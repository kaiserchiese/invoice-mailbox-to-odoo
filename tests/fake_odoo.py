"""An in-memory Odoo that answers the handful of calls the push step makes.

It follows what Odoo's source does (17.0/18.0 addons/account): `create_document_from_attachment`
is a recordset method, `checksum` is the SHA-1 Odoo computes itself, and the new bill is a draft.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from mailbox_to_odoo.odoo_client import OdooError


class FakeOdoo:
    def __init__(self) -> None:
        self.tables: dict[str, dict[int, dict[str, Any]]] = {
            "res.partner": {}, "ir.attachment": {}, "account.move": {}, "account.journal": {},
        }
        self.calls: list[tuple[str, str]] = []
        self.fail_on: dict[str, str] = {}  # "model.method" -> message, raised once
        self.state_of_new_bill = "draft"
        self.partner_on_new_bill: int | bool = False
        self._next = 100

    def add(self, model: str, **values: Any) -> int:
        self._next += 1
        self.tables[model][self._next] = {"id": self._next, **values}
        return self._next

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[1] in {"create", "write", "unlink", "create_document_from_attachment"}]

    @staticmethod
    def _match(row: dict[str, Any], domain: list[Any]) -> bool:
        return all(row.get(field, False) == value for field, _op, value in domain)

    def execute(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        self.calls.append((model, method))
        key = f"{model}.{method}"
        if key in self.fail_on:
            raise OdooError(self.fail_on.pop(key))
        rows = self.tables[model]
        if method == "search":
            return [i for i, r in rows.items() if self._match(r, args[0])]
        if method == "read":
            return [{"id": i, **{f: rows[i].get(f, False) for f in args[1]}} for i in args[0] if i in rows]
        if method == "unlink":
            for i in args[0]:
                rows.pop(i, None)
            return True
        if method == "write":
            for i in args[0]:
                rows[i].update(args[1])
            return True
        if (model, method) == ("ir.attachment", "create"):
            values = dict(args[0])
            values["checksum"] = hashlib.sha1(base64.b64decode(values["datas"])).hexdigest()  # noqa: S324
            return self.add(model, **values)
        if (model, method) == ("account.journal", "create_document_from_attachment"):
            return self._document_from_attachment(args, kwargs or {})
        raise AssertionError(f"the fake does not know {key}")

    def _document_from_attachment(self, args: list[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
        journal_ids, attachment_ids = args  # a recordset method: [journal ids, attachment ids]
        assert all(i in self.tables["ir.attachment"] for i in attachment_ids), "attachment id passed as a journal id?"
        assert kwargs["context"]["default_move_type"] == "in_invoice"
        if journal_ids:
            assert kwargs["context"].get("default_journal_id") == journal_ids[0]
        bill = self.add("account.move", move_type="in_invoice", state=self.state_of_new_bill,
                        partner_id=self.partner_on_new_bill)
        self.tables["ir.attachment"][attachment_ids[0]].update(res_model="account.move", res_id=bill)
        return {"res_model": "account.move", "res_id": bill, "view_mode": "form"}
