# Alternatives to mailbox-to-odoo

Read on 2026-11-24 from primary sources: Odoo and OCA source code on GitHub, the Odoo documentation sources (`odoo/documentation`), apps.odoo.com pages and vendor pricing pages. Each claim links to the page it comes from. Anything not checked against a source is marked **not verified**.

What is compared. mailbox-to-odoo reads a Gmail mailbox over IMAP without changing it, picks invoice PDFs with one rule per supplier (a Gmail query plus an optional file-name regex), and files them in one folder per supplier. On this branch it also has an Odoo step (`--odoo`, code in `src/mailbox_to_odoo/odoo.py` and `odoo_client.py`, design in [PLAN-ODOO.md](PLAN-ODOO.md)): over the external API (`/jsonrpc`) it creates one draft vendor bill per PDF through `account.journal.create_document_from_attachment`, with the PDF attached and the vendor taken from the rule (never guessed). It plans first and writes only with `--execute`, and it skips PDFs Odoo already has. Odoo's own digitization runs where the instance has it.

## Summary

| Option | Cost | Community | OCR | Reads an existing mailbox | Main difference from mailbox-to-odoo |
|---|---|---|---|---|---|
| Odoo journal email alias | Free (part of `account`) | Yes | Enterprise only, IAP credits | Through an Incoming Mail Server: unread INBOX mail only, marked as read | Vendor from the sender address, no per-supplier filter, no dry run; mail must reach the alias |
| OCA `account_invoice_import` (+ `_simple_pdf`) | Free, AGPL-3 | Yes | No OCR service; reads XML e-invoices and the text layer of PDFs with per-vendor rules | Same Odoo Incoming Mail Server | Extracts amounts; needs modules on the Odoo server (not possible on Odoo Online) |
| OCA `fetchmail_attach_from_folder` | Free, AGPL-3 | Yes | No | Yes, chosen IMAP folders | Attaches mails to records; not built for vendor bills |
| apps.odoo.com OCR apps | Free to about 1,250 EUR | Most say yes | Yes (own AI key or a service) | Through Odoo's mail alias where they support email | OCR first; mail intake is Odoo's alias |
| Dext, Hubdoc, Veryfi, Mindee, Rossum | Paid (see section 4) | n/a | Yes | Forward-to-address or API | No first-party Odoo integration found on their pages |
| GitHub scripts and add-ons | Free | n/a | Most use an LLM | One script has an IMAP poller; one add-on claims email intake | Demo code, or OCR inside Odoo |

## 1. Odoo's journal email alias

**What it does.** A purchase journal can have an email alias. Odoo's documentation says "Each PDF attached to the email is automatically converted into a new draft vendor bill" and "Only PDF and XML formats are processed via an email alias associated with a journal" ([invoice digitization, 18.0](https://www.odoo.com/documentation/18.0/applications/finance/accounting/vendor_bills/invoice_digitization.html)). The default alias is `vendor-bills@` plus the alias domain, set in the journal's Advanced Settings tab (same page).

