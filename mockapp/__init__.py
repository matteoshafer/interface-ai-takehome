"""A deliberately legacy-styled mock credit-union back-office admin app.

This stands in for the "core banking / servicing console with no API" that the
real system targets. Design choices that matter for the exercise:

* Server-rendered, full page reload per step, ``<form method=post>`` -- no SPA.
* Table-based layout, generic class names, **no** ``data-testid`` / stable ids.
* BUT real accessible labels (``<label for>``, ``<th>``, headings) so the
  accessibility-tree surface is viable. ``?hostile=1`` strips the labels to
  force the screenshot fallback path (documented simplification).
* Injectable runtime conditions via ``?inject=`` so replay can be exercised
  against the exceptional states that actually occur in production.
* A second "tenant" (``?tenant=west``) re-brands, relabels the member field and
  adds one extra interstitial -- a stand-in for two institutions running the
  same vendor product.
"""
from __future__ import annotations

import socket as _socket
import time

# On some macOS setups reverse-DNS on the bind address hangs for ~minutes inside
# werkzeug's server startup. This is a throwaway local mock; short-circuit it.
_socket.getfqdn = lambda *a: "localhost"  # noqa: E731

from flask import (Flask, abort, redirect, render_template, request, session,  # noqa: E402
                   url_for)

from . import data

INJECTS = {"slow", "timeout", "dialog", "error", "permission"}

