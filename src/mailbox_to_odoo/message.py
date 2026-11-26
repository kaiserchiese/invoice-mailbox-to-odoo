"""What is taken out of one mail: its PDFs, its date and the name a PDF is filed under."""

from __future__ import annotations

import re
from datetime import date
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

_NOT_ALLOWED = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _decoded(value: str) -> str:
    """MIME encoded words ('=?utf-8?q?...?=') to text. Plain text passes through."""
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):  # unknown or wrong charset label: keep the raw name
        return value


def pdfs(msg: Message) -> list[tuple[str, bytes]]:
    """PDF attachments. Many senders use octet-stream: the extension decides."""
    found = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        name = _decoded(part.get_filename() or "")
        is_pdf = part.get_content_type() == "application/pdf" or name.lower().endswith(".pdf")
        content = part.get_payload(decode=True)
        if is_pdf and isinstance(content, bytes) and content:
            found.append((name or "invoice.pdf", content))
    return found


def day(msg: Message) -> date:
    return parsedate_to_datetime(msg["Date"]).date()


def subject(msg: Message) -> str:
    return _decoded(str(msg["Subject"] or ""))


def filename(original: str, sent: date) -> str:
    """The attachment name, which usually carries the invoice number.

    Without any digit ("invoice.pdf") the mail date goes in front: otherwise two
    months of the same supplier collide and the second looks like a duplicate.
    """
    clean = _NOT_ALLOWED.sub("_", original).strip() or "invoice.pdf"
    if not clean.lower().endswith(".pdf"):
        clean += ".pdf"
    if not any(c.isdigit() for c in clean):
        clean = f"{sent.isoformat()} {clean}"
    return clean
