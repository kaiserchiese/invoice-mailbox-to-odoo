> Superseded by [PLAN-ODOO.md](PLAN-ODOO.md): the Odoo step is built.

# Roadmap: a generic step into Odoo

Status: design only. Nothing here is implemented, and it has not been tried against a live Odoo instance. Check endpoint and field names against the Odoo version you target before building it.

## Goal

Take the folder that `mailbox-to-odoo` fills and turn each new PDF into a draft vendor bill in Odoo with the PDF attached. A human opens the draft, checks it and posts it.

## Shape

A second command, `mailbox-to-odoo push`, with the same dry-run default:

```
mailbox-to-odoo push rules.yaml ROOT [--execute]
```

It reads the same rules file. Each rule gains an optional `partner` (the exact Odoo vendor name or its id). The folder name is not used to guess the vendor.

## Odoo side

- Transport: JSON-RPC at `/jsonrpc` (stdlib `urllib`, no new dependency). XML-RPC at `/xmlrpc/2/` is the fallback for older versions; the calls are the same two (`authenticate`, `execute_kw`).
- Credentials by environment: `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY`. Odoo API keys are used in place of a password.
- Bill: `account.move.create` with `move_type = "in_invoice"`, `partner_id` from the rule, `state` left as `draft`, `invoice_date` from the mail date, `ref` from the file name.
- Attachment: `ir.attachment.create` with `res_model = "account.move"`, `res_id` of the new bill, `datas` as base64, `mimetype = "application/pdf"`.
- No lines, no amounts, no taxes. Those depend on the company's chart of accounts and stay with the human, or with a later OCR step.

## Idempotency

The tool must not create a bill twice on a rerun.

1. Before creating, search `account.move` for `move_type = "in_invoice"`, the same `partner_id` and the same `ref`. A hit means skip.
2. Also store the SHA-256 of the PDF in the bill's `narration`, and skip when another bill of that partner holds it. Same-name-different-bytes follows the folder rule: same name is the same invoice.
3. Keep a small `.pushed.json` per supplier folder (file name to bill id) so a rerun does not need Odoo to answer first.

## Open questions

- Field names and the external API can differ between Odoo versions. Pick one tested range and document it.
- Multi-company databases need a `company_id` on the rule.
- Whether to let Odoo's own OCR (if the instance has it) fill the lines after the draft exists.

## Order of work

1. `push` in dry run: list the bills it would create, no network write.
2. Create the draft and the attachment against a local Odoo in Docker, with a test that checks both records exist.
3. Idempotency checks and the `.pushed.json` file.
4. Docs and a demo capture.

## Out of scope

Posting bills, payments, reconciliation, and any connector to another system (Stripe, CRM, banks). Those belong to separate packages.
