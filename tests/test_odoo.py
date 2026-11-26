"""The Odoo step: what gets created, and what is left alone. Against the in-memory fake."""

from __future__ import annotations

import base64
from datetime import date

import pytest

from fake_odoo import FakeOdoo
from mailbox_to_odoo import odoo
from mailbox_to_odoo.rules import Rule

PDF = b"%PDF-1.4 invoice one"
ACME = Rule(name="Acme", folder="Acme", partner="Acme Hosting SL")


def item(
    rule: Rule = ACME, name: str = "INV-1.pdf", content: bytes = PDF, message_id: str = "<m1@acme.test>"
) -> odoo.Item:
    return odoo.Item(rule, name, content, message_id, date(2026, 11, 1))


@pytest.fixture
def fake() -> FakeOdoo:
    odoo_fake = FakeOdoo()
    odoo_fake.add("res.partner", name="Acme Hosting SL", vat="ESB123")
    return odoo_fake


def run(fake: FakeOdoo, *items: odoo.Item, journal: int | None = None) -> odoo.Result:
    return odoo.execute(fake, odoo.plan(fake, list(items)), journal)


def test_one_pdf_becomes_a_draft_bill_with_the_pdf_and_the_rule_supplier(fake: FakeOdoo) -> None:
    result = run(fake, item())

    (bill_id,) = fake.tables["account.move"]
    bill = fake.tables["account.move"][bill_id]
    (attachment,) = fake.tables["ir.attachment"].values()
    assert result.created == [("INV-1.pdf", bill_id)]
    assert bill["state"] == "draft"
    assert bill["partner_id"] == next(iter(fake.tables["res.partner"]))
    assert (attachment["res_model"], attachment["res_id"]) == ("account.move", bill_id)
    assert attachment["name"] == "INV-1.pdf"
    assert base64.b64decode(attachment["datas"]) == PDF


def test_planning_only_reads(fake: FakeOdoo) -> None:
    plan = odoo.plan(fake, [item()])

    assert len(plan.new) == 1
    assert fake.writes() == []


def test_a_rule_without_partner_makes_a_bill_without_supplier(fake: FakeOdoo) -> None:
    run(fake, item(Rule(name="Anon", folder="Anon")))

    (bill,) = fake.tables["account.move"].values()
    assert bill["partner_id"] is False
    assert ("account.move", "write") not in fake.calls


def test_a_rule_can_match_the_supplier_by_vat(fake: FakeOdoo) -> None:
    run(fake, item(Rule(name="Acme", folder="Acme", partner="vat:ESB123")))

    (bill,) = fake.tables["account.move"].values()
    assert bill["partner_id"] == next(iter(fake.tables["res.partner"]))


def test_a_vat_rule_ignores_the_contacts_that_inherit_the_vat_of_their_company(fake: FakeOdoo) -> None:
    company = next(iter(fake.tables["res.partner"]))
    fake.add("res.partner", name="Acme Contact", vat="ESB123", parent_id=company)  # Odoo copies the vat to children

    run(fake, item(Rule(name="Acme", folder="Acme", partner="vat:ESB123")))

    (bill,) = fake.tables["account.move"].values()
    assert bill["partner_id"] == company


@pytest.mark.parametrize(("partner", "problem"), [("Nobody Ltd", "no vendor"), ("Twin SL", "2 vendors")])
def test_a_supplier_that_is_not_exactly_one_vendor_is_an_error_and_nothing_is_sent(
    fake: FakeOdoo, partner: str, problem: str
) -> None:
    fake.add("res.partner", name="Twin SL")
    fake.add("res.partner", name="Twin SL")

    plan = odoo.plan(fake, [item(Rule(name="X", folder="X", partner=partner))])

    assert plan.new == []
    assert len(plan.errors) == 1 and "X" in plan.errors[0] and problem in plan.errors[0]
    assert fake.writes() == []


