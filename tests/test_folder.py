"""Which PDFs from the mailbox get written into which folder."""

from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from pathlib import Path

from mailbox_to_odoo import folder
from mailbox_to_odoo.rules import Rule

ACME = Rule("Acme Hosting", "Acme Hosting", "from:billing@acme.test")


def _mail(attachments: list[tuple[str, bytes]], day: str = "Tue, 01 Sep 2026 10:00:00 +0000") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Your Acme invoice"
    msg["Date"] = day
    msg.set_content("attached")
    for name, content in attachments:
        msg.add_attachment(content, maintype="application", subtype="pdf", filename=name)
    return msg


def test_writes_new_pdf_into_rule_folder(tmp_path: Path) -> None:
    plan = folder.plan(tmp_path, [(ACME, _mail([("100200300.pdf", b"%PDF-sept")]))])

    folder.write(plan)

    assert (tmp_path / "Acme Hosting" / "100200300.pdf").read_bytes() == b"%PDF-sept"


def test_same_content_under_other_name_is_not_written(tmp_path: Path) -> None:
    target = tmp_path / "Acme Hosting"
    target.mkdir()
    (target / "uploaded by hand.pdf").write_bytes(b"%PDF-sept")

    plan = folder.plan(tmp_path, [(ACME, _mail([("100200300.pdf", b"%PDF-sept")]))])

    assert plan.new == [] and plan.already_there == 1


def test_second_run_writes_nothing(tmp_path: Path) -> None:
    mails = [(ACME, _mail([("100200300.pdf", b"%PDF-sept")]))]
    folder.write(folder.plan(tmp_path, mails))

    assert folder.plan(tmp_path, mails).new == []


def test_same_name_in_subfolder_is_the_same_invoice_even_with_other_bytes(tmp_path: Path) -> None:
    target = tmp_path / "Acme Hosting" / "2026"
    target.mkdir(parents=True)
    (target / "Invoice-TEST0001-0002.pdf").write_bytes(b"%PDF-render-1")

    plan = folder.plan(tmp_path, [(ACME, _mail([("Invoice-TEST0001-0002.pdf", b"%PDF-render-2")]))])

    assert plan.new == [] and plan.already_there == 1


def test_same_name_twice_in_one_run_is_the_same_invoice(tmp_path: Path) -> None:
    plan = folder.plan(tmp_path, [
        (ACME, _mail([("invoice 1.pdf", b"%PDF-render-1")])),
        (ACME, _mail([("invoice 1.pdf", b"%PDF-render-2")])),
    ])

    assert [n.target.name for n in plan.new] == ["invoice 1.pdf"]
    assert plan.already_there == 1


def test_mail_without_pdf_is_reported_not_written(tmp_path: Path) -> None:
    plan = folder.plan(tmp_path, [(ACME, _mail([]))])

    assert plan.new == []
    assert plan.without_pdf[0].day == date(2026, 9, 1)
    assert plan.without_pdf[0].subject == "Your Acme invoice"


def test_attachment_filter_skips_annexes(tmp_path: Path) -> None:
    rule = Rule("Acme Legal", "Acme Legal", "from:x", attachment=r"^\d{4}-A-")
    msg = _mail([("Annex III signed.pdf", b"%PDF-annex"), ("2026-A-6-Example.pdf", b"%PDF-inv")])

    plan = folder.plan(tmp_path, [(rule, msg), (rule, _mail([("Annex.pdf", b"%PDF-a2")]))])

    assert [n.target.name for n in plan.new] == ["2026-A-6-Example.pdf"]
    assert plan.without_pdf == []
