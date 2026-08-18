"""Context formatting for the LLM prompt, "cite what you use" label
extraction, and citation dict formatting for the UI.
"""

import re
from pathlib import Path


def format_context(docs) -> str:
    """Build the context block shown to the LLM. Each chunk gets a 1-indexed
    numeric label ("[1]", "[2]", ...) in addition to its existing
    source/section/page/type header.

    The label is what makes "cite what you use" enforceable in code, not
    just in the prompt: previously the Sources list was built from EVERY
    retrieved chunk regardless of whether the model actually relied on it,
    so a same-shaped-but-wrong-company chunk that MMR retrieved (these
    sample HR handbooks are near-identical in structure) but the model
    correctly ignored still showed up as a cited source -- that's what
    drove citation precision down to ~0.77. Now the model cites a chunk's
    label inline only when it actually uses it, and qa.answer_question()
    builds the Sources list from exactly those labels, not from the full
    retrieved set.
    """
    parts = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        section = doc.metadata.get("section", "")
        subsection = doc.metadata.get("subsection", "")
        heading = " > ".join(part for part in (section, subsection) if part)

        # is_table is set by ingestion. is_image is read defensively --
        # ingestion does not currently tag any chunk is_image (there's no
        # per-image extraction yet, only whole-page OCR fallback), so this
        # branch is forward-compatible dead code until that's added, not
        # something already wired end-to-end.
        tags = []
        if doc.metadata.get("is_table"):
            tags.append("Table")
        if doc.metadata.get("is_image"):
            tags.append("OCR'd Image")
        type_suffix = f", Type: {'/'.join(tags)}" if tags else ""

        header = f"[{i}] [Source: {source}, Section: {heading or 'N/A'}, Page: {page}{type_suffix}]"
        parts.append(f"{header}\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


_CITATION_LABEL_RE = re.compile(r"\[(\d+)\]")


def extract_cited_docs(answer_text: str, docs: list) -> list:
    """Return the subset of retrieved `docs` whose numeric label actually
    appears in the model's answer text, in first-appearance order. Labels
    outside the valid 1..len(docs) range (a hallucinated label number) are
    silently ignored rather than crashing -- rule 4 in the prompt tells the
    model never to invent one, but this is the defensive backstop.
    """
    cited_indices = []
    for match in _CITATION_LABEL_RE.finditer(answer_text):
        n = int(match.group(1))
        if 1 <= n <= len(docs) and n not in cited_indices:
            cited_indices.append(n)
    return [docs[n - 1] for n in cited_indices]


def dedupe_sources(docs) -> list[dict]:
    seen = set()
    sources = []
    for doc in docs:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        section = doc.metadata.get("section", "")
        subsection = doc.metadata.get("subsection", "")
        key = (source, section, subsection, page)
        if key not in seen:
            seen.add(key)
            sources.append({"source": source, "page": page, "section": section, "subsection": subsection})
    # Two different sections (or subsections within the same section) can
    # legitimately live on the same page, so sort on source/page first and
    # use section/subsection only as tiebreakers.
    sources.sort(
        key=lambda s: (s["source"], s["page"] if isinstance(s["page"], int) else 0, s["section"], s["subsection"])
    )
    return sources


def format_citation(s: dict) -> str:
    """Render one source dict as "Employee Handbook -> Leave Policy ->
    Sick Leave Accrual, p.12" -- dropping the "->" hops for whichever of
    section/subsection are missing, down to just "Employee Handbook, p.12"
    when neither is present."""
    title = Path(s["source"]).stem  # drop the .pdf extension for readability
    heading = " → ".join(part for part in (s.get("section"), s.get("subsection")) if part)
    if heading:
        return f"{title} → {heading}, p.{s['page']}"
    return f"{title}, p.{s['page']}"