def seed_bill(fake: FakeOdoo, attachment: odoo.Item | None = None, *, name: str = "x.pdf", content: bytes = b"other",
              marker: str = "", partner: str = "Acme Hosting SL", res_model: str | bool = "account.move") -> int:
    """A bill (or orphan attachment) that is already in Odoo before the run."""
    import hashlib

    partner_id = next(i for i, p in fake.tables["res.partner"].items() if p["name"] == partner)
    bill = fake.add("account.move", partner_id=partner_id, state="draft") if res_model else 0
    if attachment:
        name, content, marker = attachment.name, attachment.content, attachment.marker
    fake.add("ir.attachment", name=name, res_model=res_model, res_id=bill if res_model else False,
             description=marker, checksum=hashlib.sha1(content).hexdigest())  # noqa: S324
    return bill


def test_a_mail_already_in_odoo_is_skipped(fake: FakeOdoo) -> None:
    seed_bill(fake, item())

    plan = odoo.plan(fake, [item()])

    assert plan.new == [] and len(plan.already) == 1
    assert fake.writes() == []


def test_the_same_bytes_in_another_mail_are_skipped_even_if_a_person_uploaded_them(fake: FakeOdoo) -> None:
    seed_bill(fake, content=PDF)  # no marker: uploaded by hand

    plan = odoo.plan(fake, [item(message_id="<resent@acme.test>", name="renamed.pdf")])

    assert plan.new == [] and "same PDF" in plan.already[0][1]


def test_the_same_file_name_for_the_same_supplier_is_the_same_invoice_even_with_other_bytes(fake: FakeOdoo) -> None:
    seed_bill(fake, name="INV-1.pdf", content=b"re-rendered")

    plan = odoo.plan(fake, [item()])

    assert plan.new == [] and "same file name" in plan.already[0][1]


def test_the_same_file_name_for_another_supplier_is_a_new_invoice(fake: FakeOdoo) -> None:
    fake.add("res.partner", name="Other SL")
    seed_bill(fake, name="INV-1.pdf", content=b"theirs", partner="Other SL")

    assert len(odoo.plan(fake, [item()]).new) == 1


def test_the_same_name_twice_in_one_run_is_one_invoice(fake: FakeOdoo) -> None:
    result = run(fake, item(), item(content=b"%PDF-1.4 again", message_id="<m2@acme.test>"))

    assert len(result.created) == 1 and len(fake.tables["account.move"]) == 1


def test_an_attachment_left_over_by_a_dead_run_is_replaced_not_duplicated(fake: FakeOdoo) -> None:
    seed_bill(fake, item(), res_model=False)  # uploaded, never turned into a bill
    (orphan,) = fake.tables["ir.attachment"]

    run(fake, item())

    assert orphan not in fake.tables["ir.attachment"]
    (kept,) = fake.tables["ir.attachment"].values()
    assert kept["res_model"] == "account.move" and len(fake.tables["account.move"]) == 1


def test_running_twice_creates_one_bill(fake: FakeOdoo) -> None:
    run(fake, item())
    second = odoo.plan(fake, [item()])

    assert second.new == [] and len(fake.tables["account.move"]) == 1


def test_a_failed_conversion_removes_the_upload_and_the_next_pdf_still_goes(fake: FakeOdoo) -> None:
    fake.fail_on["account.journal.create_document_from_attachment"] = "boom"

    result = run(fake, item(), item(name="INV-2.pdf", content=b"%PDF second", message_id="<m2@acme.test>"))

    assert len(result.errors) == 1 and "INV-1.pdf" in result.errors[0] and "boom" in result.errors[0]
    assert [name for name, _ in result.created] == ["INV-2.pdf"]
    (kept,) = fake.tables["ir.attachment"].values()
    assert kept["name"] == "INV-2.pdf"


