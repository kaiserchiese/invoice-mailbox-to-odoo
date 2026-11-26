"""What is taken out of one mail."""

from __future__ import annotations

from datetime import date
from email import message_from_bytes
from email.message import EmailMessage, Message

import pytest

from mailbox_to_odoo import message


def test_octet_stream_with_pdf_extension_counts_as_pdf() -> None:
    msg = EmailMessage()
    msg["Date"] = "Tue, 01 Sep 2026 10:00:00 +0000"
    msg.set_content("x")
    msg.add_attachment(b"%PDF-1", maintype="application", subtype="octet-stream", filename="INV-7.PDF")
    msg.add_attachment(b"GIF89a", maintype="image", subtype="gif", filename="logo.gif")

    assert message.pdfs(msg) == [("INV-7.PDF", b"%PDF-1")]


def test_filename_without_number_gets_mail_date() -> None:
    assert message.filename("invoice.pdf", date(2026, 9, 1)) == "2026-09-01 invoice.pdf"


def test_filename_with_number_is_kept_and_cleaned() -> None:
    assert message.filename('a/b:"7".PDF', date(2026, 9, 1)) == 'a_b__7_.PDF'
    assert message.filename("factura 12", date(2026, 9, 1)) == "factura 12.pdf"


def _parsed(headers: bytes) -> Message:
    return message_from_bytes(b"Date: Tue, 01 Sep 2026 10:00:00 +0000\r\n" + headers + b"\r\n\r\nx")


def test_encoded_attachment_name_and_subject_are_decoded() -> None:
    msg = _parsed(
        b"Subject: =?utf-8?q?Factura_a=C3=B1o?=\r\nContent-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="=?utf-8?q?fact=C3=BAra_1.pdf?="'
    )

    assert message.pdfs(msg)[0][0] == "factúra 1.pdf"
    assert message.subject(msg) == "Factura año"


def test_unquoted_attachment_name_with_spaces_keeps_its_number() -> None:
    msg = _parsed(b"Content-Type: application/pdf\r\nContent-Disposition: attachment; filename=Invoice 123.pdf")

    assert message.pdfs(msg)[0][0] == "Invoice 123.pdf"


@pytest.mark.parametrize("label", ["=?x-unknown?q?inv1.pdf?=", "=?utf-8?q?factura_caf=E9.pdf?="])
def test_a_badly_labelled_file_name_does_not_stop_the_run(label: str) -> None:
    msg = EmailMessage()
    msg.add_attachment(b"%PDF-1.4 x", maintype="application", subtype="pdf", filename="x.pdf")
    del msg.get_payload()[-1]["Content-Disposition"]
    msg.get_payload()[-1]["Content-Disposition"] = f'attachment; filename="{label}"'

    (found,) = message.pdfs(msg)

    assert found[1] == b"%PDF-1.4 x"
