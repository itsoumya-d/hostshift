"""HttpBridgeSession tests against a local stub server.

The bridge client is the harness's only window into the device-backed hosts,
so its contract parsing gets tested for real: a threaded HTTP server serves
the six endpoints, the session must map them onto the Session protocol, and a
dead port must raise RenderError rather than hang."""

import json
import pathlib
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.render.base import RenderError
from hostshift.render.bridge import HttpBridgeSession, _widget

TREE = {
    "kind": "container", "name": "Screen", "node_id": "main",
    "focusable": False,
    "children": [
        {"kind": "input", "name": "Email", "node_id": "email",
         "focusable": True, "children": []},
    ],
}

ACTIONS = [
    {"id": "email", "kind": "input", "name": "Email", "enabled": True,
     "value": "", "options": []},
]


class StubBridge(BaseHTTPRequestHandler):
    invoked = []

    def log_message(self, *a):  # silence test output
        return

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/state":
            self._send({"route": "main", "values": {"x": ""}, "collections": {}})
        elif self.path == "/tree":
            self._send(TREE)
        elif self.path == "/actions":
            self._send(ACTIONS)
        elif self.path == "/facts":
            self._send({"error_visible": False, "empty_state_visible": False,
                        "enabled": {"email": True}, "field_values": {},
                        "options": {}, "visible_rows": {}})
        else:
            self._send({})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        StubBridge.invoked.append((self.path, payload))
        self._send({"status": "ok"})


def test_bridge_session_maps_endpoints():
    server = HTTPServer(("127.0.0.1", 0), StubBridge)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        s = HttpBridgeSession("compose", port=port, timeout=5)
        assert s.state()["route"] == "main"
        tree = s.widget_tree()
        assert tree.kind == "container"
        assert tree.children[0].name == "Email"
        assert s.actions()[0]["id"] == "email"
        assert s.ui_facts()["enabled"] == {"email": True}
        s.invoke("email", "a@b.c")
        s.reset()
        assert ("POST /invoke".replace("POST ", ""), {"id": "email", "value": "a@b.c"}) in \
            [(p, d) for p, d in StubBridge.invoked]
        assert any(path == "/reset" for path, _ in StubBridge.invoked)
        s.close()  # must be a no-op, not an error
    finally:
        server.shutdown()


def test_bridge_dead_port_raises_render_error():
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    try:
        HttpBridgeSession("swiftui", port=dead_port, timeout=1)
        raised = False
    except RenderError:
        raised = True
    assert raised


def test_widget_conversion_defaults():
    w = _widget({"kind": "text"})
    assert w.kind == "text" and w.name is None and w.node_id is None
    assert not w.focusable and w.children == []


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = skipped = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except unittest.SkipTest as exc:
            skipped += 1
            print(f"  SKIP  {fn.__name__}  ({exc})")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    ran = len(fns) - failed - skipped
    print(f"\n{ran}/{len(fns)} passed, {skipped} skipped")
    sys.exit(1 if failed else 0)
