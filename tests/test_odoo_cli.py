"""The command line with --odoo: dry run first, --execute to write, --watch to repeat."""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest

from fake_odoo import FakeOdoo
from mailbox_to_odoo import __main__ as cli
from mailbox_to_odoo import imap, odoo

RULES = """
since: 2026-01-01
rules:
  - {name: Acme, folder: Acme, query: 'from:billing@acme.test', partner: 'Acme Hosting SL'}
"""


def mail(message_id: str = "<m1@acme.test>", name: str = "INV-1.pdf", body: bytes = b"%PDF-1 one") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["Message-ID"] = "Invoice", message_id
    msg["Date"] = "Tue, 01 Sep 2026 10:00:00 +0000"
    msg.set_content("x")
    msg.add_attachment(body, maintype="application", subtype="pdf", filename=name)
    return msg


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, FakeOdoo]:
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    fake = FakeOdoo()
    fake.add("res.partner", name="Acme Hosting SL")
    monkeypatch.setattr(cli, "fetch", lambda _c, config: [(config.rules[0], mail())])
    monkeypatch.setattr(cli, "connect_odoo", lambda: fake)
    monkeypatch.setattr(imap.Credentials, "from_env", classmethod(lambda cls: imap.Credentials("u", "p")))
    monkeypatch.delenv("ODOO_JOURNAL", raising=False)
    return rules, fake


def test_odoo_dry_run_reports_and_writes_nothing(
    env: tuple[Path, FakeOdoo], capsys: pytest.CaptureFixture[str]
) -> None:
    rules, fake = env

    assert cli.main([str(rules), "--odoo"]) == 0

    out = capsys.readouterr().out
    assert "Odoo: 1 new" in out and "INV-1.pdf" in out and "--execute" in out
    assert fake.writes() == []


def test_odoo_execute_creates_the_draft_bill(env: tuple[Path, FakeOdoo], capsys: pytest.CaptureFixture[str]) -> None:
    rules, fake = env

    assert cli.main([str(rules), "--odoo", "--execute"]) == 0

    assert len(fake.tables["account.move"]) == 1
    assert "INV-1.pdf -> bill" in capsys.readouterr().out
    assert cli.main([str(rules), "--odoo", "--execute"]) == 0  # again: nothing new
    assert len(fake.tables["account.move"]) == 1


def test_odoo_and_folder_can_run_together(env: tuple[Path, FakeOdoo], tmp_path: Path) -> None:
    rules, fake = env

    cli.main([str(rules), str(tmp_path / "out"), "--odoo", "--execute"])

    assert (tmp_path / "out" / "Acme" / "INV-1.pdf").exists() and len(fake.tables["account.move"]) == 1


def test_it_needs_a_folder_or_odoo(env: tuple[Path, FakeOdoo]) -> None:
    with pytest.raises(SystemExit):
        cli.main([str(env[0])])


def test_a_bad_supplier_rule_makes_the_exit_code_fail(env: tuple[Path, FakeOdoo]) -> None:
    rules, fake = env
    rules.write_text(RULES.replace("Acme Hosting SL", "Nobody"), encoding="utf-8")

    assert cli.main([str(rules), "--odoo", "--execute"]) == 1
    assert fake.writes() == []


def test_the_journal_comes_from_its_code(env: tuple[Path, FakeOdoo], monkeypatch: pytest.MonkeyPatch) -> None:
    rules, fake = env
    journal = fake.add("account.journal", code="BILL", type="purchase")
    monkeypatch.setenv("ODOO_JOURNAL", "BILL")

    cli.main([str(rules), "--odoo", "--execute"])

    assert len(fake.tables["account.move"]) == 1 and journal in fake.tables["account.journal"]


def test_an_unknown_journal_stops_the_run(env: tuple[Path, FakeOdoo], monkeypatch: pytest.MonkeyPatch) -> None:
    rules, fake = env
    monkeypatch.setenv("ODOO_JOURNAL", "NOPE")

    assert cli.main([str(rules), "--odoo", "--execute"]) == 1
    assert fake.writes() == []


def test_watch_needs_execute(env: tuple[Path, FakeOdoo]) -> None:
    with pytest.raises(SystemExit):
        cli.main([str(env[0]), "--odoo", "--watch", "5"])


def test_watch_repeats_survives_a_failed_cycle_and_stops_on_ctrl_c(
    env: tuple[Path, FakeOdoo], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rules, fake = env
    cycles = {"n": 0}
    good = cli.fetch

    def flaky(credentials: imap.Credentials, config: object) -> list[tuple[object, EmailMessage]]:
        cycles["n"] += 1
        if cycles["n"] == 1:
            raise RuntimeError("Gmail said no")
        return good(credentials, config)  # type: ignore[arg-type,return-value]

    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "fetch", flaky)
    monkeypatch.setattr(cli, "sleep", sleep)

    assert cli.main([str(rules), "--odoo", "--execute", "--watch", "5"]) == 0

    assert waits == [300, 300, 300]
    assert "Gmail said no" in capsys.readouterr().out
    assert len(fake.tables["account.move"]) == 1


def test_a_second_run_at_the_same_time_is_refused(env: tuple[Path, FakeOdoo]) -> None:
    rules, fake = env
    (rules.parent / ".mailbox-to-odoo.lock").write_text("running", encoding="utf-8")

    assert cli.main([str(rules), "--odoo", "--execute"]) == 2
    assert fake.writes() == []
    assert (rules.parent / ".mailbox-to-odoo.lock").exists()  # not ours: left alone


def test_items_without_a_message_id_still_get_a_marker() -> None:
    msg = mail()
    del msg["Message-ID"]
    rule = odoo.Rule(name="Acme", folder="Acme")

    (item,) = odoo.items([(rule, msg)])

    assert item.message_id.startswith("no-id:2026-09-01")
