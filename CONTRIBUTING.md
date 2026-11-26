# Contributing

Small project, small rules.

```
git clone https://github.com/kaiserchiese/invoice-mailbox-to-odoo && cd invoice-mailbox-to-odoo
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check src tests && mypy && pytest --cov=mailbox_to_odoo
```

- Tests first: a failing test for the behaviour, then the change. Tests never touch the network; the IMAP side is covered with a fake server (see `tests/test_imap.py`).
- Never put a real address, supplier, password or invoice in code, tests, fixtures or issues. Use `example.test` domains and invented names.
- Keep it stdlib plus PyYAML. A new dependency needs a reason in the PR.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`).
- Bigger ideas (a second mail provider, Odoo 19's JSON-2 API) start as an issue; see [docs/ROADMAP.md](docs/ROADMAP.md).
