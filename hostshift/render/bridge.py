"""HTTP instrumentation bridge for device-backed hosts.

iOS and Android apps cannot be inspected from the harness the way a browser DOM
can, so the generated apps serve their own instrumentation over loopback HTTP
and the harness reads it. Same five endpoints on both platforms, matching the
`window.__hostshift` contract on web:

    GET  /state    GET /facts    GET /tree    GET /actions
    POST /invoke   {"id": ..., "value": ...}
    POST /reset

Two properties of this design matter for the experiment. The tree endpoint must
report the *realized* view hierarchy read back from the platform's accessibility
APIs, never a re-serialization of the spec -- otherwise render parity would
measure the generator and not the host. And the port is fixed per host so that
an emulator port-forward is a one-line setup rather than per-run discovery.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..widgettree import Widget
from .base import RenderError

DEFAULT_PORTS = {"swiftui": 8781, "compose": 8782}


def _widget(d: dict) -> Widget:
    return Widget(
        kind=d.get("kind", "container"),
        name=d.get("name"),
        node_id=d.get("node_id"),
        focusable=bool(d.get("focusable")),
        children=[_widget(c) for c in d.get("children") or []],
    )


class HttpBridgeSession:
    """Session backed by an app serving the instrumentation contract."""

    simulated = False

    def __init__(self, host: str, port: int | None = None, timeout: float = 10.0):
        self.host = host
        self.port = port or DEFAULT_PORTS.get(host, 8780)
        self.timeout = timeout
        self._base = f"http://127.0.0.1:{self.port}"
        self._check()

    def _check(self) -> None:
        try:
            self._get("/state")
        except Exception as exc:
            raise RenderError(
                f"no {self.host} instrumentation bridge on {self._base}. Launch the "
                f"generated app on the simulator or emulator, and for Android "
                f"forward the port with `adb forward tcp:{self.port} tcp:{self.port}`."
            ) from exc

    def _get(self, path: str):
        with urllib.request.urlopen(self._base + path, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def _post(self, path: str, body: dict):
        req = urllib.request.Request(
            self._base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise RenderError(f"{self.host} bridge rejected {path}: {exc.read().decode()[:200]}") from exc

    def widget_tree(self) -> Widget:
        return _widget(self._get("/tree"))

    def state(self) -> dict:
        return self._get("/state")

    def ui_facts(self) -> dict:
        return self._get("/facts")

    def actions(self) -> list[dict]:
        return self._get("/actions")

    def invoke(self, node_id: str, value: object | None = None) -> None:
        self._post("/invoke", {"id": node_id, "value": value})

    def reset(self) -> None:
        self._post("/reset", {})

    def close(self) -> None:
        # The app outlives the session; the harness relaunches per task rather
        # than reusing a process, so that state cannot leak between tasks.
        return None
