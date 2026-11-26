"""Dry run against made-up mail: no network, no credentials. Used for the README capture."""

from __future__ import annotations

import tempfile
from email.message import EmailMessage
from pathlib import Path

from mailbox_to_odoo import __main__ as cli
from mailbox_to_odoo import imap, rules


def _mail(subject: str, day: str, *pdfs: tuple[str, bytes]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["Date"] = subject, day
    msg.set_content("attached")
    for name, content in pdfs:
        msg.add_attachment(content, maintype="application", subtype="pdf", filename=name)
    return msg


def main() -> None:
    root = Path(tempfile.mkdtemp()) / "Invoices"
    (root / "Acme Hosting").mkdir(parents=True)
    (root / "Acme Hosting" / "INV-1001.pdf").write_bytes(b"%PDF-already-filed")
    config = rules.load(Path(__file__).with_name("rules.example.yaml"))
    acme, globex, _portal = config.rules
    inbox = [
        (acme, _mail("Invoice 1001", "Tue, 01 Sep 2026 10:00:00 +0000", ("INV-1001.pdf", b"%PDF-already-filed"))),
        (acme, _mail("Invoice 1002", "Thu, 01 Oct 2026 10:00:00 +0000", ("INV-1002.pdf", b"%PDF-oct"))),
        (acme, _mail("Terms update", "Fri, 02 Oct 2026 10:00:00 +0000", ("terms.pdf", b"%PDF-terms"))),
        (globex, _mail("Your bill", "Thu, 01 Oct 2026 08:00:00 +0000", ("bill.pdf", b"%PDF-bill"))),
        (globex, _mail("Your bill is ready", "Sun, 01 Nov 2026 08:00:00 +0000")),
    ]
    cli.fetch = lambda _c, _cfg: inbox  # type: ignore[assignment]
    imap.Credentials.from_env = classmethod(lambda cls: imap.Credentials("accounts@example.test", "x"))  # type: ignore[method-assign]
    cli.main([str(Path(__file__).with_name("rules.example.yaml")), str(root)])


if __name__ == "__main__":
    main()
