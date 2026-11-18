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

# Fix 1a: a bare single-integer "number" ("1.", "2.", "8.") is never trusted
# as a real heading -- every real subsection heading in this corpus is
# dotted ("1.2", "3.4.1", ...); a bare integer followed by a capitalized
# word is what an ordinary numbered list item ("1. Verbal warning") looks
# like too, and _NUMBERED_CLAUSE_RE can't otherwise tell the two apart.
# Verified empirically across the whole corpus before hardcoding this (see
# git history / the diagnostic that added this comment): every bare-integer
# match found was either a list item or a TOC line with a trailing page
# number ("1 Purpose 3") -- the real body headings those TOC lines describe
# are rendered as markdown "#" headings ("## 1 Purpose"), a different branch
# entirely, unaffected by this rule. No genuine bare-integer body heading
# was found anywhere in the corpus.
_BULLET_PREFIX_RE = re.compile(r"^[-*•]\s+")

# Fix 1d: a dotted numbered-clause line ending in a bare, whitespace-
# separated trailing integer ("3.1 Screening 3", "3.8 Whistleblower policy
# 9") is a table-of-contents entry with its page number baked in, not a
# real heading -- a real heading in this corpus's style either ends in the
# heading text itself or is bold-terminated ("1.4 **NOMINATION...**"),
# never a lone trailing digit separated by whitespace from the preceding
# words. Verified empirically across the whole corpus before hardcoding
# this: every match was one of HR Security Policy's own numbered TOC lines
# (the one document in the corpus whose TOC uses "N.M Title P" numbered
# style instead of bullets) -- no genuine heading anywhere ends this way.
_TRAILING_PAGE_NUMBER_RE = re.compile(r"\s\d+\s*$")

# Boundary-finding ONLY (see _first_real_heading_offset) -- NOT used by the
# main detect_headings() clause branch, which stays governed strictly by
# _NUMBERED_CLAUSE_RE + the Fix 1a/1b/1c filter exactly as specified.
#
# Every real subsection heading in this corpus is bold-styled by
# pymupdf4llm ("1.1 **OBJECTIVE**"), which _NUMBERED_CLAUSE_RE's
# `[A-Z]`-immediately-after-the-number requirement does NOT match (the
# next character is "*", not a letter) -- confirmed empirically: real
# headings never actually go through the clause branch at all, in either
# the old code or this one; they've always been caught by the ALL-CAPS
# branch instead. That means _accepted_clause_number alone can never find
# a boundary for Fix 2 to gate the all-caps branch against -- it would
# always come back empty and silently disable Fix 2's TOC check (this was
# caught by testing against the real corpus before trusting it, not
# assumed). This pattern tolerates 0-2 leading "*" after the number so a
# bold real heading counts as a boundary candidate too, without changing
# what the main clause branch itself accepts as a heading.
_NUMBERED_BOLD_HEADING_RE = re.compile(r"^(\d+\.\d+(?:\.\d+)*)\.?\s+\*{0,2}[A-Z]")


def _parse_number_path(number_str: str) -> tuple[int, ...]:
    return tuple(int(part) for part in number_str.split("."))


def _is_plausible_next_heading_number(path: tuple[int, ...], candidate: tuple[int, ...]) -> bool:
    """Fix 1b: is `candidate` a plausible NEXT real heading number given
    `path` (the last ACCEPTED heading's own number, or () if none yet)?

    Plausible means: a sibling at some shared depth with a LARGER value
    than what's there now (e.g. 1.2 -> 1.3 or 1.2 -> 1.4 -- skipping ahead
    is fine, a real document doesn't always number every single value), or
    a child one level deeper than the current path starting fresh at .1
    (e.g. 1.3 -> 1.3.1). Anything else -- equal to, or smaller than, what's
    already been seen at the point the two numbers diverge -- is a restart
    (e.g. 1.3 -> 1.1 after 1.3 was already accepted) and is rejected: no
    real document's heading numbering goes backward.
    """
    if not path:
        return True
    common = 0
    while common < len(path) and common < len(candidate) and path[common] == candidate[common]:
        common += 1
    if common == len(candidate):
        # candidate is a prefix of (or identical to) path -- not a forward move.
        return False
    if common == len(path):
        # path is a prefix of candidate -- going deeper is only plausible
        # starting fresh at .1, not jumping straight to .2+.
        return candidate[common] == 1
    # They diverge at `common`: only forward (strictly greater) is plausible.
    return candidate[common] > path[common]


def _is_all_caps_heading(line: str) -> bool:
    s = line.strip()
    if not (3 <= len(s) <= 80):
        return False
    if not any(c.isalpha() for c in s):
        return False
    return s == s.upper() and s != s.lower()


_MARKDOWN_EMPHASIS_RE = re.compile(r"[*_]{1,3}")

# One specific, verified pymupdf4llm rendering artifact: HR Security
# Policy-V1.0.pdf's "4 Roles and responsibilities" heading extracts as
# "4 Roles and res onsibilities p" (a stray mid-word space plus a trailing
# "p", from the PDF's own glyph run, not from anything this pipeline's code
# does upstream of _clean_heading_text). Confirmed by grepping every PDF's
# freshly-extracted page text corpus-wide before adding this: the exact
# "res onsibilities" substring appears exactly once, on exactly this page of
# exactly this document -- no other document's heading is affected.
_KNOWN_GARBLED_HEADINGS = {
    "4 Roles and res onsibilities p": "4 Roles and Responsibilities",
}


