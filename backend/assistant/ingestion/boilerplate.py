"""2. Boilerplate stripping (repeated headers/footers, "Page X of Y", etc.)."""

import re

# Boilerplate detection: a (normalized) line that repeats across at least
# this fraction of a document's pages is treated as a running header/footer
# and stripped before chunking. Skipped entirely for very short documents,
# where "repeats across most pages" isn't a meaningful signal.
BOILERPLATE_MIN_PAGES = 3
BOILERPLATE_FREQUENCY_THRESHOLD = 0.6

_DIGIT_RE = re.compile(r"\d+")


def _normalize_line(line: str) -> str:
    # Collapse digit runs so "Page 3 of 42" and "Page 4 of 42" normalize to
    # the same signature ("page # of #") and count as the same repeated line.
    return _DIGIT_RE.sub("#", line.strip().lower())


def strip_boilerplate(page_texts: list[str]) -> list[str]:
    if len(page_texts) < BOILERPLATE_MIN_PAGES:
        return page_texts

    per_page_lines = [text.split("\n") for text in page_texts]
    line_page_counts: dict[str, int] = {}
    for lines in per_page_lines:
        seen_this_page = set()
        for line in lines:
            norm = _normalize_line(line)
            if not norm or norm in seen_this_page:
                continue
            seen_this_page.add(norm)
            line_page_counts[norm] = line_page_counts.get(norm, 0) + 1

    threshold = len(page_texts) * BOILERPLATE_FREQUENCY_THRESHOLD
    boilerplate = {norm for norm, count in line_page_counts.items() if count >= threshold}

    return [
        "\n".join(line for line in lines if _normalize_line(line) not in boilerplate)
        for lines in per_page_lines
    ]
