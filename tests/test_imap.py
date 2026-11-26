"""The IMAP side, against a fake server: no network."""

from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from typing import Any

import pytest

from mailbox_to_odoo import imap
from mailbox_to_odoo.rules import Rule


def _raw(subject: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["Date"] = "Tue, 01 Sep 2026 10:00:00 +0000"
    msg.set_content("x")
    return msg.as_bytes()


class FakeImap:
    def __init__(self, found: bytes = b"1 2", search_status: str = "OK") -> None:
        self.found = found
        self.search_status = search_status
        self.literal: bytes | None = None
        self.searched: list[bytes] = []

    def list(self) -> tuple[str, list[bytes]]:
        return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/Todos"', b'(\\HasNoChildren) "/" "INBOX"']

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        if command == "SEARCH":
            assert self.literal is not None
            self.searched.append(self.literal)
            return self.search_status, [self.found]
        return "OK", [(b"1 (BODY[] {10}", _raw(f"mail {args[0]}")), b")"]


def test_all_mail_folder_is_found_by_flag_not_by_localized_name() -> None:
    assert imap.all_mail_folder(FakeImap()) == '"[Gmail]/Todos"'  # type: ignore[arg-type]


def test_search_rule_adds_since_and_reads_each_mail() -> None:
    server = FakeImap()
    rule = Rule("Acme", "Acme", 'from:billing@acme.test "tax invoice"')

    mails = imap.search_rule(server, rule, date(2026, 1, 1))  # type: ignore[arg-type]

    assert server.searched == [b'from:billing@acme.test "tax invoice" after:2026/01/01']
    assert [m["Subject"] for m in mails] == ["mail 1", "mail 2"]


def test_empty_search_returns_no_mails() -> None:
    assert imap.search_rule(FakeImap(found=b""), Rule("A", "A", "from:x"), date(2026, 1, 1)) == []  # type: ignore[arg-type]


def test_rejected_search_raises() -> None:
    with pytest.raises(RuntimeError, match="rejected"):
        imap.search(FakeImap(search_status="NO"), "from:x")  # type: ignore[arg-type]


def test_credentials_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_IMAP_USER", "someone@example.test")
    monkeypatch.setenv("MAILBOX_IMAP_PASSWORD", "not-a-real-password")
    monkeypatch.delenv("MAILBOX_IMAP_HOST", raising=False)

    expected = imap.Credentials("someone@example.test", "not-a-real-password", "imap.gmail.com")
    assert imap.Credentials.from_env() == expected


def test_missing_credentials_fail_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAILBOX_IMAP_USER", raising=False)
    monkeypatch.delenv("MAILBOX_IMAP_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="MAILBOX_IMAP_USER"):
        imap.Credentials.from_env()


def test_connection_verifies_the_server_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    import ssl

    seen: dict[str, Any] = {}

    class Conn(FakeImap):
        def __init__(self, host: str, *, ssl_context: ssl.SSLContext) -> None:
            super().__init__()
            seen["context"] = ssl_context

        def login(self, user: str, password: str) -> None: ...
        def select(self, folder: str, readonly: bool = False) -> None: ...
        def logout(self) -> None: ...

    monkeypatch.setattr(imap.imaplib, "IMAP4_SSL", Conn)

    with imap.connect(imap.Credentials("u", "p")):
        pass

    assert seen["context"].verify_mode == ssl.CERT_REQUIRED
    assert seen["context"].check_hostname
