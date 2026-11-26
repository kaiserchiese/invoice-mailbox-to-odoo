"""Edges the README promises: per-supplier rules, folders, mails without a PDF."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from mailbox_to_odoo import __main__ as cli
from mailbox_to_odoo import folder, imap, rules
from mailbox_to_odoo.rules import Rule


def _mail(attachments: list[tuple[str, bytes]], subject: str = "Invoice") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["Date"] = "Tue, 01 Sep 2026 10:00:00 +0000"
    msg.set_content("attached")
    for name, content in attachments:
        msg.add_attachment(content, maintype="application", subtype="pdf", filename=name)
    return msg


def test_same_pdf_for_two_suppliers_is_filed_under_each(tmp_path: Path) -> None:
    pdf = _mail([("INV-1.pdf", b"%PDF-shared")])
    one, two = Rule("One", "One", "from:a"), Rule("Two", "Two", "from:b")

    plan = folder.plan(tmp_path, [(one, pdf), (two, pdf)])

    assert sorted(str(n.target.relative_to(tmp_path)) for n in plan.new) == [
        str(Path("One") / "INV-1.pdf"),
        str(Path("Two") / "INV-1.pdf"),
    ]


def test_attachment_regex_ignores_case(tmp_path: Path) -> None:
    rule = Rule("Acme", "Acme", "from:a", attachment="^inv-")

    plan = folder.plan(tmp_path, [(rule, _mail([("INV-9.pdf", b"%PDF-9")]))])

    assert [n.target.name for n in plan.new] == ["INV-9.pdf"]


def test_annex_only_mail_is_not_reported_as_missing_pdf(tmp_path: Path) -> None:
    rule = Rule("Acme", "Acme", "from:a", attachment="^INV-")

    plan = folder.plan(tmp_path, [(rule, _mail([("contract.pdf", b"%PDF-c")]))])

    assert plan.new == [] and plan.without_pdf == []


def test_missing_supplier_folder_counts_as_empty(tmp_path: Path) -> None:
    assert folder.pdfs_in(tmp_path / "does-not-exist") == []


def test_non_pdf_files_in_the_folder_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a.PDF").write_bytes(b"%PDF")

    assert [p.name for p in folder.pdfs_in(tmp_path)] == ["a.PDF"]


def test_existing_file_with_same_name_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "Acme").mkdir()
    (tmp_path / "Acme" / "INV-1.pdf").write_bytes(b"%PDF-mine")
    rule = Rule("Acme", "Acme", "from:a")

    folder.write(folder.plan(tmp_path, [(rule, _mail([("INV-1.pdf", b"%PDF-other")]))]))

    assert (tmp_path / "Acme" / "INV-1.pdf").read_bytes() == b"%PDF-mine"


def test_rules_file_without_since_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("rules: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="since"):
        rules.load(path)


def test_rules_without_query_are_not_searched(monkeypatch: pytest.MonkeyPatch) -> None:
    searched: list[str] = []

    @contextmanager
    def fake_connect(_credentials: imap.Credentials) -> Any:
        yield object()

    def fake_search(_conn: Any, rule: Rule, _since: date) -> list[EmailMessage]:
        searched.append(rule.name)
        return []

    monkeypatch.setattr(imap, "connect", fake_connect)
    monkeypatch.setattr(imap, "search_rule", fake_search)
    config = rules.Config(date(2026, 1, 1), (Rule("Mail", "Mail", "from:a"), Rule("Portal", "Portal")))

    assert cli.fetch(imap.Credentials("u", "p"), config) == []
    assert searched == ["Mail"]


def test_cli_lists_mails_without_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("since: 2026-01-01\nrules:\n  - {name: Acme, folder: Acme, query: 'from:a'}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "fetch", lambda _c, config: [(config.rules[0], _mail([], "Your invoice is ready"))])
    monkeypatch.setattr(imap.Credentials, "from_env", classmethod(lambda cls: imap.Credentials("u", "p")))

    cli.main([str(path), str(tmp_path / "out")])

    assert "? Acme 2026-09-01 'Your invoice is ready': no PDF attached" in capsys.readouterr().out
