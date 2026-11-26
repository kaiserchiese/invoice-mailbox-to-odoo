"""Draft vendor bills in Odoo: one per PDF, through Odoo's own "upload a document to a journal" call.

`plan` only reads from Odoo. `execute` writes. See docs/PLAN-ODOO.md for why each check exists.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from email.message import Message
from typing import Any, Protocol

from . import message
from .odoo_client import OdooError
from .rules import Rule


class Client(Protocol):
    def execute(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any: ...


@dataclass(frozen=True)
class Item:
    rule: Rule
    name: str
    content: bytes = field(repr=False)
    message_id: str
    day: date

    @property
    def marker(self) -> str:
        return f"mailbox-to-odoo:{self.message_id}:{hashlib.sha256(self.content).hexdigest()}"


@dataclass(frozen=True)
class Planned:
    item: Item
    partner_id: int | None
    orphans: tuple[int, ...] = ()  # attachments a dead run left with this marker and no bill


@dataclass
class Plan:
    new: list[Planned] = field(default_factory=list)
    already: list[tuple[Item, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Result:
    created: list[tuple[str, int]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def items(mails: Iterable[tuple[Rule, Message]]) -> list[Item]:
    """The PDFs to send, filtered by each rule's `attachment` regex exactly like the folder step."""
    found = []
    for rule, msg in mails:
        day = message.day(msg)
        message_id = str(msg["Message-ID"] or "").strip() or f"no-id:{day.isoformat()}"
        for name, content in message.pdfs(msg):
            if re.search(rule.attachment, name, re.IGNORECASE):
                found.append(Item(rule, message.filename(name, day), content, message_id, day))
    return found


def journal_id(client: Client, code: str) -> int | None:
    """The purchase journal with this code ('' = let Odoo pick the first purchase journal)."""
    if not code:
        return None
    found = client.execute("account.journal", "search", [[["code", "=", code], ["type", "=", "purchase"]]])
    if len(found) != 1:
        raise ValueError(f"ODOO_JOURNAL {code!r}: {len(found)} purchase journals with that code")
    return int(found[0])


def _partner_id(client: Client, rule: Rule) -> int | None:
    """The rule's vendor: exactly one match or an error. Never guessed."""
    if not rule.partner:
        return None
    by_vat = rule.partner.startswith("vat:")
    field_name, value = ("vat", rule.partner[4:]) if by_vat else ("name", rule.partner)
    domain: list[Any] = [[field_name, "=", value]]
    if by_vat:
        domain.append(["parent_id", "=", False])  # Odoo copies a company's vat onto its contacts
    found = client.execute("res.partner", "search", [domain])
    if len(found) != 1:
        count = "no vendor" if not found else f"{len(found)} vendors"
        raise ValueError(f"rule {rule.name!r}: {count} with {field_name} {value!r} in Odoo; nothing sent for it")
    return int(found[0])


def _bills(client: Client, domain: list[Any]) -> list[dict[str, Any]]:
    """Attachments of bills matching `domain`, with the res_id of their bill."""
    ids = client.execute("ir.attachment", "search", [[["res_model", "=", "account.move"], *domain]])
    return client.execute("ir.attachment", "read", [ids, ["res_id"]]) if ids else []


def _known(client: Client, item: Item, partner_id: int | None) -> tuple[str, tuple[int, ...]]:
    """Why Odoo already has this PDF ('' = it does not), and any dead-run leftovers to replace."""
    marked = client.execute("ir.attachment", "search", [[["description", "=", item.marker]]])
    rows = client.execute("ir.attachment", "read", [marked, ["res_model"]]) if marked else []
    if any(r["res_model"] == "account.move" for r in rows):
        return "mail already in Odoo", ()
    orphans = tuple(r["id"] for r in rows)
    if _bills(client, [["checksum", "=", hashlib.sha1(item.content).hexdigest()]]):  # noqa: S324 - Odoo's own checksum
        return "same PDF already on a bill", orphans
    if partner_id:
        for row in _bills(client, [["name", "=", item.name]]):
            (move,) = client.execute("account.move", "read", [[row["res_id"]], ["partner_id"]])
            owner = move["partner_id"]
            if (owner[0] if isinstance(owner, list) else owner) == partner_id:
                return "same file name already on a bill of this supplier", orphans
    return "", orphans


def plan(client: Client, items: list[Item]) -> Plan:
    result = Plan()
    partners: dict[Rule, int | None] = {}  # keyed by the rule itself: two rules may share a name
    failed: set[Rule] = set()
    seen: set[tuple[Rule, str]] = set()
    sent: set[bytes] = set()  # Odoo knows nothing of this run's PDFs until they are created
    for item in items:
        rule = item.rule
        if rule in failed:
            continue
        try:
            if rule not in partners:
                partners[rule] = _partner_id(client, rule)
        except ValueError as error:
            failed.add(rule)
            result.errors.append(str(error))
            continue
        if (rule, item.name.lower()) in seen:
            result.already.append((item, "same file name earlier in this run"))
            continue
        if item.content in sent:
            result.already.append((item, "same PDF earlier in this run"))
            continue
        why, orphans = _known(client, item, partners[rule])
        if not why:
            seen.add((rule, item.name.lower()))
            sent.add(item.content)
        if why:
            result.already.append((item, why))
        else:
            result.new.append(Planned(item, partners[rule], orphans))
    return result


def _convert(client: Client, attachment: int, journal: int | None, context: dict[str, Any]) -> int:
    """Turn an uploaded PDF into a bill and return the bill id. On failure, leave no stray upload."""
    try:
        action = client.execute(
            "account.journal", "create_document_from_attachment",
            [[journal] if journal else [], [attachment]], {"context": context},
        )
        return int(action["res_id"])
    except OdooError:
        row = client.execute("ir.attachment", "read", [[attachment], ["res_id"]])
        if row and row[0]["res_id"]:  # a timeout can hide a commit: the bill exists, keep it
            return int(row[0]["res_id"])
        client.execute("ir.attachment", "unlink", [[attachment]])
        raise


def execute(client: Client, to_create: Plan, journal: int | None = None) -> Result:
    result = Result()
    context = {"default_move_type": "in_invoice", **({"default_journal_id": journal} if journal else {})}
    for planned in to_create.new:
        item = planned.item
        bill: int | None = None
        try:
            if planned.orphans:
                client.execute("ir.attachment", "unlink", [list(planned.orphans)])
            attachment = client.execute("ir.attachment", "create", [{
                "name": item.name, "datas": base64.b64encode(item.content).decode("ascii"),
                "mimetype": "application/pdf", "description": item.marker,
            }])
            bill = _convert(client, attachment, journal, context)
            result.created.append((item.name, bill))
            (state,) = client.execute("account.move", "read", [[bill], ["state", "partner_id"]])
            if state["state"] != "draft":
                result.errors.append(
                    f"{item.name}: bill {bill} is {state['state']}, not draft (auto-post?); supplier left untouched"
                )
            elif planned.partner_id:
                owner = state.get("partner_id")
                if owner and (owner[0] if isinstance(owner, list) else owner) != planned.partner_id:
                    result.errors.append(
                        f"{item.name}: Odoo had set another supplier on bill {bill}; the rule's supplier replaced it"
                    )
                client.execute("account.move", "write", [[bill], {"partner_id": planned.partner_id}])
        except OdooError as error:
            where = "supplier not set on the bill" if bill else "failed"
            result.errors.append(f"{item.name}: {where}: {error}")
    return result
