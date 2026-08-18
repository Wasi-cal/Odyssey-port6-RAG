"""Tables are chunked as standalone units, never split unless oversized --
and when they are, split BY ROW (never by raw characters/tokens across a row
boundary), repeating the header row(s) at the top of every sub-chunk.
"""

import re
import sys

from langchain_core.documents import Document

from ..structure import offset_to_page, resolve_heading_path
from .masking import chunk_header
from .tokens import TABLE_TOKEN_CAP, decode, encode, token_len

_SEPARATOR_ROW_RE = re.compile(r"^\s*\|[\s:\-\|]+\|\s*$")


def _split_table_header(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split a table's lines into its header row(s) and its data rows, so the
    header can be repeated at the top of every sub-chunk when the table gets
    split. Treats a markdown separator row ("|---|---|") right after the
    first row as part of the header; otherwise assumes a single header row."""
    if not lines:
        return [], []
    if len(lines) >= 2 and _SEPARATOR_ROW_RE.match(lines[1]):
        return lines[:2], lines[2:]
    return lines[:1], lines[1:]


def _split_long_row(row: str, available_tokens: int) -> list[str]:
    """Last-resort split of a single row that's over the cap even by itself --
    slices by raw tokens rather than by row, since there's no smaller natural
    unit than the row left to split on."""
    token_ids = encode(row)
    available_tokens = max(available_tokens, 1)
    return [decode(token_ids[i : i + available_tokens]) for i in range(0, len(token_ids), available_tokens)]


def _split_table_into_chunks(table_text: str, source: str, page: int) -> list[str]:
    """Split an oversized table BY ROWS (never by raw characters/tokens
    across a row boundary), repeating the header row(s) at the top of every
    sub-chunk so each piece is self-describing on its own. Returns a list of
    table-text pieces (without the outer "{filename} — {section} > {subsection}"
    chunk header, which the caller adds uniformly)."""
    lines = [line for line in table_text.split("\n") if line.strip()]
    header_lines, data_lines = _split_table_header(lines)
    header_text = "\n".join(header_lines)
    header_tokens = token_len(header_text)

    # Greedily pack data rows into groups that stay under TABLE_TOKEN_CAP
    # together with the repeated header.
    groups: list[list[str]] = []
    current_rows: list[str] = []
    for row in data_lines:
        candidate = current_rows + [row]
        candidate_text = header_text + "\n" + "\n".join(candidate)
        if current_rows and token_len(candidate_text) > TABLE_TOKEN_CAP:
            groups.append(current_rows)
            current_rows = [row]
        else:
            current_rows = candidate
    if current_rows:
        groups.append(current_rows)

    sub_tables = []
    for group in groups:
        group_text = header_text + "\n" + "\n".join(group)
        if token_len(group_text) <= TABLE_TOKEN_CAP:
            sub_tables.append(group_text)
            continue

        # This only happens when a SINGLE row (plus the header) is already
        # over the cap -- the greedy loop above never lets a group grow past
        # the cap once it holds more than one row.
        print(
            f"[ingest] WARNING: {source} p.{page}: a table row exceeds "
            f"TABLE_TOKEN_CAP ({TABLE_TOKEN_CAP} tokens) even on its own -- "
            f"splitting it by tokens instead of by row.",
            file=sys.stderr,
        )
        available = TABLE_TOKEN_CAP - header_tokens
        for row in group:
            for piece in _split_long_row(row, available):
                sub_tables.append(header_text + "\n" + piece)

    if not sub_tables:
        # Pathological edge case: a "table" with header/separator rows but no
        # data rows at all. Still emit something rather than silently
        # dropping this span's content.
        sub_tables = [header_text or table_text]

    return sub_tables


def build_table_chunks(
    filename: str,
    full_text: str,
    table_spans: list[tuple[int, int]],
    page_offsets: list[int],
    headings: list[tuple[int, int, str]],
    heading_positions: list[int],
    section_level: int,
) -> list[Document]:
    chunks = []
    for start, end in table_spans:
        table_text = full_text[start:end].strip("\n")
        if not table_text.strip():
            continue
        page = offset_to_page(start, page_offsets)
        section, subsection = resolve_heading_path(start, heading_positions, headings, section_level)
        header = chunk_header(filename, section, subsection)

        if token_len(header + table_text) <= TABLE_TOKEN_CAP:
            # Common case: the whole table fits comfortably -- keep it as one
            # self-contained chunk, same as before.
            sub_tables = [table_text]
        else:
            # Oversized table (problem #1): split BY ROWS instead of letting
            # it get silently truncated at embed time.
            sub_tables = _split_table_into_chunks(table_text, filename, page)

        for part_index, sub_table_text in enumerate(sub_tables):
            chunks.append(
                Document(
                    page_content=header + sub_table_text,
                    metadata={
                        "source": filename,
                        "page": page,
                        "section": section,
                        "subsection": subsection,
                        "is_table": True,
                        "table_part": part_index,
                    },
                )
            )
    return chunks
