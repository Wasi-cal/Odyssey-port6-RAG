"""Chat domain model + citation-string parsing."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    meta: dict | None = None


class ChatSession(BaseModel):
    id: str
    title: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.messages

    def add_message(self, role: str, content: str, meta: dict | None = None) -> ChatMessage:
        """Append a message. The first user message becomes the session's
        title (truncated to 40 chars), matching what shows up in the
        sidebar's Chat History list.
        """
        message = ChatMessage(role=role, content=content, meta=meta)
        self.messages.append(message)
        if self.title is None and role == "user":
            self.title = content[:40] + ("…" if len(content) > 40 else "")
        return message


def parse_citation(citation) -> tuple[str, str, str]:
    """Split a pre-formatted citation string into (doc, heading, page_label)
    for display, page-first.

    sources[] items come from the backend's rag.format_citation as
    "Doc → Section, p.N", "Doc → Section → Subsection, p.N", or "Doc, p.N".
    Parse those shapes when possible; otherwise fall back to showing the raw
    value as `doc` with no heading/page. Never raises.
    """
    if not isinstance(citation, str) or not citation.strip():
        return "Unknown source", "", ""
    text = citation.strip()

    page_label = ""
    if ", p." in text:
        text, page_part = text.rsplit(", p.", 1)
        page_label = f"Pg {page_part.strip()}"

    if " → " in text:
        doc, heading = text.split(" → ", 1)
        return doc.strip(), heading.strip(), page_label
    return text.strip(), "", page_label
