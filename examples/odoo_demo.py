"""A few minutes with a local Odoo: made-up mail in, draft vendor bills out. No mailbox, no real data.

    docker compose -f examples/odoo/compose.yaml up -d      # wait until http://127.0.0.1:18069 answers
    python examples/odoo_demo.py                            # dry run
    python examples/odoo_demo.py --execute                  # creates the drafts
    docker compose -f examples/odoo/compose.yaml down -v    # clean up

The defaults below are the login of that throwaway container, nothing else.
"""

from __future__ import annotations

import os
import sys
from email.message import EmailMessage
from pathlib import Path

from mailbox_to_odoo import __main__ as cli
from mailbox_to_odoo import imap

os.environ.setdefault("ODOO_URL", "http://127.0.0.1:18069")
os.environ.setdefault("ODOO_DB", "demo")
os.environ.setdefault("ODOO_USER", "admin")
os.environ.setdefault("ODOO_API_KEY", "admin")


def pdf(number: str, total: str) -> bytes:
    """A small valid one-page PDF that shows the invoice number and total."""
    text = f"BT /F1 18 Tf 72 720 Td (Invoice {number}) Tj 0 -28 Td (Total due: {total} EUR) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number_, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number_} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def mail(message_id: str, subject: str, name: str, content: bytes) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["Message-ID"] = subject, message_id
    msg["Date"] = "Tue, 03 Nov 2026 10:00:00 +0000"
    msg.set_content("Please find the invoice attached.")
    msg.add_attachment(content, maintype="application", subtype="pdf", filename=name)
    return msg


def main() -> int:
    rules_file = Path(__file__).with_name("odoo") / "rules.yaml"
    config = cli.rules.load(rules_file)
    azure, unknown = config.rules
    inbox = [
        (azure, mail("<a1@azure.test>", "Invoice AZ-2026-001", "AZ-2026-001.pdf", pdf("AZ-2026-001", "1,210.00"))),
        (azure, mail("<a2@azure.test>", "Invoice AZ-2026-002", "AZ-2026-002.pdf", pdf("AZ-2026-002", "380.50"))),
        (unknown, mail("<u1@unknown.test>", "Your invoice", "UN-77.pdf", pdf("UN-77", "99.00"))),
    ]
    cli.fetch = lambda _credentials, _config: inbox  # type: ignore[assignment]
    imap.Credentials.from_env = classmethod(lambda cls: imap.Credentials("demo@example.test", "x"))  # type: ignore[method-assign]
    return cli.main([str(rules_file), "--odoo", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
