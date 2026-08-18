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


def parse_citation(citation) -> tuple[str, str]:
    """Split a pre-formatted citation string into (doc, detail) for display.

    sources[] items come from the backend's rag.format_citation as
    "Doc → Section, p.N" or "Doc, p.N". Parse those shapes when possible;
    otherwise fall back to showing the raw value. Never raises.
    """
    if not isinstance(citation, str) or not citation.strip():
        return "Unknown source", ""
    text = citation.strip()
    if " → " in text:
        doc, detail = text.split(" → ", 1)
        return doc.strip(), detail.strip()
    if ", p." in text:
        doc, page = text.rsplit(", p.", 1)
        return doc.strip(), f"p. {page.strip()}"
    return text, ""
