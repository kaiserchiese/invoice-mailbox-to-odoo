"""mailbox-to-odoo RULES.yaml [ROOT] [--odoo] [--execute] [--watch MINUTES]: dry run unless --execute."""

from __future__ import annotations

import argparse
import imaplib
import io
import os
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from email.message import Message
from pathlib import Path
from time import sleep

from . import folder, imap, odoo, rules
from .odoo_client import OdooClient, OdooError

LOCK_NAME = ".mailbox-to-odoo.lock"


def fetch(credentials: imap.Credentials, config: rules.Config) -> list[tuple[rules.Rule, Message]]:
    mails: list[tuple[rules.Rule, Message]] = []
    with imap.connect(credentials) as conn:
        for rule in (r for r in config.rules if r.query):
            found = imap.search_rule(conn, rule, config.since)
            print(f"  {rule.name}: {len(found)} mails")
            mails += [(rule, m) for m in found]
    return mails


def connect_odoo() -> odoo.Client:
    return OdooClient.from_env()


def folder_step(root: Path, mails: list[tuple[rules.Rule, Message]], execute: bool) -> None:
    result = folder.plan(root, mails)
    print(f"\n{len(result.new)} new | {result.already_there} already there | {len(result.without_pdf)} without PDF")
    for new in result.new:
        print(f"  + {new.target.relative_to(root)}")
    for mail in result.without_pdf:
        print(f"  ? {mail.rule} {mail.day} '{mail.subject}': no PDF attached")
    if execute:
        folder.write(result)
        print(f"Wrote {len(result.new)} into {root}")
    elif result.new:
        print("Dry run: --execute to write them.")


def odoo_step(mails: list[tuple[rules.Rule, Message]], execute: bool) -> int:
    """Exit code 1 when a rule or a PDF could not be handled."""
    client = connect_odoo()
    try:
        journal = odoo.journal_id(client, os.environ.get("ODOO_JOURNAL", ""))
    except ValueError as error:
        print(f"Odoo: {error}")
        return 1
    to_do = odoo.plan(client, odoo.items(mails))
    print(f"\nOdoo: {len(to_do.new)} new | {len(to_do.already)} already in Odoo | {len(to_do.errors)} rule errors")
    for planned in to_do.new:
        print(f"  + {planned.item.rule.name}: {planned.item.name}")
    for item, why in to_do.already:
        print(f"  = {item.name} ({why})")
    for problem in to_do.errors:
        print(f"  ! {problem}")
    failed = bool(to_do.errors)
    if execute:
        result = odoo.execute(client, to_do, journal)
        for name, bill in result.created:
            print(f"  {name} -> bill {bill}")
        for problem in result.errors:
            print(f"  ! {problem}")
        failed = failed or bool(result.errors)
    elif to_do.new:
        print("Dry run: --execute to create the draft bills.")
    return 1 if failed else 0


def cycle(args: argparse.Namespace, config: rules.Config) -> int:
    mails = fetch(imap.Credentials.from_env(), config)
    if args.root:
        folder_step(args.root, mails, args.execute)
    try:
        return odoo_step(mails, args.execute) if args.odoo else 0
    except OdooError as error:
        print(f"Odoo: {error}")
        return 1


@contextmanager
def _single_run(path: Path) -> Iterator[bool]:
    """One writing run at a time: Odoo has no unique key to stop two runs creating the same bill."""
    try:
        os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        yield False
        return
    # shortcut: SIGTERM (a service stop) releases the lock; kill -9 or a power cut does not, delete the file by hand
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        yield True
    finally:
        path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mailbox-to-odoo", description=__doc__)
    parser.add_argument("rules", type=Path)
    parser.add_argument("root", type=Path, nargs="?", help="folder that holds one subfolder per supplier")
    parser.add_argument("--odoo", action="store_true", help="create draft vendor bills in Odoo (ODOO_* variables)")
    parser.add_argument("--execute", action="store_true", help="write the PDFs and the bills (default: dry run)")
    parser.add_argument("--watch", type=float, metavar="MINUTES", help="repeat every MINUTES; needs --execute")
    args = parser.parse_args(argv)
    if not args.root and not args.odoo:
        parser.error("give a ROOT folder, --odoo, or both")
    if args.watch and not args.execute:
        parser.error("--watch needs --execute: a dry run on repeat changes nothing")
    # Subjects are printed as received: a cp1252 console or log file must not crash the run.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")

    config = rules.load(args.rules)
    lock = args.rules.resolve().parent / LOCK_NAME
    with _single_run(lock) if args.execute and args.odoo else _no_lock() as free:
        if not free:
            print(f"Another run holds {lock}. If none is running, delete that file.")
            return 2
        if not args.watch:
            return cycle(args, config)
        while True:
            try:
                cycle(args, config)
            except (OdooError, RuntimeError, OSError, imaplib.IMAP4.error) as error:
                print(f"Cycle failed, will retry: {error}")
            print(f"Next run in {args.watch:g} minutes (Ctrl+C to stop)")
            try:
                sleep(args.watch * 60)
            except KeyboardInterrupt:
                return 0


@contextmanager
def _no_lock() -> Iterator[bool]:
    yield True


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
