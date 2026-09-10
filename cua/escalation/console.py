"""A minimal operator console (Flask). The UI is intentionally bare -- a real
product would be a co-browsing view -- but the mechanism is real: it reads the
same intervention queue the running automation writes to, and its Resume/Abort
writes the response the automation is blocked on.

While a request is open, the automation has ceded control; the operator works in
the already-open browser window (the same live session) and then clicks Resume.
"""
from __future__ import annotations

import socket as _socket
from pathlib import Path

_socket.getfqdn = lambda *a: "localhost"  # noqa: E731  (see mockapp/__init__.py)

from flask import Flask, abort, redirect, request, send_file, url_for  # noqa: E402

from cua.escalation.intervention import InterventionResponse, Queue  # noqa: E402

_PAGE = """<!doctype html><meta charset=utf-8><title>Operator console</title>
<style>body{{font:14px system-ui;margin:24px;max-width:820px}}
.card{{border:1px solid #bbb;padding:14px;margin:12px 0;border-radius:6px}}
.k{{color:#555}} pre{{background:#f4f4f4;padding:8px;white-space:pre-wrap}}
button{{padding:6px 14px;margin-right:8px}} img{{max-width:100%;border:1px solid #ccc}}</style>
<h1>Operator console</h1>{body}"""


def create_console(queue_dir: str | Path) -> Flask:
    app = Flask(__name__)
    q = Queue(queue_dir)

    @app.get("/")
    def index():
        reqs = q.open_requests()
        if not reqs:
            body = "<p>No open intervention requests. The automation has control.</p>"
        else:
            body = ""
            for r in reqs:
                body += (f'<div class="card"><b>{r.kind}</b> &mdash; {r.reason}<br>'
                         f'<span class="k">capability:</span> {r.capability or "-"} '
                         f'<span class="k">step:</span> {r.step or "-"}<br>'
                         f'<a href="{url_for("detail", rid=r.id)}">open &raquo;</a></div>')
        return _PAGE.format(body=body)

    @app.get("/req/<rid>")
    def detail(rid):
        r = q.get(rid)
        if not r:
            abort(404)
        shot = (f'<img src="{url_for("shot", rid=rid)}">'
                if r.screenshot and Path(r.screenshot).exists() else "")
        body = f"""<div class="card">
        <p><b>{r.kind}</b> &mdash; {r.reason}</p>
        <p class="k">The automation has ceded control. Perform the needed steps in
        the browser window that is already open (same live session), then Resume.</p>
        <pre>{r.ax_digest}</pre>
        <p class="k">url: {r.url}</p>
        {shot}
        <form method="post" action="{url_for('resolve', rid=rid)}">
          <p><label>What you did / decided:<br>
             <textarea name="note" rows="3" cols="80"></textarea></label></p>
          <button name="decision" value="resume">Resume automation</button>
          <button name="decision" value="abort">Abort run</button>
        </form></div>
        <p><a href="{url_for('index')}">&laquo; all requests</a></p>"""
        return _PAGE.format(body=body)

    @app.get("/req/<rid>/screenshot")
    def shot(rid):
        r = q.get(rid)
        if not r or not r.screenshot or not Path(r.screenshot).exists():
            abort(404)
        return send_file(r.screenshot)

    @app.post("/req/<rid>/resolve")
    def resolve(rid):
        if not q.get(rid):
            abort(404)
        q.respond(InterventionResponse(
            id=rid, decision=request.form.get("decision", "resume"),
            note=request.form.get("note", "")))
        return redirect(url_for("index"))

    return app