TENANTS = {
    "core": {"brand": "MeridianCU CoreAdmin", "member_label": "Member ID",
             "extra_branch_step": False},
    "west": {"brand": "Westland FCU ServiceDesk", "member_label": "Account Holder #",
             "extra_branch_step": True},
}


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "mock-app-not-a-secret"  # noqa: S105 -- local mock only

    # ---- helpers -----------------------------------------------------------
    def tenant() -> str:
        t = request.args.get("tenant") or session.get("tenant") or "core"
        return t if t in TENANTS else "core"

    def tconf() -> dict:
        return TENANTS[tenant()]

    def hostile() -> bool:
        return request.args.get("hostile") == "1" or session.get("hostile")

    @app.context_processor
    def inject_globals() -> dict:
        return {"t": tconf(), "tenant_name": tenant(), "hostile": hostile()}

    @app.before_request
    def carry_flags() -> None:
        # Sticky across the flow so the agent/replay doesn't have to re-thread them.
        if request.args.get("tenant") in TENANTS:
            session["tenant"] = request.args["tenant"]
        if request.args.get("hostile") == "1":
            session["hostile"] = True

    def check_inject() -> object | None:
        """Apply a requested runtime condition. Returns a response to short-circuit
        with, or None to proceed normally.

        The condition can come from ``?inject=`` on this request or from a
        one-shot flag armed earlier via ``/_inject/<cond>`` (consumed here) --
        the latter lets a replay inject a failure into a specific downstream
        screen without altering the recorded step's URL.
        """
        inj = request.args.get("inject") or session.pop("inject_once", None)
        if inj not in INJECTS:
            return None
        if inj == "slow":
            time.sleep(2.5)
            return None  # proceeds, just late
        if inj == "timeout":
            session.pop("operator", None)
            return redirect(url_for("login", expired=1))
        if inj == "error":
            abort(500)
        if inj == "dialog":
            request.environ["cua.dialog"] = True  # template renders the interstitial
            return None
        if inj == "permission":
            return render_template("denied.html", reason="forced"), 403
        return None

    def logged_in() -> bool:
        return bool(session.get("operator"))

    # ---- auth ------------------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if request.form.get("username") and request.form.get("password"):
                session["operator"] = request.form["username"]
                return redirect(url_for("home"))
            return render_template("login.html", error="Enter a username and password.")
        return render_template("login.html", expired=request.args.get("expired"))

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/_inject/<cond>")
    def arm_inject(cond: str):
        """Test hook: arm a one-shot runtime condition for the next screen."""
        if cond == "off":
            session.pop("inject_once", None)
        elif cond in INJECTS:
            session["inject_once"] = cond
        return {"armed": session.get("inject_once")}, 200

    # ---- home / search -------------------------------------------------
    @app.route("/")
    def home():
        if (r := check_inject()) is not None:
            return r
        if not logged_in():
            return redirect(url_for("login", expired=1))
        return render_template("home.html")

    @app.route("/members")
    def members():
        if (r := check_inject()) is not None:
            return r
        if not logged_in():
            return redirect(url_for("login", expired=1))
        q = request.args.get("q", "")
        results = data.search(q)
        return render_template("members.html", q=q, results=results,
                               dialog=request.environ.get("cua.dialog"))

    # ---- member detail ------------------------------------------------
    @app.route("/member/<member_id>")
    def member_detail(member_id: str):
        if (r := check_inject()) is not None:
            return r
        if not logged_in():
            return redirect(url_for("login", expired=1))
        m = data.get(member_id)
        if m is None:
            return render_template("member_missing.html", member_id=member_id), 404
        if m.restricted:
            return render_template("denied.html", reason="restricted",
                                   member_id=member_id), 403
        return render_template("member_detail.html", m=m,
                               dialog=request.environ.get("cua.dialog"))

    # ---- open a sub-account (multi-step, has a confirmation) ----------
    @app.route("/member/<member_id>/subaccount/new", methods=["GET", "POST"])
    def subaccount_new(member_id: str):
        if (r := check_inject()) is not None:
            return r
        if not logged_in():
            return redirect(url_for("login", expired=1))
        m = data.get(member_id)
        if m is None:
            return render_template("member_missing.html", member_id=member_id), 404
        if m.restricted:
            return render_template("denied.html", reason="restricted",
                                   member_id=member_id), 403

        if request.method == "POST":
            kind = request.form.get("kind", "")
            deposit_raw = request.form.get("deposit", "").strip()
            errors = []
            if kind not in ("Savings", "Checking", "Money Market"):
                errors.append("Select an account type.")
            try:
                deposit = float(deposit_raw)
                if deposit < 25:
                    errors.append("Opening deposit must be at least $25.00.")
            except ValueError:
                deposit = 0.0
                errors.append("Opening deposit must be a dollar amount.")
            if errors:
                return render_template("subaccount_new.html", m=m, errors=errors,
                                       kind=kind, deposit=deposit_raw)

            # west tenant inserts a branch-selection interstitial before confirm
            if tconf()["extra_branch_step"] and not request.form.get("branch"):
                return render_template("subaccount_branch.html", m=m, kind=kind,
                                       deposit=f"{deposit:.2f}")

            return render_template(
                "subaccount_confirm.html", m=m, kind=kind, deposit=deposit,
                new_number=data.new_subaccount_number(member_id, kind),
                branch=request.form.get("branch"))

        return render_template("subaccount_new.html", m=m, errors=[], kind="",
                               deposit="")

    @app.route("/member/<member_id>/subaccount/create", methods=["POST"])
    def subaccount_create(member_id: str):
        """The risky / irreversible step: actually opens the sub-account."""
        if (r := check_inject()) is not None:
            return r
        if not logged_in():
            return redirect(url_for("login", expired=1))
        m = data.get(member_id)
        if m is None:
            return render_template("member_missing.html", member_id=member_id), 404
        kind = request.form.get("kind", "Savings")
        return render_template(
            "subaccount_done.html", m=m, kind=kind,
            new_number=data.new_subaccount_number(member_id, kind),
            deposit=request.form.get("deposit", "0"))

    # ---- error pages -------------------------------------------------
    @app.errorhandler(500)
    def err_500(_e):
        return render_template("error.html"), 500

    @app.errorhandler(404)
    def err_404(_e):
        return render_template("error.html", not_found=True), 404

    return app