The code is `AccountMove.message_new` in the open `account` module ([18.0 source](https://github.com/odoo/odoo/blob/18.0/addons/account/models/account_move.py), present in 16.0, 17.0, 18.0 and 19.0). Read in 18.0 and 19.0:

- The vendor is looked up from the sender's address. When the sender is an internal user (a manual forward), Odoo searches the mail body for other partner addresses. The address is stored in `invoice_source_email`.
- In 18.0 and 19.0, `_routing_check_route` refuses a mail with no attachment and sends a bounce to the sender.
- 18.0 detaches from the bill the attachments no invoice was built from, keeping them on the message (the code comment mentions marketing images); 19.0 groups the attachments and creates one bill per group (`_message_post_after_hook`).

**Edition.** The alias and `message_new` live in `addons/account` of `odoo/odoo`, which is Community. OCR does not: `account_invoice_extract` is absent from `odoo/odoo` 18.0, and Odoo's [editions page](https://www.odoo.com/page/editions) marks "Comprehensive Accounting ... Vendor Bill OCR" as Enterprise only and the Invoicing "AI" row as Enterprise only. Digitization is an IAP service: "Digitizing one document uses one credit" ([invoice digitization](https://www.odoo.com/documentation/18.0/applications/finance/accounting/vendor_bills/invoice_digitization.html)). In Community the alias gives a draft with the PDF attached.

**Requirements.** An alias domain. On Odoo Online and Odoo.sh the alias domain and addresses are preconfigured: "The database domain is ready to be used to receive emails without any additional configuration" ([inbound messages](https://www.odoo.com/documentation/18.0/applications/general/email_communication/email_servers_inbound.html)). With a custom domain, mail must reach Odoo by redirection, by an Incoming Mail Server, or by DNS; on-premise, redirection and DNS also need the mail gateway script (same page).

**Reading an existing mailbox.** Odoo can fetch a mailbox itself through an Incoming Mail Server (`fetchmail.server`, [addons/mail/models/fetchmail.py, 18.0](https://github.com/odoo/odoo/blob/18.0/addons/mail/models/fetchmail.py), in `mail` from 16.0 to 19.0). The docs list as a benefit that it "allows to keep a copy of the email in your mailbox (with IMAP)" ([inbound messages](https://www.odoo.com/documentation/18.0/applications/general/email_communication/email_servers_inbound.html)). The 18.0 code in `fetch_mail`:

- selects the default folder (INBOX), searches `(UNSEEN)` and sets `\Seen` on each message it processes;
- POP deletes each processed message;
- the `google_gmail` module (Community, auto-installed, read on 18.0) adds Gmail OAuth for incoming servers.

So Odoo's fetch is not read-only, ignores mail someone already opened, does not look at archived mail, and has no per-supplier filter. The docs also say the feature "is designed for shared inboxes" and describe one incoming server for each mailbox and alias (same page). Whether fetching a mailbox whose address is not the alias (a company's general inbox) creates vendor bills is **not verified**.

**Forwarding instead of fetching.** Odoo's docs note: "With forwarding, the address forwarding the email will be identified as the sender, while with redirections, the original sender will always remain", and that providers which validate a redirection by sending a link to the target address cause trouble (same page). Since the vendor-bill alias bounces mail without an attachment (code above), such a validation mail would not create a record there. That last point is an inference from the code; it was not tested.

**Real difference from mailbox-to-odoo.**

- The alias needs mail to arrive at the alias: by redirect, by forward, or by an incoming server on the alias mailbox. mailbox-to-odoo reads the mailbox where the mail already is, including read and archived mail and past months (`since` in the rules file), and changes nothing in it.
- The alias takes every PDF of every mail it receives. mailbox-to-odoo applies a Gmail query and a file-name regex per supplier, so a terms PDF or a contract is not turned into a bill.
- The alias guesses the vendor from the sender. mailbox-to-odoo takes it from the rule and refuses to guess.
- mailbox-to-odoo runs dry by default and, before creating a bill, checks a marker built from the mail's Message-ID and the PDF's SHA-256, Odoo's attachment checksum, and the file name on the same vendor's bills (`_known` in `odoo.py`). The alias has no dry run. Its only dedupe is the mail gateway's handling of a repeated Message-ID, which was **not verified** in source.
- The alias needs no external API access. mailbox-to-odoo does (see "Where this tool cannot compete").

### The README row about the alias

The row in the README's Alternatives table reads:

> Odoo's own vendor-bill email alias | Odoo creates a draft bill from a mail sent to an alias address | Books straight into Odoo, no extra tool. Better if you can route supplier mail to the alias. | Works when supplier mail stays in your mailbox, keeps an auditable folder per supplier, and needs no change in Odoo.

- "Odoo creates a draft bill from a mail sent to an alias address": correct. More exact: one draft per PDF attachment.
- "Books straight into Odoo": loose. It creates drafts; Odoo's docs tie automatic posting to digitization ([invoice digitization](https://www.odoo.com/documentation/18.0/applications/finance/accounting/vendor_bills/invoice_digitization.html), "Automatic vendor bill posting").
- "Works when supplier mail stays in your mailbox": misleading. Odoo can also fetch a mailbox over IMAP and keep the mail there. What holds is narrower: Odoo's fetch takes only unread INBOX mail and marks it read, and the docs set it up per alias mailbox.
- "keeps an auditable folder per supplier": correct for the folder step.
- "needs no change in Odoo": true for the folder step only. The Odoo step (`--odoo`) needs an API user and key, and on Odoo Online a Custom plan.

Keep the row, reworded. Suggested text:

> Odoo's own vendor-bill email alias (Community) | Odoo creates one draft bill per PDF in a mail sent to the journal's alias | Built in and free, no external API access needed. Better if supplier mail can be redirected to the alias. | Reads mail where it already is, including read and archived mail, without marking it; picks PDFs per supplier rule instead of taking every attachment; vendor comes from the rule, not the sender address.

## 2. OCA modules

**`account_invoice_import`** ([OCA/edi, 18.0](https://github.com/OCA/edi/tree/18.0/account_invoice_import); AGPL-3; found on branches 16.0, 18.0 and 19.0). It imports supplier invoices from UBL XML, CII XML and Factur-X; "if there is already a draft supplier invoice for this supplier with the same invoice number, Odoo will display a warning"; otherwise it creates a draft and attaches the file ([README](https://github.com/OCA/edi/blob/18.0/account_invoice_import/README.rst)). It has a mail gateway: an Incoming Mail Server with "Create a new record" set to the wizard `account.invoice.import` (same README). Its `message_new` ([wizard source, 18.0](https://github.com/OCA/edi/blob/18.0/account_invoice_import/wizard/account_invoice_import.py)) keeps only PDF and XML attachments, parses each one, creates the bill, and logs an error when parsing fails. For a PDF with no embedded XML the base module falls back to an empty parse; the code comment says this is "designed to allow the import of an empty invoice with 1 invoice line at 0". Whether that produces a draft for a vendor that is not configured is **not verified**.

**`account_invoice_import_simple_pdf`** ([OCA/edi, 18.0](https://github.com/OCA/edi/tree/18.0/account_invoice_import_simple_pdf); AGPL-3). It reads the PDF's raw text, identifies the partner "using the VAT number ... or some keywords", and extracts total, untaxed and tax amounts, dates and the invoice number with rules configured per vendor in Odoo ([README](https://github.com/OCA/edi/blob/18.0/account_invoice_import_simple_pdf/README.rst)). It relies on a PDF-to-text tool (PyMuPDF, pdftotext or pypdf). It does no OCR; scanned PDFs without a text layer are outside its design (inference from the README, **not verified**).

**`fetchmail_attach_from_folder`** ([OCA/server-tools, 18.0](https://github.com/OCA/server-tools/tree/18.0/fetchmail_attach_from_folder); on 16.0, 17.0 and 18.0). It fetches mails from chosen IMAP folders and attaches them to records matched by email address, by domain, or by the "Odoo standard" method, which "calls the model's standard action on new incoming mail"; processed mails can be deleted or moved to an archive folder ([README](https://github.com/OCA/server-tools/blob/18.0/fetchmail_attach_from_folder/README.rst)). Whether "Odoo standard", pointed at Journal Entry, yields vendor bills is **not verified**: `account.move.message_new` reads `move_type` and `journal_id` from the alias defaults.

**Hosting limit.** None of these can run on Odoo Online: "Odoo Online is incompatible with custom modules or modules from the Odoo Apps Store" ([Odoo Online docs](https://www.odoo.com/documentation/18.0/administration/odoo_online.html)).

**Real difference from mailbox-to-odoo.** The OCA pair goes further on content: it reads amounts and dates and creates bills with a line, for free, on Community. It also inherits Odoo's mail fetch: unread INBOX mail only, marked read, no per-supplier search. It runs inside Odoo, so it needs Odoo.sh or self-hosting. mailbox-to-odoo runs outside Odoo, reads no amounts, and leaves extraction to Odoo's OCR or to a person.

## 3. Apps on apps.odoo.com

Searched on 2026-11-24, series 18.0, for: vendor bill email, invoice email import, fetchmail invoice, vendor bill import, bill attachment email, invoice OCR, imap, gmail, email invoice, mail invoice, email bill, inbox, email attachment, mail attachment, invoice capture, bill capture, document capture, outlook invoice. No app was found whose main job is to read a mailbox and turn invoice mails into vendor bills. Email intake shows up as a feature of OCR apps, through Odoo's mail alias. Prices are as shown on the store cards, in EUR. Store apps cannot be installed on Odoo Online ([Odoo Online docs](https://www.odoo.com/documentation/18.0/administration/odoo_online.html)).

| App | Price | Edition | What it says about intake and OCR |
|---|---|---|---|
| [EasyOCR Invoice Capture](https://apps.odoo.com/apps/modules/18.0/easyocr) (EasySoft Tech) | Free, LGPL-3 | Community 16.0 to 20.0 | Reads text PDFs in the browser at no cost; scans need its service (free plan 10 pages/month). Intake is dropping files; email intake **not verified** |
| [BillPulse](https://apps.odoo.com/apps/modules/18.0/puzari_bill_capture) (PuzariCloud) | 62.43 EUR, OPL-1 | Community and Enterprise, 16.0 to 20.0 | "one e-mail address per company or journal"; own AI key; "Odoo Online: not possible" |
| [EU OCR Bill Capture](https://apps.odoo.com/apps/modules/18.0/eu_ocr_bill_capture_fr_be_nl) (Pokutsoft) | 63.59 EUR, OPL-1 | Community and Enterprise | "Captures come from the mail alias", your OCR provider, or pasted text |
| [Vendor Bill OCR with AI](https://apps.odoo.com/apps/modules/18.0/vendor_bill_capture) (Abdishakur Ali) | 69.00 EUR, OPL-1 | Community and Enterprise, "not Odoo Online" | Drop a PDF on a draft bill; own AI key |
| [AI OCR Provider - Mindee](https://apps.odoo.com/apps/modules/18.0/az_invoice_provider_ai_ocr_mindee) | 75.00 EUR | not checked | Uses Mindee Invoice OCR v4 |
| [Odoo Rossum Integration](https://apps.odoo.com/apps/modules/18.0/rossum_integration) | 43.20 EUR | not checked | Imports Rossum results |
| [Accounting Invoice OCR](https://apps.odoo.com/apps/modules/18.0/account_invoice_ocr) (2BIT Digital) | 1,250.00 EUR | not checked | "Create vendor bills from OCR uploads" |

Mail-client apps (for example [MailDesk](https://apps.odoo.com/apps/modules/18.0/maildesk_mail_client), 389 EUR) sync whole mailboxes into Odoo; they do not create bills.

**Real difference from mailbox-to-odoo.** These apps solve extraction. None of the pages read offers per-supplier mailbox search. They also run inside Odoo, so they are unavailable on Odoo Online.

## 4. Paid services

| Service | Odoo on its own pages | Public price | Email intake |
|---|---|---|---|
| Dext | Odoo is not named on its [integrations page](https://dext.com/en/partner/product/integrate-with-accounting-software), which names Xero, QuickBooks and Sage among "36+ accounting software platforms". No Dext app found on apps.odoo.com | **not verified** (the pricing page returned 404) | **not verified** |
| Hubdoc | [Add-ons page](https://hubdoc.com/addons) lists Xero, QuickBooks Online, Bill.com and Box. No Odoo | "$12 USD per month" after a 30-day trial ([pricing](https://www.hubdoc.com/pricing)) | "Forward from email" (same page) |
| Veryfi | Odoo not mentioned on the [pricing page](https://www.veryfi.com/pricing/); no Veryfi app found on apps.odoo.com | Free: 100 documents/month. Starter: $500/month in credits; $0.08 per receipt, $0.16 per invoice | **not verified** |
| Mindee | Odoo not mentioned on the [pricing page](https://www.mindee.com/pricing); third-party apps exist on apps.odoo.com (section 3) | 14-day trial; Starter 44/month billed annually for 6,000 credits, 1 page = 1 credit. The currency is missing from the static page | **not verified** |
| Rossum | Odoo not named on the [pricing page](https://rossum.ai/pricing/); third-party apps exist on apps.odoo.com | Starter "starting at $18,000 per year" | "through email, API, or manual upload" |
| Odoo digitization | Built in (Enterprise) | IAP, one credit per document ([docs](https://www.odoo.com/documentation/18.0/applications/finance/accounting/vendor_bills/invoice_digitization.html)); credit price **not verified** | Through the journal alias |

**Real difference from mailbox-to-odoo.** These are OCR and capture services. To reach Odoo they need a connector, and the pages read show no first-party Odoo connector. mailbox-to-odoo does no OCR and costs nothing to run.

## 5. Scripts and repos on GitHub

`gh search repos` returned no results for "odoo invoice imap", "odoo vendor bill email", "odoo bill email import", "odoo invoice email attachment", "odoo xmlrpc invoice pdf", "odoo invoice gmail", "odoo fetchmail invoice", "odoo email invoice ocr" or "odoo vendor bill import" (the search API also reported 0 for "odoo invoice imap"). Shorter phrases through the search API (`search/repositories`, sorted by stars), such as "odoo invoice ocr", "odoo vendor bill" and "odoo xmlrpc invoice", returned mostly OCR add-ons. The relevant ones:

| Repo | Stars, licence, last push | What it is |
|---|---|---|
| [karankeraliya/odoo-invoice-agent](https://github.com/karankeraliya/odoo-invoice-agent) | 0, none, 2026-06-26 | Gemini extraction, then XML-RPC `account.move`. Its README marks email monitoring as "Stubbed" (a folder) |
| [Baybordi/Huma-Invoicing-agent](https://github.com/Baybordi/Huma-Invoicing-agent) | 1, none, 2026-06-22 | A take-home exercise. Email monitoring "Built, not live in demo" (an IMAP poller); Claude extraction; XML-RPC; creates and confirms bills that pass its checks |
| [PaulArgoud/account-invoice-digitize-ai](https://github.com/PaulArgoud/account-invoice-digitize-ai) | 8, AGPL-3.0, 2026-06-11 | Odoo add-on, Odoo 16 to 19, Community and Enterprise. Replaces Odoo's OCR with an LLM (your provider key). Its README lists "Auto-create and extract vendor bills from incoming emails"; how mail reaches it (presumably Odoo's alias) is **not verified** |
| [EasySoft-Tech-SL/odoo-easyocr-module](https://github.com/EasySoft-Tech-SL/odoo-easyocr-module) | 0, LGPL-3.0, 2026-11-03 | Source of the EasyOCR app in section 3 |

Code search (`search/code`):

- `create_document_from_attachment xmlrpc`: 26 hits, all copies of the Enterprise Chilean localization file `l10n_cl_edi/models/fetchmail_server.py` in mirror repos. Not linked here.
- `create_document_from_attachment execute_kw`: 0 hits. No external script calling that method over RPC was found.
- `imaplib "account.move" xmlrpc`: 1 hit, in a hackathon repo (not read).

For reference, [invoice2data](https://github.com/invoice-x/invoice2data), already in the README, had 2,254 stars on the read date.

## Where this tool cannot compete

- **Odoo Online on a Standard plan.** "Access to data via the external API is only available on Custom Odoo pricing plans. Access to the external API is not available on One App Free or Standard plans" ([external API, 18.0](https://www.odoo.com/documentation/18.0/developer/reference/external_api.html)). There, mailbox-to-odoo can still fill the folder, but only the alias can create bills.
- **API lifetime.** "Both the XML-RPC and JSON-RPC APIs at endpoints `/xmlrpc`, `/xmlrpc/2` and `/jsonrpc` are scheduled for removal in Odoo 22 (fall 2028) / Odoo Online 21.1 (winter 2027)" ([external JSON-2 API, 19.0](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html)). The client in `odoo_client.py` uses `/jsonrpc`.
- **API keys on 19.0.** The same 19.0 page says "it is not possible to create keys that last for more than three months", so a scheduled run needs a new key at least that often.
- **Content.** It never reads the invoice. On Community, the OCA modules extract amounts and mailbox-to-odoo does not.

## Verdict

Something free and close already exists. Odoo's own journal alias, in Community at no cost, turns each PDF in a received mail into a draft vendor bill with the PDF attached, and Odoo can fetch the alias's mailbox over IMAP, Gmail OAuth included. Add OCA's `account_invoice_import` and `account_invoice_import_simple_pdf` (free, AGPL-3) and self-hosted Community also gets amounts and dates for text PDFs; the AGPL add-on `account-invoice-digitize-ai` claims LLM extraction for bills that arrive by email (not tested). For a company that can redirect supplier mail to an alias, or that runs on Odoo Online without a Custom plan, the alias is the better choice, and the README should say so.

mailbox-to-odoo differs in four narrow ways, mostly in how mail is selected:

1. It reads mail where it already sits, read or unread, archived or not, back to a chosen date, and changes nothing in the mailbox. Odoo's fetch takes only unread INBOX mail and marks it read.
2. It selects per supplier with a Gmail query and a file-name regex, so annexes are not turned into bills. The alias takes every PDF.
3. The vendor comes from a rule and is never guessed. The alias matches the sender address.
4. It has a dry run, runs outside Odoo (no module to install, so it works on Odoo Online with API access), and keeps a per-supplier folder as a record.

No tool found does this combination. Of the options whose code was read (Odoo's alias and fetch, OCA `account_invoice_import`), none selects mail per supplier or reads without side effects. OCA `fetchmail_attach_from_folder` watches chosen IMAP folders, and Gmail exposes labels as IMAP folders, so per-supplier selection may be possible there; its code was not read. The overlap with the alias is large; a fair one-line description of this tool is "the alias, for mail you cannot or will not redirect".

## Not verified

- How Odoo routes a mail fetched from a mailbox whose address is not an alias, and whether "Create a New Record = Journal Entry" yields a vendor bill (`message_route` not read).
- What Community's e-invoice decoders (Factur-X, UBL) fill in on a bill created by the alias.
- One draft per plain PDF on Community through the alias: stated in the docs; the `_extend_with_attachments` branch for plain PDFs was not read to the end.
- The Enterprise OCR trigger (`account_invoice_extract` is in the private `odoo/enterprise` repository).
- The mail gateway's dedupe on a repeated Message-ID.
- `google_gmail` OAuth fetch on versions other than 18.0.
- OCA/edi 17.0 having no invoice-import modules (the listing returned nothing, with errors suppressed).
- `account_invoice_import` creating a draft for a plain PDF from an unconfigured vendor.
- `account_invoice_import_simple_pdf` failing on scans without a text layer.
- `fetchmail_attach_from_folder` creating vendor bills in its "Odoo standard" mode, and whether it marks fetched mail as read.
- Whether Odoo is among Dext's "36+" platforms; Dext's price and email intake.
- Mindee's currency; Veryfi's email intake; the price of an Odoo IAP digitization credit.
- EasyOCR email intake; the editions of the Mindee, Rossum and 2BIT apps.
- How mail reaches `account-invoice-digitize-ai`, and whether its email intake works as described.
- The apps.odoo.com keyword searches covered series 18.0 only.
- The Symbifox `bf_email_management` module and the hackathon `cloud_agent.py` code-search hit were not read.
- How Gmail filter forwarding presents the original sender to Odoo.
