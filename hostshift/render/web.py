"""Web host: UISpec -> a self-contained HTML page with a React-style runtime.

Emits one file with no build step and no network dependency, which matters for
reproducibility: a reviewer can open the artifact years from now without
resolving an npm tree that no longer exists.

The page exposes `window.__hostshift`, the instrumentation contract every host
must satisfy: `state()`, `facts()`, `tree()`, `actions()`, `invoke()`. Without a
state hook there is no host-fair oracle, so instrumentation is generated
alongside the UI rather than bolted on.
"""

from __future__ import annotations

import json

from ..widgettree import Widget
from .base import WEB, RenderError
from .session import SimulatedSession

RUNTIME_JS = r"""
// HostShift web runtime. A faithful but independent implementation of the
// UISpec semantics -- independent on purpose: divergence between per-platform
// runtime implementations is the phenomenon this benchmark measures.
(function () {
  const SPEC = window.__HOSTSHIFT_SPEC__;
  const DEFAULTS = { string: "", number: 0, boolean: false, date: null, enum: null };
  const FOCUSABLE = new Set(["field", "select", "toggle", "button"]);

  function assign(obj, path, value) {
    const parts = path.split(".");
    let cur = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  function resolve(state, path) {
    if (!path) return null;
    if (path.indexOf("$state.") === 0) path = path.slice(7);
    if (path.endsWith(".length")) {
      const b = resolve(state, path.slice(0, -7));
      return b == null ? null : (b.length !== undefined ? b.length : null);
    }
    let cur = state;
    for (const p of path.split(".")) {
      if (cur && typeof cur === "object" && p in cur) cur = cur[p];
      else if (cur && cur.collections && p in cur.collections) cur = cur.collections[p];
      else return null;
    }
    return cur;
  }

  function looseEq(a, b) {
    if (typeof a === "boolean" || typeof b === "boolean") return a === b;
    if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
    if (typeof a === "string" && typeof b === "string") return a.trim() === b.trim();
    return a === b;
  }

  function evaluate(pred, state, row) {
    if (!pred) return true;
    const op = pred.op;
    if (op === "and") return (pred.clauses || []).every((c) => evaluate(c, state, row));
    if (op === "or") return (pred.clauses || []).some((c) => evaluate(c, state, row));
    if (op === "not") return !evaluate((pred.clauses || [])[0], state, row);
    const leftPath = pred.left;
    const left = (row && typeof leftPath === "string" && leftPath.indexOf("$row.") === 0)
      ? row[leftPath.slice(5)]
      : resolve(state, leftPath);
    let right = pred.right;
    if (typeof right === "string" && right.indexOf("$state.") === 0) right = resolve(state, right.slice(7));
    switch (op) {
      case "truthy": return !!left;
      case "falsy": return !left;
      case "nonempty": return left != null && (left.length !== undefined ? left.length > 0 : !!left);
      case "matches": return left != null && new RegExp(String(right)).test(String(left));
      case "eq": return looseEq(left, right);
      case "ne": return !looseEq(left, right);
      case "gt": case "lt": case "gte": case "lte": {
        if (left == null || right == null) return false;
        const a = isNaN(Number(left)) ? String(left) : Number(left);
        const b = isNaN(Number(right)) ? String(right) : Number(right);
        return op === "gt" ? a > b : op === "lt" ? a < b : op === "gte" ? a >= b : a <= b;
      }
      default: throw new Error("unknown predicate op " + op);
    }
  }

  function rowMatches(row, match) {
    return Object.keys(match || {}).every((k) => looseEq(row[k], match[k]));
  }

  const TPL = ["$state.", "$row.", "$payload"];
  function expand(value, state, row, payload) {
    if (typeof value === "string" && TPL.some((p) => value.startsWith(p))) {
      if (value === "$payload") return payload;
      if (value.startsWith("$state.")) return resolve(state, value.slice(7));
      return (row || {})[value.slice(5)];
    }
    if (Array.isArray(value)) return value.map((v) => expand(v, state, row, payload));
    if (value && typeof value === "object") {
      const o = {};
      for (const [k, v] of Object.entries(value)) o[k] = expand(v, state, row, payload);
      return o;
    }
    return value;
  }

  function applyActions(actions, state, payload, row) {
    if (!actions) return state;
    const seq = Array.isArray(actions) ? actions : [actions];
    let st = state;
    for (const a of seq) st = applyAction(a, st, payload, row);
    return st;
  }

  function applyAction(action, state, payload, row) {
    if (!action) return state;
    const st = JSON.parse(JSON.stringify(state));
    if (!evaluate(action.guardWhen, st)) return st;
    const t = action.target;
    switch (action.op) {
      case "navigate": st.route = t; break;
      case "set": {
        let v = "value" in action ? action.value : payload;
        if (action.from) v = resolve(st, action.from);
        assign(st, t, expand(v, st, row, payload)); break;
      }
      case "clear": {
        const d = (SPEC.state || {})[t] || {};
        assign(st, t, "default" in d ? d.default : DEFAULTS[d.type]); break;
      }
      case "append": {
        if (!st.collections[t]) st.collections[t] = [];
        let nr = expand(action.value, st, row, payload);
        if (nr == null) nr = payload;
        if (nr == null || typeof nr !== "object") throw new Error("append needs an object row");
        st.collections[t].push(JSON.parse(JSON.stringify(nr)));
        break;
      }
      case "remove": {
        const m = expand(action.value, st, row, payload) || payload || {};
        st.collections[t] = (st.collections[t] || []).filter((r) => !rowMatches(r, m));
        break;
      }
      case "update": {
        const p = expand(action.value, st, row, payload) || payload || {};
        (st.collections[t] || []).forEach((r) => {
          if (rowMatches(r, p.where || {})) Object.assign(r, p.set || {});
        });
        break;
      }
      case "submit": if (t) assign(st, t, true); break;
      case "dismiss": if (t) assign(st, t, false); break;
      default: throw new Error("unknown action op " + action.op);
    }
    return st;
  }

  function initialState() {
    const st = { collections: {}, route: SPEC.entry };
    for (const [k, d] of Object.entries(SPEC.state || {})) {
      assign(st, k, "default" in d ? d.default : DEFAULTS[d.type]);
    }
    for (const [k, d] of Object.entries(SPEC.collections || {})) {
      st.collections[k] = JSON.parse(JSON.stringify(d.seed || []));
    }
    return st;
  }

  let STATE = initialState();

  function project(state) {
    const screen = (SPEC.screens || []).find((s) => s.id === (state.route || SPEC.entry));
    if (!screen) throw new Error("route matches no screen");
    function conv(n) {
      if (!evaluate(n.visibleWhen, state)) return null;
      const declared = (SPEC.state || {})[n.bind || ""] || {};
      const p = {
        kind: n.kind, id: n.id || null, label: n.label || null,
        a11y: n.a11yLabel || n.label || null, tone: n.tone || null,
        enabled: evaluate(n.enabledWhen, state),
        focusable: FOCUSABLE.has(n.kind),
        bind: n.bind || null,
        value: n.bind ? resolve(state, n.bind) : null,
        options: declared.options || [],
        rows: n.kind === "list" && n.of
          ? (state.collections[n.of] || []).filter((r) => n.filterWhen ? evaluate(n.filterWhen, state, r) : true)
          : [],
        of: n.of || null, action: n.action || null,
        rowAction: n.rowAction || null, rowLabel: n.rowLabel || null, children: [],
      };
      (n.children || []).forEach((c) => { const g = conv(c); if (g) p.children.push(g); });
      return p;
    }
    const root = { kind: "screen", id: screen.id, label: screen.title || SPEC.title,
                   a11y: screen.title || SPEC.title, tone: null, enabled: true,
                   focusable: false, bind: null, value: null, options: [], rows: [],
                   action: null, children: [] };
    (screen.children || []).forEach((c) => { const g = conv(c); if (g) root.children.push(g); });
    return root;
  }

  function walk(n, out) { out.push(n); (n.children || []).forEach((c) => walk(c, out)); return out; }

  // ---- DOM rendering. Semantic elements throughout, because the accessibility
  // tree is an observable the benchmark reads, not a nicety.
  function el(tag, attrs, kids) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (v === null || v === undefined || v === false) return;
      if (k === "text") e.textContent = v; else e.setAttribute(k, v === true ? "" : String(v));
    });
    (kids || []).forEach((k) => k && e.appendChild(k));
    return e;
  }

  function renderNode(p) {
    const id = p.id || undefined;
    const dis = p.enabled ? null : true;
    switch (p.kind) {
      case "heading": return el("h2", { id, text: p.label || "" });
      case "text": return el("p", { id, text: p.label || "" });
      case "divider": return el("hr", { id });
      case "image": return el("img", { id, alt: p.a11y || "", src: "data:," });
      case "banner":
        return el("div", { id, role: p.tone === "error" ? "alert" : "status",
                           "data-tone": p.tone || "info", text: p.label || "" });
      case "field": {
        const inp = el("input", { id, type: "text", value: p.value == null ? "" : p.value,
                                  disabled: dis, "aria-label": p.a11y || undefined });
        inp.addEventListener("input", () => api.invoke(p.id, inp.value));
        // A <label for> gives the control its accessible name on this host.
        return el("div", {}, [p.label ? el("label", { for: id, text: p.label }) : null, inp]);
      }
      case "select": {
        const sel = el("select", { id, disabled: dis, "aria-label": p.a11y || undefined },
          (p.options || []).map((o) => el("option", { value: o, text: o,
                                                      selected: o === p.value ? true : null })));
        sel.addEventListener("change", () => api.invoke(p.id, sel.value));
        return el("div", {}, [p.label ? el("label", { for: id, text: p.label }) : null, sel]);
      }
      case "toggle": {
        const cb = el("input", { id, type: "checkbox", disabled: dis,
                                 checked: p.value ? true : null,
                                 "aria-label": p.a11y || undefined });
        cb.addEventListener("change", () => api.invoke(p.id, cb.checked));
        return el("div", {}, [cb, p.label ? el("label", { for: id, text: p.label }) : null]);
      }
      case "button": {
        const b = el("button", { id, type: "button", disabled: dis, text: p.label || "" });
        b.addEventListener("click", () => api.invoke(p.id));
        return b;
      }
      case "list": {
        const items = (p.rows || []).map((r, i) => {
          const text = (p.rowLabel ? r[p.rowLabel] : null)
                    || r.title || r.name || r.label || r.subject || r.email || "";
          if (!p.rowAction) return el("li", { text: String(text) });
          const b = el("button", { id: p.id ? p.id + "#" + i : undefined,
                                   type: "button", text: String(text) });
          b.addEventListener("click", () => api.invoke(p.id + "#" + i));
          return el("li", {}, [b]);
        });
        return el("ul", { id, "aria-label": p.a11y || undefined }, items);
      }
      case "dialog":
        return el("dialog", { id, open: true, "aria-label": p.a11y || undefined },
                  p.children.map(renderNode));
      case "tabs":
        return el("div", { id, role: "tablist" }, p.children.map(renderNode));
      case "tab": case "listItem":
        return el("li", { id, text: p.label || "" });
      default:
        return el("div", { id, "data-kind": p.kind }, p.children.map(renderNode));
    }
  }

  function render() {
    const root = document.getElementById("root");
    root.innerHTML = "";
    const proj = project(STATE);
    const main = el("main", { "aria-label": proj.a11y || "" },
                    proj.children.map(renderNode));
    root.appendChild(main);
  }

  // ---- Instrumentation contract -------------------------------------------
  const api = {
    state() { return JSON.parse(JSON.stringify(STATE)); },

    facts() {
      const nodes = walk(project(STATE), []);
      const banners = nodes.filter((n) => n.kind === "banner");
      const f = {
        error_visible: banners.some((n) => n.tone === "error"),
        empty_state_visible: banners.some((n) => n.tone === "empty"),
        enabled: {}, field_values: {}, options: {}, visible_rows: {},
      };
      nodes.forEach((n) => {
        if (n.id && n.focusable) f.enabled[n.id] = n.enabled;
        if (n.id && (n.kind === "field" || n.kind === "select")) f.field_values[n.id] = n.value;
        if (n.id && n.options && n.options.length) f.options[n.id] = n.options;
        if (n.kind === "list") {
          if (n.id) f.visible_rows[n.id] = (n.rows || []).length;
          if (n.of) f.visible_rows[n.of] = (n.rows || []).length;
        }
      });
      return f;
    },

    // Canonical widget tree read from the live DOM, not from the spec. Reading
    // the realized DOM is the point: if the renderer failed to build what the
    // spec asked for, this must show it.
    tree() {
      const LOWER = {
        DIV: "container", SECTION: "container", MAIN: "container", FORM: "container",
        SPAN: "text", P: "text", H1: "text", H2: "text", H3: "text", LABEL: "text",
        TEXTAREA: "input", SELECT: "choice", BUTTON: "action", A: "action",
        UL: "collection", OL: "collection", TABLE: "collection", LI: "item",
        TR: "item", IMG: "media", HR: "separator", DIALOG: "overlay",
      };
      function accName(e) {
        const aria = e.getAttribute && e.getAttribute("aria-label");
        if (aria) return aria;
        if (e.tagName === "IMG") return e.getAttribute("alt") || null;
        if (e.id) {
          const lab = document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
          if (lab) return lab.textContent.trim() || null;
        }
        if (["BUTTON", "P", "H1", "H2", "H3", "LABEL", "LI"].includes(e.tagName)) {
          return (e.textContent || "").trim() || null;
        }
        if (e.getAttribute && e.getAttribute("role")) return (e.textContent || "").trim() || null;
        return null;
      }
      function conv(e) {
        let kind = LOWER[e.tagName] || "container";
        if (e.tagName === "INPUT") {
          const t = (e.getAttribute("type") || "text").toLowerCase();
          kind = t === "checkbox" ? "boolean" : t === "radio" ? "choice" : "input";
        }
        if (e.getAttribute && e.getAttribute("role") === "tablist") kind = "tablist";
        if (e.getAttribute && ["alert", "status"].includes(e.getAttribute("role"))) kind = "status";
        const node = {
          kind, name: accName(e), node_id: e.id || null,
          focusable: ["input", "choice", "boolean", "action"].includes(kind),
          children: [],
        };
        Array.from(e.children).forEach((c) => node.children.push(conv(c)));
        return node;
      }
      return conv(document.querySelector("#root > main"));
    },

    actions() {
      const out = [];
      for (const n of walk(project(STATE), [])) {
        if (n.focusable && n.id) {
          out.push({ id: n.id, kind: n.kind, name: n.a11y || n.label,
                     enabled: n.enabled, value: n.value, options: n.options });
        }
        if (n.kind === "list" && n.rowAction && n.id) {
          (n.rows || []).forEach((r, i) => out.push({
            id: n.id + "#" + i, kind: "listItem",
            name: (n.rowLabel ? String(r[n.rowLabel] ?? "") : "") || null,
            enabled: n.enabled, value: null, options: [],
          }));
        }
      }
      return out;
    },

    invoke(nodeId, value) {
      const nodes = walk(project(STATE), []);
      if (nodeId.indexOf("#") !== -1) {
        const [listId, idx] = nodeId.split("#");
        const lst = nodes.find((n) => n.id === listId && n.kind === "list");
        if (!lst || !lst.rowAction) throw new Error("no tappable list " + listId);
        const row = (lst.rows || [])[Number(idx)];
        if (row === undefined) throw new Error("row out of range " + nodeId);
        if (!lst.enabled) return;
        STATE = applyActions(lst.rowAction, STATE, value, row);
        render();
        return;
      }
      const node = nodes.find((n) => n.id === nodeId);
      if (!node) throw new Error("no such control " + nodeId);
      if (!node.enabled) return;
      if ((node.kind === "field" || node.kind === "select") && node.bind) {
        STATE = applyActions({ op: "set", target: node.bind, value: value }, STATE, value);
      } else if (node.kind === "toggle" && node.bind) {
        STATE = applyActions({ op: "set", target: node.bind,
                               value: value === undefined ? !node.value : !!value }, STATE, value);
      }
      if (node.action) STATE = applyActions(node.action, STATE, value);
      render();
    },

    reset() { STATE = initialState(); render(); },
  };

  window.__hostshift = api;
  document.addEventListener("DOMContentLoaded", render);
  if (document.readyState !== "loading") render();
})();
"""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; margin: 0; padding: 24px; }}
  main {{ max-width: 42rem; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }}
  label {{ display: block; font-size: .875rem; color: #444; }}
  input[type=text], select {{ width: 100%; padding: 8px; font: inherit; }}
  button {{ padding: 8px 14px; font: inherit; cursor: pointer; }}
  button[disabled], input[disabled], select[disabled] {{ opacity: .5; cursor: not-allowed; }}
  [role=alert] {{ color: #b00020; }}
  [data-tone=empty] {{ color: #666; font-style: italic; }}
  ul {{ padding-left: 1.25rem; }}
</style>
</head>
<body>
<div id="root"></div>
<script>window.__HOSTSHIFT_SPEC__ = {spec};</script>
<script>{runtime}</script>
</body>
</html>
"""


class WebRenderer:
    host = "web"

    def emit(self, spec: dict) -> dict[str, str]:
        title = spec.get("title") or "HostShift"
        return {
            "index.html": PAGE.format(
                title=_esc(title),
                spec=json.dumps(spec, separators=(",", ":")),
                runtime=RUNTIME_JS,
            )
        }

    def open(self, spec: dict):
        try:
            return WebSession(spec, self.emit(spec)["index.html"])
        except ImportError as exc:
            raise RenderError(
                "the web host needs Playwright: pip install playwright && playwright install chromium"
            ) from exc


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class WebSession:
    """Device-backed: drives a real browser and reads the realized DOM."""

    simulated = False
    host = "web"

    def __init__(self, spec: dict, html: str):
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page()
        self._page.set_content(html, wait_until="load")
        self._page.wait_for_function("window.__hostshift !== undefined", timeout=5000)

    def widget_tree(self) -> Widget:
        return _to_widget(self._page.evaluate("window.__hostshift.tree()"))

    def state(self) -> dict:
        return self._page.evaluate("window.__hostshift.state()")

    def ui_facts(self) -> dict:
        return self._page.evaluate("window.__hostshift.facts()")

    def actions(self) -> list[dict]:
        return self._page.evaluate("window.__hostshift.actions()")

    def invoke(self, node_id: str, value: object | None = None) -> None:
        self._page.evaluate(
            "([i, v]) => window.__hostshift.invoke(i, v)", [node_id, value])

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()


def _to_widget(d: dict) -> Widget:
    return Widget(
        kind=d.get("kind", "container"),
        name=d.get("name"),
        node_id=d.get("node_id"),
        focusable=bool(d.get("focusable")),
        children=[_to_widget(c) for c in d.get("children") or []],
    )


class SimulatedWebSession(SimulatedSession):
    """Pipeline-only stand-in. See session.assert_measurable."""

    def __init__(self, spec: dict):
        super().__init__(spec, WEB)
