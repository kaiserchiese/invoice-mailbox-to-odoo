"""The mailbox over IMAP, read-only. Stdlib only.

Gmail only (X-GM-RAW search, \\All folder). Another provider needs a plain
IMAP SEARCH translation of each rule's query; add it when a second provider exists.
"""

from __future__ import annotations

import contextlib
import email
import imaplib
import os
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from email.message import Message

from .rules import Rule


@dataclass(frozen=True)
class Credentials:
    user: str
    password: str = field(repr=False)
    host: str = "imap.gmail.com"

    @classmethod
    def from_env(cls) -> Credentials:
        user = os.environ.get("MAILBOX_IMAP_USER", "")
        password = os.environ.get("MAILBOX_IMAP_PASSWORD", "")
        if not user or not password:
            raise RuntimeError("Set MAILBOX_IMAP_USER and MAILBOX_IMAP_PASSWORD (a Google app password)")
        return cls(user, password, os.environ.get("MAILBOX_IMAP_HOST") or "imap.gmail.com")


def all_mail_folder(conn: imaplib.IMAP4_SSL) -> str:
    """The folder with ALL the mail, found by its \\All flag: its name changes with
    the account language ('[Gmail]/Todos')."""
    _, folders = conn.list()
    for line in folders:
        text = line.decode() if isinstance(line, bytes) else str(line)
        if "\\All" in text:
            return text.rsplit(' "/" ', 1)[-1]
    return '"[Gmail]/All Mail"'


@contextmanager
def connect(credentials: Credentials) -> Iterator[imaplib.IMAP4_SSL]:
    conn = imaplib.IMAP4_SSL(credentials.host, ssl_context=ssl.create_default_context())
    try:
        conn.login(credentials.user, credentials.password)
        conn.select(all_mail_folder(conn), readonly=True)
        yield conn
    finally:
        with contextlib.suppress(imaplib.IMAP4.error):
            conn.logout()


def search(conn: imaplib.IMAP4_SSL, query: str) -> list[bytes]:
    """UIDs for the same search as in Gmail's web box. Sent as a literal so quotes
    and accents in the query survive."""
    conn.literal = query.encode("utf-8")  # type: ignore[assignment]  # imaplib accepts bytes
    status, data = conn.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
    if status != "OK":
        raise RuntimeError(f"Gmail rejected the search {query!r}: {data!r}")
    return data[0].split() if data and data[0] else []


def read(conn: imaplib.IMAP4_SSL, uid: bytes) -> Message:
    status, data = conn.uid("FETCH", uid.decode(), "(BODY.PEEK[])")
    raw = data[0][1] if status == "OK" and data and isinstance(data[0], tuple) else None
    if not isinstance(raw, bytes):
        raise RuntimeError(f"Could not read mail {uid!r}")
    return email.message_from_bytes(raw)


def search_rule(conn: imaplib.IMAP4_SSL, rule: Rule, since: date) -> list[Message]:
    """Every mail of one rule sent on or after `since`."""
    return [read(conn, uid) for uid in search(conn, f"{rule.query} after:{since:%Y/%m/%d}")]
