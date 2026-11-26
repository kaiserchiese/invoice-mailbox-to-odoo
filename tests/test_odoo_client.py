"""The JSON-RPC client, against a fake Odoo on the loopback interface (no external network)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from mailbox_to_odoo.odoo_client import OdooClient, OdooError


class _Fake(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]]
    uid: int | bool = 7
    fault: str = ""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(body)
        params = body["params"]
        if params["method"] == "authenticate":
            out: dict[str, Any] = {"jsonrpc": "2.0", "id": body["id"], "result": type(self).uid}
        elif type(self).fault:
            out = {"jsonrpc": "2.0", "id": body["id"], "error": {"message": "Odoo Server Error",
                   "data": {"message": type(self).fault}}}
        else:
            out = {"jsonrpc": "2.0", "id": body["id"], "result": [42]}
        payload = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[tuple[str, type[_Fake]]]:
    handler = type("Handler", (_Fake,), {"requests": [], "uid": 7, "fault": ""})
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", handler
    httpd.shutdown()


def test_execute_authenticates_once_and_sends_execute_kw(server: tuple[str, type[_Fake]]) -> None:
    url, fake = server
    client = OdooClient(url, "demo", "admin", "secret-key")

    first = client.execute("res.partner", "search", [[["name", "=", "Acme"]]], {"limit": 2})
    client.execute("res.partner", "search", [[]])

    assert first == [42]
    auth, call, _ = (r["params"] for r in fake.requests)
    assert (auth["service"], auth["method"]) == ("common", "authenticate")
    assert auth["args"][:3] == ["demo", "admin", "secret-key"]
    assert (call["service"], call["method"]) == ("object", "execute_kw")
    assert call["args"] == ["demo", 7, "secret-key", "res.partner", "search", [[["name", "=", "Acme"]]], {"limit": 2}]
    assert len([r for r in fake.requests if r["params"]["method"] == "authenticate"]) == 1


def test_bad_credentials_stop_before_any_call(server: tuple[str, type[_Fake]]) -> None:
    url, fake = server
    fake.uid = False

    with pytest.raises(OdooError, match="authentication failed"):
        OdooClient(url, "demo", "admin", "wrong").execute("res.partner", "search", [[]])

    assert len(fake.requests) == 1


def test_rpc_fault_shows_odoos_message_and_never_the_key(server: tuple[str, type[_Fake]]) -> None:
    url, fake = server
    fake.fault = "You are not allowed to create 'Journal Entry'"

    with pytest.raises(OdooError) as error:
        OdooClient(url, "demo", "admin", "secret-key").execute("account.move", "create", [[{}]])

    assert "not allowed to create" in str(error.value)
    assert "secret-key" not in str(error.value)


def test_unreachable_server_is_an_odoo_error() -> None:
    with pytest.raises(OdooError, match="cannot reach"):
        OdooClient("http://127.0.0.1:1", "demo", "admin", "k").execute("res.partner", "search", [[]])


def test_a_reply_that_is_not_json_says_to_check_the_url() -> None:
    handler = type("Html", (BaseHTTPRequestHandler,), {
        "do_POST": lambda self: (self.send_response(200), self.send_header("Content-Length", "6"),
                                 self.end_headers(), self.wfile.write(b"<html>")),
        "log_message": lambda *_: None,
    })
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    with pytest.raises(OdooError, match="check ODOO_URL"):
        OdooClient(f"http://127.0.0.1:{httpd.server_port}/odoo", "d", "u", "k").execute("res.partner", "search", [[]])
    httpd.shutdown()
