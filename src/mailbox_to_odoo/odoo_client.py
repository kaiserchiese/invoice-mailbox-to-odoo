"""Odoo's external API over JSON-RPC (`/jsonrpc`). Stdlib only.

Two calls matter: `common.authenticate` and `object.execute_kw`. Odoo 19 announces a
JSON-2 API in their place; this client targets the JSON-RPC that 17 and 18 serve.
"""

from __future__ import annotations

import itertools
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class OdooError(RuntimeError):
    """Anything that stops a call: bad credentials, an RPC fault, an unreachable server."""


@dataclass
class OdooClient:
    url: str
    db: str
    user: str
    key: str = field(repr=False)
    timeout: float = 60.0
    _uid: int | None = field(default=None, init=False, repr=False)
    _ids: Any = field(default_factory=itertools.count, init=False, repr=False)

    @classmethod
    def from_env(cls) -> OdooClient:
        values = {n: os.environ.get(f"ODOO_{n.upper()}", "") for n in ("url", "db", "user", "api_key")}
        missing = [f"ODOO_{n.upper()}" for n, v in values.items() if not v]
        if missing:
            raise OdooError(f"Set {', '.join(missing)} (ODOO_API_KEY can be the password of a local demo database)")
        return cls(values["url"], values["db"], values["user"], values["api_key"])

    def _call(self, service: str, method: str, args: list[Any]) -> Any:
        body = {"jsonrpc": "2.0", "method": "call", "id": next(self._ids),
                "params": {"service": service, "method": method, "args": args}}
        request = urllib.request.Request(
            self.url.rstrip("/") + "/jsonrpc", json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (the user's own URL)
                answer = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise OdooError(f"cannot reach Odoo at {self.url}: {error}") from None
        except ValueError:
            raise OdooError(f"{self.url} did not answer as Odoo JSON-RPC: check ODOO_URL (server root only)") from None
        if "error" in answer:
            detail = answer["error"].get("data", {}).get("message") or answer["error"].get("message", "unknown error")
            raise OdooError(f"{service}.{method}: {detail}")
        return answer.get("result")

    def authenticate(self) -> int:
        if self._uid is None:
            uid = self._call("common", "authenticate", [self.db, self.user, self.key, {}])
            if not uid:
                raise OdooError(f"authentication failed for {self.user!r} on database {self.db!r}")
            self._uid = int(uid)
        return self._uid

    def execute(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        call = [self.db, self.authenticate(), self.key, model, method, args, kwargs or {}]
        return self._call("object", "execute_kw", call)
