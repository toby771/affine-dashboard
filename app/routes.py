from flask import jsonify, redirect, render_template, request, url_for

from .bittensor_service import Subnet120Manager
from .config import Config
from submissions import SubmissionService


manager = Subnet120Manager(
    netuid=Config.NETUID,
    network=Config.NETWORK,
    cache_seconds=Config.CACHE_SECONDS,
    blocks_per_day=Config.BLOCKS_PER_DAY,
)
submission_service = SubmissionService(
    netuid=Config.NETUID,
    network=Config.NETWORK,
)


def register_routes(app):
    @app.get("/")
    def dashboard():
        error = None
        snapshot = None

        try:
            snapshot = manager.snapshot()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        return render_template(
            "dashboard.html",
            snapshot=snapshot,
            error=error,
            refresh_seconds=Config.REFRESH_SECONDS,
        )

    @app.get("/coldkey/<path:coldkey>")
    def coldkey_detail(coldkey):
        error = None
        snapshot = None
        coldkey_data = None

        try:
            snapshot = manager.snapshot()
            coldkey_data = manager.get_coldkey(coldkey)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        if snapshot is not None and coldkey_data is None and error is None:
            return redirect(url_for("dashboard"))

        return render_template(
            "coldkey.html",
            snapshot=snapshot,
            coldkey=coldkey_data,
            error=error,
            refresh_seconds=Config.REFRESH_SECONDS,
        )

    @app.get("/submissions")
    def submissions():
        selected_coldkeys = list(dict.fromkeys(request.args.getlist("coldkey")))
        error = None
        history = None
        try:
            history = submission_service.history(selected_coldkeys)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        return render_template(
            "submissions.html",
            history=history,
            selected_coldkeys=selected_coldkeys,
            error=error,
            refresh_seconds=Config.REFRESH_SECONDS,
        )

    @app.get("/api/snapshot")
    def api_snapshot():
        force = request.args.get("refresh", "0") == "1"

        try:
            return jsonify(manager.snapshot(force=force))
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }), 503

    @app.get("/api/coldkeys")
    def api_coldkeys():
        try:
            snapshot = manager.snapshot()
            return jsonify({
                "netuid": snapshot["netuid"],
                "block": snapshot["block"],
                "coldkeys": snapshot["coldkeys"],
            })
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }), 503

    @app.get("/api/coldkey/<path:coldkey>")
    def api_coldkey(coldkey):
        try:
            data = manager.get_coldkey(coldkey)
            if data is None:
                return jsonify({"ok": False, "error": "Coldkey not found"}), 404
            return jsonify(data)
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }), 503

    @app.post("/api/refresh")
    def api_refresh():
        try:
            submission_service.clear_cache()
            return jsonify(manager.snapshot(force=True))
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }), 503
