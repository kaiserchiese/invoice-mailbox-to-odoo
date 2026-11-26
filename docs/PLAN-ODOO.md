# Plan: vendor bills in Odoo

Status: plan, before code. Replaces the "design only" parts of [ROADMAP.md](ROADMAP.md).

## Goal

For each invoice PDF the mailbox rules find, create one draft vendor bill in Odoo with the PDF attached, and let Odoo's own digitization (OCR) run when the instance has it. Community has no OCR: the draft and the PDF are all you get there.

## What Odoo's source says (read on 2026-11-24, not from memory)

- `account.journal.create_document_from_attachment(attachment_ids)` exists in `addons/account/models/account_journal.py` on branches 17.0 (line 935) and 18.0 (line 983). It is in the open `account` module, so Community has it. It has no leading underscore, so it is callable over RPC.
- It reads `default_move_type` from the context, creates an empty `account.move` in the journal, calls `invoice._extend_with_attachments(attachment, new=True)`, posts the attachment in the chatter and sets `res_model`/`res_id` on the attachment. Its own comment says each attachment is created "with a tentative to enhance with EDI / OCR".
- `_extend_with_attachments` (`account_move.py`, 18.0 line 4386) documents three callers: chatter drop, journal dashboard upload, and the journal's mail alias. We use the same entry as the dashboard upload, so whatever hooks Enterprise adds there fire for us too.
- Community's `_extend_with_attachments` decodes structured e-invoice formats (XML inside the PDF, Factur-X and similar). It does not read a plain PDF.
- 18.0 only: after creating the bill it calls `_autopost_bill()`, which posts it when the company and the partner both have auto-post on and a partner is already set. Odoo's own e-invoice importer (`account_edi_ubl_cii`, Community, auto-installed) can set the partner from XML embedded in the PDF before that call, and creates the partner if none matches. So **this tool never posts, but Odoo's auto-post can**. The tool reads `state` after the call and reports anything other than `draft`; it does not write the partner onto a bill that is not a draft.
- That same importer may also fill lines and amounts when the PDF carries structured XML (Factur-X and similar). A plain PDF gets none.
- OCR lives in Enterprise (`account_invoice_extract`). `github.com/odoo/enterprise` is private (HTTP 404), so the trigger **cannot be read or tested here**. Claim made in the README: "the same entry as the dashboard upload", nothing about OCR results. OCR is marked not tested.

## Seams under test

| Seam | Interface | Catches | Misses |
|---|---|---|---|
| Odoo client | `OdooClient(call)`: `authenticate`, `execute_kw` over JSON-RPC | Wrong request shape, auth failure, RPC error text surfaced | Real server behaviour (covered by the Docker run) |
| Push | `odoo.plan(client, items)` then `odoo.execute(client, plan)` against an in-memory fake Odoo | Idempotency, dry-run writes nothing, partner resolution, draft state, orphan clean-up | Odoo business rules |
| CLI | `main([...])` with the fake client injected | `--execute` gating, flags, exit codes, watch loop | Terminal rendering |
| Rules | `rules.load` | `partner` field parsing | |
| Real Odoo | Docker Community 18 (and 17 if RAM fits) | Everything the fake lies about | Enterprise OCR |

The fake is a loopback object, not a mock of internals: it answers `search_read`, `create`, `write`, `create_document_from_attachment` like Odoo does.

## Design