def test_a_timeout_that_did_create_the_bill_is_not_undone(fake: FakeOdoo) -> None:
    from mailbox_to_odoo.odoo_client import OdooError

    original = fake._document_from_attachment

    def commit_then_time_out(args: list[object], kwargs: dict[str, object]) -> dict[str, object]:
        original(args, kwargs)
        raise OdooError("timed out")

    fake._document_from_attachment = commit_then_time_out  # type: ignore[method-assign]

    result = run(fake, item())

    assert len(fake.tables["account.move"]) == 1 and len(fake.tables["ir.attachment"]) == 1
    assert [name for name, _ in result.created] == ["INV-1.pdf"]
    assert fake.tables["account.move"][result.created[0][1]]["partner_id"] != False  # noqa: E712


def test_a_failed_supplier_write_keeps_the_bill_and_says_so(fake: FakeOdoo) -> None:
    fake.fail_on["account.move.write"] = "access denied"

    result = run(fake, item())

    assert len(fake.tables["account.move"]) == 1
    assert len(result.created) == 1 and "supplier not set" in result.errors[0] and "access denied" in result.errors[0]


def test_odoo_posting_the_bill_by_itself_is_reported_and_the_supplier_is_left_alone(fake: FakeOdoo) -> None:
    fake.state_of_new_bill = "posted"

    result = run(fake, item())

    (bill,) = fake.tables["account.move"].values()
    assert bill["partner_id"] is False
    assert "posted" in result.errors[0] and len(result.created) == 1


def test_the_same_pdf_twice_in_one_run_is_one_bill_even_under_two_names(fake: FakeOdoo) -> None:
    again = item(name="2026-11-15 invoice.pdf", message_id="<m2@acme.test>")

    result = run(fake, item(name="2026-11-01 invoice.pdf"), again)

    assert len(result.created) == 1 and len(fake.tables["account.move"]) == 1


def test_one_mail_matching_two_rules_is_one_bill(fake: FakeOdoo) -> None:
    other = Rule(name="Acme again", folder="Acme2", partner="Acme Hosting SL")

    result = run(fake, item(), item(rule=other))

    assert len(result.created) == 1


def test_two_rules_with_the_same_name_keep_their_own_supplier(fake: FakeOdoo) -> None:
    fake.add("res.partner", name="Acme Web SL")
    eu = Rule(name="Acme", folder="A", partner="Acme Hosting SL")
    web = Rule(name="Acme", folder="B", partner="Acme Web SL")

    run(fake, item(eu), item(web, name="W-1.pdf", content=b"%PDF web", message_id="<w@acme.test>"))

    partners = {fake.tables["res.partner"][b["partner_id"]]["name"] for b in fake.tables["account.move"].values()}
    assert partners == {"Acme Hosting SL", "Acme Web SL"}


def test_a_failed_upload_after_an_earlier_bill_is_not_called_a_supplier_problem(fake: FakeOdoo) -> None:
    from mailbox_to_odoo.odoo_client import OdooError

    other = Rule(name="Other", folder="O")
    plan = odoo.plan(fake, [item(), item(other, content=b"%PDF other", message_id="<o@x.test>")])
    real = fake.execute
    calls = {"n": 0}

    def flaky(model: str, method: str, args: list[object], kwargs: dict[str, object] | None = None) -> object:
        calls["n"] += model == "ir.attachment" and method == "create"
        if model == "ir.attachment" and method == "create" and calls["n"] == 2:
            raise OdooError("timed out")
        return real(model, method, args, kwargs)

    fake.execute = flaky  # type: ignore[method-assign]
    result = odoo.execute(fake, plan, None)

    assert len(result.created) == 1 and result.errors[0].startswith("INV-1.pdf: failed:")


def test_a_supplier_that_odoo_set_by_itself_is_replaced_and_the_run_says_so(fake: FakeOdoo) -> None:
    other = fake.add("res.partner", name="Set By Odoo")
    fake.partner_on_new_bill = other

    result = run(fake, item())

    (bill,) = fake.tables["account.move"].values()
    assert bill["partner_id"] == next(iter(fake.tables["res.partner"]))
    assert "another supplier" in result.errors[0]
