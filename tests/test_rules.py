"""The rules file and the command line."""

from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from pathlib import Path

import pytest

from mailbox_to_odoo import __main__ as cli
from mailbox_to_odoo import imap, rules

RULES = """
since: 2026-01-01
rules:
  - name: Acme Hosting
    folder: Acme Hosting
    query: 'from:billing@acme.test has:attachment'
    attachment: '^INV-'
  - {name: Portal only, folder: Portal}
"""


def test_load_reads_rules_and_since(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(RULES, encoding="utf-8")

    config = rules.load(path)

    assert config.since == date(2026, 1, 1)
    query = "from:billing@acme.test has:attachment"
    assert config.rules[0] == rules.Rule("Acme Hosting", "Acme Hosting", query, "^INV-")
    assert config.rules[1].query == ""


def _mail() -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Invoice"
    msg["Date"] = "Tue, 01 Sep 2026 10:00:00 +0000"
    msg.set_content("x")
    msg.add_attachment(b"%PDF-1", maintype="application", subtype="pdf", filename="INV-1.pdf")
    return msg


@pytest.mark.parametrize(("execute", "written"), [(False, False), (True, True)])
def test_cli_is_dry_run_unless_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], execute: bool, written: bool
) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(RULES, encoding="utf-8")
    monkeypatch.setattr(cli, "fetch", lambda _c, config: [(config.rules[0], _mail())])
    monkeypatch.setattr(imap.Credentials, "from_env", classmethod(lambda cls: imap.Credentials("u", "p")))

    code = cli.main([str(path), str(tmp_path / "out"), *(["--execute"] if execute else [])])

    assert code == 0
    assert (tmp_path / "out" / "Acme Hosting" / "INV-1.pdf").exists() is written
    assert "1 new" in capsys.readouterr().out


def test_cli_survives_a_console_that_cannot_print_the_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    path = tmp_path / "rules.yaml"
    path.write_text("since: 2026-01-01\nrules:\n  - {name: Acme, folder: Acme, query: 'from:a'}\n", encoding="utf-8")
    msg = EmailMessage()
    msg["Subject"], msg["Date"] = "Faktura Łódź", "Tue, 01 Sep 2026 10:00:00 +0000"
    msg.set_content("x")
    monkeypatch.setattr(cli, "fetch", lambda _c, config: [(config.rules[0], msg)])
    monkeypatch.setattr(imap.Credentials, "from_env", classmethod(lambda cls: imap.Credentials("u", "p")))
    monkeypatch.setattr("sys.stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

    assert cli.main([str(path), str(tmp_path / "out")]) == 0


def test_load_reads_the_partner_of_a_rule(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "since: 2026-01-01\nrules:\n  - {name: A, folder: A, partner: 'Acme Hosting SL'}\n  - {name: B, folder: B}\n",
        encoding="utf-8",
    )

    config = rules.load(path)

    assert config.rules[0].partner == "Acme Hosting SL"
    assert config.rules[1].partner == ""
