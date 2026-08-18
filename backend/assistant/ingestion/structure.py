"""3. Whole-document text stream + page offsets, section-heading detection,
and table-span detection -- all operating on the concatenated document text
so chunking (and its overlap) can span page boundaries.
"""

import bisect
import re

PAGE_SEPARATOR = "\n\n"


# --------------------------------------------------------------------------
# Whole-document text stream + page offset lookup (fixes cross-page overlap)
# --------------------------------------------------------------------------


def build_full_text(page_texts: list[str]) -> tuple[str, list[int]]:
    """Concatenate all pages into one stream and record each page's start
    offset within it, so a chunk's character offset can be mapped back to
    the page it starts on (via bisect) after chunking the WHOLE document."""
    parts = []
    offsets = []
    offset = 0
    for text in page_texts:
        offsets.append(offset)
        parts.append(text)
        offset += len(text)
        parts.append(PAGE_SEPARATOR)
        offset += len(PAGE_SEPARATOR)
    return "".join(parts), offsets


def offset_to_page(offset: int, page_offsets: list[int]) -> int:
    idx = bisect.bisect_right(page_offsets, offset) - 1
    return max(0, idx) + 1  # 1-indexed


# --------------------------------------------------------------------------
# Section-heading detection
#
# Each detected heading now carries a LEVEL, not just its text, so citations
# can show a two-tier "section -> subsection" breadcrumb instead of just
# whichever single heading happened to be nearest (which, for a chunk nested
# under a sub-heading, used to silently throw away which major section it
# was in). Level is markdown "#" count, ALL-CAPS always 1, or a numbered
# clause's dot-count + 1 ("3." -> 1, "3.1" -> 2, "3.1.2" -> 3).
#
# IMPORTANT: level is NOT the same thing as "is this a section or a
# subsection" -- see determine_section_level below for why, and don't assume
# level 1 == section when reading resolve_heading_path.
# --------------------------------------------------------------------------

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_NUMBERED_CLAUSE_RE = re.compile(r"^(?:Section\s+)?(\d+(?:\.\d+)*)\.?\s+[A-Z].{0,80}$")


def _is_all_caps_heading(line: str) -> bool:
    s = line.strip()
    if not (3 <= len(s) <= 80):
        return False
    if not any(c.isalpha() for c in s):
        return False
    return s == s.upper() and s != s.lower()


def detect_headings(text: str) -> list[tuple[int, int, str]]:
    """Scan the whole-document text for heading-like lines. Returns a list of
    (char_offset, level, heading_text) sorted by offset (built in reading
    order)."""
    headings = []
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        md_match = _MD_HEADING_RE.match(stripped)
        clause_match = None if md_match else _NUMBERED_CLAUSE_RE.match(stripped)
        if md_match:
            level = len(md_match.group(1))
            headings.append((offset, level, md_match.group(2).strip()))
        elif clause_match:
            level = clause_match.group(1).count(".") + 1
            headings.append((offset, level, stripped))
        elif _is_all_caps_heading(stripped):
            headings.append((offset, 1, stripped.title()))
        offset += len(line) + 1  # +1 for the "\n" split() consumed
    return headings


def determine_section_level(headings: list[tuple[int, int, str]]) -> int:
    """Figure out which heading LEVEL actually functions as "the section"
    for THIS document, rather than assuming it's always level 1.

    Real documents commonly open with exactly one shallow "#" document
    title before their real, repeated section headings begin one level
    deeper (very often "##", since pymupdf4llm renders a PDF's title as
    "#" and its numbered clauses as "##") -- every one of this project's own
    sample HR handbooks does exactly this: a single level-1 title, then ten
    level-2 numbered sections and NO level 3 at all. Hardcoding "level 1 =
    section" would make that one-off title swallow the section attribution
    for the ENTIRE document (every chunk's "section" would just be the
    document's own title, and the real numbered sections would wrongly be
    demoted to "subsection").

    So: use the SHALLOWEST level that RECURS (appears 2+ times) as the
    section level -- a one-off title doesn't recur, but a document's actual
    section headings do, almost by definition. Falls back to the shallowest
    level seen at all if nothing recurs (e.g. a very short document with
    exactly one heading at each of a few levels).
    """
    if not headings:
        return 1
    counts: dict[int, int] = {}
    for _, level, _ in headings:
        counts[level] = counts.get(level, 0) + 1
    recurring_levels = sorted(level for level, count in counts.items() if count >= 2)
    if recurring_levels:
        return recurring_levels[0]
    return min(counts)


def resolve_heading_path(
    offset: int,
    heading_positions: list[int],
    headings: list[tuple[int, int, str]],
    section_level: int,
) -> tuple[str, str]:
    """Return (section, subsection) for the given offset.

    `section` is the nearest preceding heading at or shallower than
    `section_level` (see determine_section_level). `subsection` is the
    nearest preceding heading deeper than that, but only if it falls AFTER
    that section's own start -- a leftover sub-heading from the previous
    section must not bleed into this one. Either can come back "".
    """
    idx = bisect.bisect_right(heading_positions, offset) - 1
    if idx < 0:
        return "", ""

    section_idx = idx
    while section_idx >= 0 and headings[section_idx][1] > section_level:
        section_idx -= 1
    if section_idx < 0:
        return "", ""

    section_text = headings[section_idx][2]
    if idx == section_idx:
        return section_text, ""
    return section_text, headings[idx][2]


# --------------------------------------------------------------------------
# Table detection -- tables are chunked as standalone units, never split
# --------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_MIN_ROWS = 2  # header + at least one data/separator row


def detect_table_spans(text: str) -> list[tuple[int, int]]:
    """Find contiguous runs of markdown table rows ("| a | b |") and return
    their (start_offset, end_offset) spans in the whole-document text."""
    spans = []
    run_start = None
    run_rows = 0
    offset = 0
    for line in text.split("\n"):
        line_len = len(line) + 1
        if _TABLE_ROW_RE.match(line):
            if run_start is None:
                run_start = offset
            run_rows += 1
        else:
            if run_start is not None and run_rows >= _TABLE_MIN_ROWS:
                spans.append((run_start, offset))
            run_start = None
            run_rows = 0
        offset += line_len
    if run_start is not None and run_rows >= _TABLE_MIN_ROWS:
        spans.append((run_start, offset))
    return spans