def _clean_heading_text(text: str) -> str:
    """pymupdf4llm renders bold/italic PDF text as markdown emphasis
    (**bold**, *italic*), and a document's headings are very often just a
    bold run end to end -- e.g. "## **1. Scope, Definitions**" -- so left
    alone, every citation and LLM context line downstream would show the
    literal "**" markers instead of clean heading text. Strip them once
    here, at the point the heading is captured, rather than patching every
    place that later displays a section/subsection string.
    """
    cleaned = _MARKDOWN_EMPHASIS_RE.sub("", text).strip()
    return _KNOWN_GARBLED_HEADINGS.get(cleaned, cleaned)


def _accepted_clause_number(
    stripped: str, prev_nonblank: str, path: tuple[int, ...]
) -> tuple[int, ...] | None:
    """The four-part filter for treating a _NUMBERED_CLAUSE_RE match as a
    real heading rather than an ordinary numbered list item or TOC entry --
    see Fix 1a/1b/1c/1d in this module's git history. Returns the parsed
    number path if ALL four checks pass, else None. `path` is the last
    ACCEPTED clause heading's own number (empty tuple if none yet)."""
    m = _NUMBERED_CLAUSE_RE.match(stripped)
    if not m:
        return None
    number = m.group(1)
    if "." not in number:  # Fix 1a: bare integers are never trusted
        return None
    candidate = _parse_number_path(number)
    if not _is_plausible_next_heading_number(path, candidate):  # Fix 1b
        return None
    if prev_nonblank.endswith(":"):  # Fix 1c: list introduced by a colon sentence
        return None
    if _TRAILING_PAGE_NUMBER_RE.search(stripped):  # Fix 1d: TOC line with a baked-in page number
        return None
    return candidate


def _first_real_heading_offset(text: str) -> int | None:
    """Fix 2's TOC-boundary proxy: the offset of the first unambiguous real
    heading (a markdown "#" heading, or a numbered-clause match that passes
    Fix 1a/1b/1c), whichever comes first. Deliberately does NOT consider the
    all-caps branch here -- that's exactly the branch Fix 2 needs a boundary
    for, so it can't also be used to establish one.

    There's no dedicated table-of-contents-block detector anywhere in this
    ingestion pipeline (checked before adding this), so "before the first
    real numbered/markdown heading" is the proxy used instead, per the task
    that introduced this function. This is an approximation, flagged as one
    on purpose: a document whose real body content genuinely starts before
    its own first detectable heading (e.g. an un-numbered, non-"#" opening
    paragraph followed only by ALL-CAPS-styled headings throughout) would
    have its front matter boundary estimated as "the whole document," which
    would fall back to today's un-filtered all-caps behavior for that
    document specifically. Worth revisiting if that ever shows up in
    practice -- no document in the corpus this was built against does this.
    """
    offset = 0
    prev_nonblank = ""
    path: tuple[int, ...] = ()
    for line in text.split("\n"):
        stripped = line.strip()
        if _MD_HEADING_RE.match(stripped):
            return offset
        candidate = _accepted_clause_number(stripped, prev_nonblank, path)
        if candidate is not None:
            return offset
        if _NUMBERED_BOLD_HEADING_RE.match(stripped):
            return offset
        if stripped:
            prev_nonblank = stripped
        offset += len(line) + 1
    return None


def detect_headings(text: str) -> list[tuple[int, int, str]]:
    """Scan the whole-document text for heading-like lines. Returns a list of
    (char_offset, level, heading_text) sorted by offset (built in reading
    order).

    Three branches, in priority order: markdown "#" headings (trusted
    outright -- pymupdf4llm only emits these for genuine structural
    headings, never for prose), numbered clauses ("1.2 Eligibility") that
    pass the Fix 1a/1b/1c filter in _accepted_clause_number, and ALL-CAPS
    lines that are neither bulleted nor inside the document's presumed
    front-matter/TOC block (Fix 2) -- a bare, unfiltered ALL-CAPS check
    matches a TOC's own bullet list ("- **OBJECTIVE**") exactly as readily
    as a real body heading ("1.4 **NOMINATION...**"), which is why both
    guards are needed here rather than only one.
    """
    toc_boundary = _first_real_heading_offset(text)
    headings: list[tuple[int, int, str]] = []
    offset = 0
    prev_nonblank = ""
    clause_path: tuple[int, ...] = ()
    for line in text.split("\n"):
        stripped = line.strip()
        md_match = _MD_HEADING_RE.match(stripped)
        clause_number = None if md_match else _accepted_clause_number(stripped, prev_nonblank, clause_path)
        if md_match:
            level = len(md_match.group(1))
            headings.append((offset, level, _clean_heading_text(md_match.group(2))))
        elif clause_number is not None:
            clause_path = clause_number
            level = len(clause_number)
            headings.append((offset, level, _clean_heading_text(stripped)))
        elif (
            _is_all_caps_heading(stripped)
            and not _BULLET_PREFIX_RE.match(stripped)
            and (toc_boundary is None or offset >= toc_boundary)
        ):
            headings.append((offset, 1, _clean_heading_text(stripped).title()))
        if stripped:
            prev_nonblank = stripped
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