- **New files:** `odoo_client.py` (transport, about 60 lines), `odoo.py` (plan and execute, about 150 lines). `__main__.py` gains flags. No new dependency: JSON-RPC at `/jsonrpc` with `urllib`. Odoo 19 announces the external JSON-2 API in place of XML-RPC/JSON-RPC; supporting it is out of scope and stated in the README.
- **CLI:** `mailbox-to-odoo RULES [ROOT] --odoo [--execute] [--watch MINUTES]`. `ROOT` becomes optional: given, the folder step runs as today; with `--odoo`, the Odoo step runs on the same mails. Dry run by default, `--execute` for both. `--watch N` loops every N minutes and requires `--execute`; an error in one cycle is printed and the loop goes on.
- **Config by environment:** `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_API_KEY` (an API key, or the password on a local demo database). Optional `ODOO_JOURNAL` (purchase journal code). Without it Odoo picks the first purchase journal of the user's company.
- **Supplier by rule:** a rule gets optional `partner`: the exact Odoo name, or `vat:XX123` to match the VAT. One match: use it. Zero or several: the rule is reported as an error and none of its PDFs is sent. No `partner` on the rule: the draft is created without supplier (Enterprise OCR may fill it; otherwise a human does). The supplier is never guessed from the sender.
- **Flow per new PDF:**
  1. Skip if already in Odoo (see idempotency).
  2. `ir.attachment.create` with `name`, `datas` (base64), `mimetype`, `description` = marker.
  3. `account.journal.create_document_from_attachment`. It is a recordset method: `args = [[journal_id], [attachment_id]]`, or `[[], [attachment_id]]` with no journal (a bare `[[attachment_id]]` would pass the attachment id as a journal id). Context `default_move_type=in_invoice`, plus `default_journal_id` when a journal is set. The result is an action dict: `res_id` is the bill when one attachment is sent. One attachment per call, so the bill id is always known.
  4. Read the bill's `state`. If it is `draft` and the rule has a partner: `account.move.write({"partner_id": ...})`. If it is not `draft`, report an error and write nothing. If the partner Odoo already set differs from the rule's, the rule wins only on a draft, and the run says so.
  5. Failure handling: if step 3 fails, re-read the attachment; delete it only if `res_id` is still empty (a timeout can hide a commit on the server). If step 4 fails, keep the bill and report it: deleting would leave an empty bill and the retry would make another.
- **Idempotency** (the same mail never makes two bills):
  - Marker `mailbox-to-odoo:<Message-ID>:<sha256 of PDF>` goes in the attachment `description`. Before sending, search `ir.attachment` with `res_model = account.move` and that exact marker.
  - Second check: an attachment on any `account.move` with the same `checksum` (Odoo stores the SHA-1 itself). This also catches a PDF a person uploaded by hand. Known limit: the same bytes under another supplier count as the same invoice.
  - Same file name twice in one run: the first goes, the second counts as already there, as the folder step does.
  - Nothing is written into `ref`: that is the supplier's invoice number and feeds Odoo's own duplicate warning.
  - A mail with no `Message-ID` header uses `no-id:<mail date>` in the marker; the checksum check still applies.
  - An attachment with the marker but `res_model` empty (the process died between steps 2 and 3) is found by a second search, reused if the marker matches and deleted otherwise.
  - Same file name from a later mail with different bytes (re-rendered PDF, the Stripe case): a third check, an `account.move` attachment with the same `name` and the same partner when the rule has one. Without a partner on the rule it is a known limit.
  - Not atomic: search then create has no unique key in Odoo. A lock file next to the rules file stops two local runs at once (`--watch` plus a manual run). Two machines at once are unsupported, and the README says so. "Never creates two bills" is worded as "skips what it can see in Odoo".
  - A draft deleted by hand takes its attachment with it, so the next run recreates it; a cancelled bill keeps blocking by checksum. Documented as "cancel, do not delete". The delete half was tried on the real run (docs/PRUEBA-ODOO.md); the cancel half follows from Odoo keeping the attachment and was not run.
- **Dry run:** connects, authenticates, resolves partners and runs the idempotency searches (reads only), prints what it would create, writes nothing.
- **Errors:** RPC faults print Odoo's own message, with no key in it. An authentication failure stops the run before any write.

## Order of work (TDD, one slice at a time)

1. `rules`: `partner` field.
2. `odoo_client`: authenticate and execute_kw on a loopback HTTP server, plus a fake `call`.
3. `odoo.plan` against the fake: new, already-in-Odoo by marker, by checksum, in-run duplicate, partner none/one/many.
4. `odoo.execute`: creates attachment, bill, partner write; dry run writes nothing; cleans the orphan on failure.
5. CLI wiring, `--watch`.
6. Real run against Community 18 in Docker (compose file in `examples/odoo/`, `docker compose down -v` after). Log in `docs/PRUEBA-ODOO.md`.
7. README, alternatives table, launch drafts.

## Out of scope

Posting bills, writing lines and amounts ourselves (Odoo's importer may fill them from structured XML), payments. A `vat:` rule is checked on the real run: contacts that share the VAT of their parent would give "several matches", and `parent_id = False` may be needed. Enterprise OCR results (not testable here). Odoo 19 JSON-2. Multi-company (`company_id` on the rule) is listed as a limit.

## Open risks

- `description` on `ir.attachment` is assumed free text and writable by an ordinary user; check against the real instance.
- The `checksum` search needs the field to be searchable (it is stored in 17 and 18; check on the real run).
- If Enterprise OCR rewrites the partner after our write, our rule would lose. Not testable here; stated in the README.
