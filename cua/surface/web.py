"""The one surface this project implements: a browser, perceived through the
Chrome DevTools Protocol accessibility tree.

Why the a11y tree, not CSS/DOM selectors: the brief's targets are legacy
enterprise apps with no clean DOM, no stable selectors, no test IDs. The a11y
tree (a) exists for them, (b) is close to what a human operator perceives, and
(c) also exists for native desktop apps -- so the same role+name targeting model
carries over. Screenshots + viewport-ratio coordinates are the documented
fallback and where an OCR/vision surface would slot in.

Playwright removed ``page.accessibility`` in 1.55, so we read the tree over CDP
directly (``Accessibility.getFullAXTree``). Acting still goes through Playwright's
ARIA-aware ``get_by_role`` locators.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from playwright.sync_api import Locator, Playwright, sync_playwright

from cua.surface.base import AXNode, LocateResult, Observation
from cua.targeting.selector import (Anchor, BBoxRatio, CellAt, RoleName, Strategy,
                                    TextContains)

# Chrome-internal role -> the role we expose. Anything not here and not below is
# treated as structural and dropped (its text is folded into an ancestor's name).
# LayoutTable* (Chrome's role for a <table> used only for visual layout) is
# deliberately absent -> dropped, so form scaffolding doesn't flood the tree.
_ROLE_MAP = {
    "textbox": "textbox", "button": "button", "link": "link",
    "combobox": "combobox", "listbox": "listbox", "option": "option",
    "checkbox": "checkbox", "radio": "radio", "menuitem": "menuitem",
    "heading": "heading", "alert": "alert", "status": "status",
    "dialog": "dialog", "alertdialog": "alertdialog",
    "cell": "cell", "gridcell": "cell", "columnheader": "columnheader",
    "rowheader": "rowheader", "row": "row", "table": "table", "grid": "table",
}
# roles kept only for structure (anchors / dialog detection), never emitted
_STRUCT_ROLES = {"table", "row"}
_ROW_ROLES = {"row", "LayoutTableRow"}
_CELL_ROLES = {"cell", "gridcell", "columnheader", "rowheader"}
_TEXT_ROLES = {"StaticText"}
_STATE_PROPS = ("focused", "disabled", "checked", "expanded", "required",
                "selected", "invalid")

_BROWSER_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def _find_browser() -> Optional[str]:
    p = os.environ.get("CUA_BROWSER_PATH")
    if p and os.path.exists(p):
        return p
    return next((c for c in _BROWSER_CANDIDATES if os.path.exists(c)), None)


class WebSurface:
    def __init__(self, *, headless: bool = True, viewport: tuple[int, int] = (1280, 800),
                 slow_mo: int = 0) -> None:
        self._pw: Optional[Playwright] = None
        self._headless = headless
        self._viewport = viewport
        self._slow_mo = slow_mo
        self._last_status: Optional[int] = None
        self._start()

    # -- lifecycle -------------------------------------------------------
    def _start(self) -> None:
        self._pw = sync_playwright().start()
        launch_kw = dict(headless=self._headless, slow_mo=self._slow_mo)
        exe = _find_browser()
        if exe:
            launch_kw["executable_path"] = exe
        self.browser = self._pw.chromium.launch(**launch_kw)
        self.context = self.browser.new_context(
            viewport={"width": self._viewport[0], "height": self._viewport[1]})
        self.page = self.context.new_page()
        self.page.on("response", self._on_response)
        self._cdp = self.context.new_cdp_session(self.page)
        self._cdp.send("Accessibility.enable")

    def _on_response(self, response) -> None:
        try:
            req = response.request
            if req.resource_type == "document" and req.is_navigation_request():
                self._last_status = response.status
        except Exception:
            pass

    def close(self) -> None:
        for obj in (getattr(self, "context", None), getattr(self, "browser", None)):
            try:
                obj and obj.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

    # -- perceive -----------------------------------------------------
    def goto(self, url: str) -> None:
        resp = self.page.goto(url, wait_until="domcontentloaded")
        if resp is not None:
            self._last_status = resp.status
        self._settle()

    def current_url(self) -> str:
        return self.page.url

    def _settle(self, timeout_ms: int = 8000) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            pass

    def observe(self) -> Observation:
        raw = self._cdp.send("Accessibility.getFullAXTree").get("nodes", [])
        by_id = {n["nodeId"]: n for n in raw}

        def own_text(n: dict) -> str:
            return (n.get("name", {}) or {}).get("value", "") or ""

        def descendant_text(n: dict, depth: int = 0) -> str:
            parts: list[str] = []
            for cid in n.get("childIds", []):
                c = by_id.get(cid)
                if not c:
                    continue
                if c.get("role", {}).get("value") in _TEXT_ROLES:
                    parts.append(own_text(c))
                elif depth < 6:
                    parts.append(descendant_text(c, depth + 1))
            return " ".join(p for p in parts if p).strip()

        def eff_name(n: dict) -> str:
            return own_text(n).strip() or descendant_text(n)

        nodes: list[AXNode] = []
        dialog: Optional[str] = None

        def child_cells(n: dict) -> list[dict]:
            return [by_id[c] for c in n.get("childIds", [])
                    if by_id.get(c) and by_id[c].get("role", {}).get("value")
                    in _CELL_ROLES]

        def _rows_under(n: dict, depth: int = 0):
            for cid in n.get("childIds", []):
                c = by_id.get(cid)
                if not c:
                    continue
                if c.get("role", {}).get("value") in _ROW_ROLES:
                    yield c
                elif depth < 4:  # descend through implicit rowgroup / tbody
                    yield from _rows_under(c, depth + 1)

        def table_headers(tbl: dict) -> list[str]:
            for row in _rows_under(tbl):
                hs = [eff_name(c) for c in child_cells(row)
                      if c.get("role", {}).get("value") == "columnheader"]
                if hs:
                    return hs
            return []

        def walk(nid: str, row_anchor: Optional[str], headers: list[str],
                 my_column: Optional[str]) -> None:
            nonlocal dialog
            n = by_id.get(nid)
            if not n:
                return
            crole = n.get("role", {}).get("value", "")
            role = _ROLE_MAP.get(crole)
            name = eff_name(n)
            props = {p["name"]: p.get("value", {}).get("value")
                     for p in n.get("properties", [])}

            anchor = row_anchor
            col_of: dict[str, str] = {}
            if role == "table":
                headers = table_headers(n)
            if crole in _ROW_ROLES:
                cells = child_cells(n)
                if cells:
                    anchor = eff_name(cells[0]) or row_anchor
                for i, c in enumerate(cells):
                    if i < len(headers):
                        col_of[c["nodeId"]] = headers[i]

            if role in ("dialog", "alertdialog"):
                dialog = name or "dialog"

            if role and role not in _STRUCT_ROLES and not n.get("ignored"):
                too_long = role in _CELL_ROLES and len(name) > 60
                if name or role in ("textbox", "combobox", "checkbox"):
                    if not too_long:
                        states = tuple(k for k in _STATE_PROPS
                                       if props.get(k) in (True, "true"))
                        nodes.append(AXNode(
                            role=role, name=name,
                            value=(n.get("value", {}) or {}).get("value"),
                            states=states,
                            row_anchor=anchor if role in _CELL_ROLES or role in (
                                "link", "button", "textbox", "combobox") else None,
                            column_header=my_column if role in _CELL_ROLES else None,
                        ))
            for cid in n.get("childIds", []):
                walk(cid, anchor, headers, col_of.get(cid))

        root = next((n["nodeId"] for n in raw
                     if n.get("role", {}).get("value") == "RootWebArea"),
                    raw[0]["nodeId"] if raw else None)
        if root:
            walk(root, None, [], None)

        try:
            body_text = self.page.locator("body").inner_text(timeout=2000)
        except Exception:
            body_text = ""

        return Observation(
            url=self.page.url, title=self.page.title(), nodes=nodes,
            text=body_text, dialog=dialog, viewport=self._viewport,
            http_status=self._last_status,
        )

    def screenshot(self, path: str) -> str:
        self.page.screenshot(path=path, full_page=True)
        return path

    def side_effect_get(self, url: str) -> None:
        """Issue a GET that shares the session cookie but does NOT navigate.
        Used only by the replay CLI's failure-injection hook."""
        try:
            self.page.request.get(url, timeout=5000)
        except Exception:
            pass

    # -- locate -----------------------------------------------------
    def locate(self, strategy: Strategy, obs: Observation) -> LocateResult:
        if isinstance(strategy, RoleName):
            return self._finalize(
                self.page.get_by_role(strategy.role, name=strategy.name,
                                      exact=strategy.exact),
                strategy, strategy.nth)
        if isinstance(strategy, CellAt):
            return self._locate_cell_at(strategy)
        if isinstance(strategy, Anchor):
            return self._locate_anchor(strategy)
        if isinstance(strategy, TextContains):
            if strategy.role:
                loc = self.page.get_by_role(strategy.role).filter(
                    has_text=re.compile(re.escape(strategy.text), re.I))
            else:
                loc = self.page.get_by_text(strategy.text, exact=False)
            return self._finalize(loc, strategy)
        if isinstance(strategy, BBoxRatio):
            return LocateResult(status="unique", strategy=strategy,
                                handle=("point", strategy.x, strategy.y), count=1)
        return LocateResult(status="missing", strategy=strategy)

    def _finalize(self, loc: Locator, strategy: Strategy, nth: int = 0) -> LocateResult:
        try:
            count = loc.count()
        except Exception:
            return LocateResult(status="missing", strategy=strategy, count=0)
        if count == 0:
            return LocateResult(status="missing", strategy=strategy, count=0)
        if count == 1:
            return LocateResult(status="unique", strategy=strategy,
                                handle=loc.first, count=1)
        if 0 <= nth < count:
            return LocateResult(status="unique", strategy=strategy,
                                handle=loc.nth(nth), count=count)
        return LocateResult(status="ambiguous", strategy=strategy, count=count)

    def _locate_cell_at(self, s: CellAt) -> LocateResult:
        """Address a data-grid cell by (row anchor x column header) -- the most
        robust way to read a value out of a legacy table."""
        rx_col = re.compile(re.escape(s.column_header), re.I)
        rx_row = re.compile(re.escape(s.row_anchor), re.I)
        for ti in range(self.page.get_by_role("table").count()):
            tbl = self.page.get_by_role("table").nth(ti)
            heads = tbl.get_by_role("columnheader")
            idx = next((i for i in range(heads.count())
                        if rx_col.search(heads.nth(i).inner_text() or "")), None)
            if idx is None:
                continue
            rows = tbl.get_by_role("row")
            for ri in range(rows.count()):
                cells = rows.nth(ri).get_by_role("cell")
                cn = cells.count()
                if cn == 0:
                    continue
                if rx_row.search(cells.nth(0).inner_text() or "") and idx < cn:
                    target = cells.nth(idx)
                    if s.contains and s.contains not in (target.inner_text() or ""):
                        continue
                    return LocateResult(status="unique", strategy=s,
                                        handle=target, count=1)
        return LocateResult(status="missing", strategy=s, count=0)

    def _locate_anchor(self, s: Anchor) -> LocateResult:
        label = self.page.locator(
            "label", has_text=re.compile(re.escape(s.anchor_text), re.I))
        try:
            if label.count() >= 1:
                for_id = label.first.get_attribute("for")
                if for_id:
                    r = self._finalize(self.page.locator(f"#{for_id}"), s)
                    if r.status == "unique":
                        return r
        except Exception:
            pass
        anchor_el = self.page.get_by_text(s.anchor_text, exact=False)
        for xp in ("xpath=ancestor::tr[1]",
                   "xpath=ancestor::*[contains(@class,'fld')][1]", "xpath=.."):
            try:
                if anchor_el.count() == 0:
                    break
                scope = anchor_el.first.locator(xp)
                loc = scope.get_by_role(s.control_role)
                r = self._finalize(loc, s)
                if r.status == "unique":
                    return r
            except Exception:
                continue
        return LocateResult(status="missing", strategy=s, count=0)

    # -- act -------------------------------------------------------
    def click(self, handle: object) -> None:
        if isinstance(handle, tuple) and handle and handle[0] == "point":
            self.click_point(handle[1], handle[2])
            return
        handle.click(timeout=6000)
        self._settle()

    def fill(self, handle: object, text: str) -> None:
        handle.fill(text, timeout=6000)

    def select_option(self, handle: object, value: str) -> None:
        try:
            handle.select_option(label=value, timeout=6000)
        except Exception:
            handle.select_option(value=value, timeout=6000)

    def read(self, handle: object) -> str:
        try:
            tag = (handle.evaluate("el => el.tagName") or "").lower()
        except Exception:
            tag = ""
        if tag in ("input", "select", "textarea"):
            try:
                return (handle.input_value(timeout=4000) or "").strip()
            except Exception:
                pass
        return (handle.inner_text(timeout=4000) or "").strip()

    def press_key(self, key: str) -> None:
        self.page.keyboard.press(key)
        self._settle()

    def click_point(self, x_ratio: float, y_ratio: float) -> None:
        w, h = self._viewport
        self.page.mouse.click(x_ratio * w, y_ratio * h)
        self._settle()
