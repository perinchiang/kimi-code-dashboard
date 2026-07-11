"""System routes: Kimi Web launch, health, and index page."""

import subprocess

from flask import Blueprint, jsonify, render_template

from config import (
    KIMI_WEB_ALLOWED_HOSTS,
    KIMI_WEB_BYPASS_AUTH,
    KIMI_WEB_HOST,
    KIMI_WEB_KEEP_ALIVE,
    KIMI_WEB_PORT,
    KIMI_WEB_PUBLIC_URL,
    log,
)
from services.helpers import tcp_open

bp = Blueprint("system", __name__)


def _kimi_web_url():
    """Return the URL shown to Pat for the Kimi Web UI."""
    if KIMI_WEB_PUBLIC_URL:
        return KIMI_WEB_PUBLIC_URL
    if KIMI_WEB_HOST == "0.0.0.0":
        return f"http://127.0.0.1:{KIMI_WEB_PORT}"
    return f"http://{KIMI_WEB_HOST}:{KIMI_WEB_PORT}"


@bp.route("/api/kimi-web-status")
def api_kimi_web_status():
    running = tcp_open("127.0.0.1", KIMI_WEB_PORT)
    return jsonify({
        "running": running,
        "port": KIMI_WEB_PORT,
        "url": _kimi_web_url(),
    })


@bp.route("/api/launch-kimi-web", methods=["POST"])
def api_launch_kimi_web():
    """POST-only: launch `kimi server run` with Pat's preferred flags."""
    if tcp_open("127.0.0.1", KIMI_WEB_PORT):
        return jsonify({
            "status": "already_running",
            "port": KIMI_WEB_PORT,
            "url": _kimi_web_url(),
        })
    try:
        cmd = [
            "kimi", "server", "run",
            "--host", KIMI_WEB_HOST,
            "--port", str(KIMI_WEB_PORT),
        ]
        if KIMI_WEB_KEEP_ALIVE:
            cmd.append("--keep-alive")
        if KIMI_WEB_BYPASS_AUTH:
            cmd.append("--dangerous-bypass-auth")
        for host in KIMI_WEB_ALLOWED_HOSTS:
            cmd.extend(["--allowed-host", host])

        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(cmd, **kwargs)
        log.info("Launched Kimi Web: %s", " ".join(cmd))
        return jsonify({
            "status": "launched",
            "port": KIMI_WEB_PORT,
            "url": _kimi_web_url(),
        })
    except Exception as e:
        log.error("Failed to launch kimi web: %s", e)
        return jsonify({"status": "error", "error": str(e)})


@bp.route("/")
def index():
    return render_template("index.html")
