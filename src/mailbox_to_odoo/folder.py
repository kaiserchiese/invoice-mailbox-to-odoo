"""What gets written into the supplier folders. No network: it takes mails already read."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from email.message import Message
from pathlib import Path

from . import message
from .rules import Rule


@dataclass(frozen=True)
class New:
    rule: str
    target: Path
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class WithoutPdf:
    rule: str
    day: date
    subject: str


@dataclass
class Plan:
    new: list[New] = field(default_factory=list)
    already_there: int = 0
    without_pdf: list[WithoutPdf] = field(default_factory=list)


def _fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def pdfs_in(directory: Path) -> list[Path]:
    """Subfolders count too ('Acme/2026/...')."""
    return [p for p in directory.rglob("*") if p.suffix.lower() == ".pdf"] if directory.is_dir() else []


def _free(directory: Path, name: str, taken: set[Path]) -> Path:
    """Never overwrite: if the target exists, suffix ' (2)', ' (3)'... (safety net, e.g. a case-insensitive clash)."""
    target = directory / name
    n = 2
    while target.exists() or target in taken:
        target = directory / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return target


def plan(root: Path, mails: Iterable[tuple[Rule, Message]]) -> Plan:
    """The same PDF is never written twice: not with the same content, not with the same name.

    The name counts because some senders (Stripe) re-render the PDF on every send: the
    same invoice arrives with other bytes, and writing it as ' (2)' would book it twice.
    """
    result = Plan()
    seen: dict[Path, set[str]] = {}
    names: dict[Path, set[str]] = {}
    taken: set[Path] = set()
    for rule, msg in mails:
        directory = root / rule.folder
        fingerprints = seen.setdefault(directory, {_fingerprint(p.read_bytes()) for p in pdfs_in(directory)})
        existing = names.setdefault(directory, {p.name.lower() for p in pdfs_in(directory)})
        attachments = message.pdfs(msg)
        if not attachments:
            result.without_pdf.append(WithoutPdf(rule.name, message.day(msg), message.subject(msg)))
            continue
        # A mail with PDFs but none of them an invoice (an annex) is not a warning: skipped.
        for name, content in (a for a in attachments if re.search(rule.attachment, a[0], re.IGNORECASE)):
            fingerprint = _fingerprint(content)
            filename = message.filename(name, message.day(msg))
            if fingerprint in fingerprints or filename.lower() in existing:
                result.already_there += 1
                continue
            fingerprints.add(fingerprint)
            existing.add(filename.lower())
            target = _free(directory, filename, taken)
            taken.add(target)
            result.new.append(New(rule.name, target, content))
    return result


def write(to_write: Plan) -> None:
    for new in to_write.new:
        new.target.parent.mkdir(parents=True, exist_ok=True)
        new.target.write_bytes(new.content)
