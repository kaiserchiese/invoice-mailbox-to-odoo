"""Which mails are supplier invoices, and which folder each one goes to."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Rule:
    name: str
    folder: str  # relative to the root folder given at run time
    # Gmail search box syntax (X-GM-RAW). Empty = this supplier's invoice does not
    # arrive by mail; the rule is skipped when searching.
    query: str = ""
    # Regex on the attachment file name, for suppliers that send annexes or contracts
    # in the same thread. Empty = every PDF.
    attachment: str = ""
    # The Odoo vendor, only used by --odoo: its exact name, or 'vat:XX123' to match the VAT.
    # Empty = the bill is created with no supplier. It is never guessed from the sender.
    partner: str = ""


@dataclass(frozen=True)
class Config:
    since: date
    rules: tuple[Rule, ...]


def load(path: Path) -> Config:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    since = data.get("since")
    if since is None:
        raise ValueError(f"{path}: 'since' is required (mails before it are ignored)")
    return Config(
        since=since if isinstance(since, date) else date.fromisoformat(str(since)),
        rules=tuple(
            Rule(
                name=str(r["name"]),
                folder=str(r["folder"]),
                query=str(r.get("query") or ""),
                attachment=str(r.get("attachment") or ""),
                partner=str(r.get("partner") or ""),
            )
            for r in data.get("rules") or []
        ),
    )
