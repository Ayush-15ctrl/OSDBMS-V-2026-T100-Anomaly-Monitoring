"""Serves the static pages in web/ (offline, no CDN)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Blueprint, send_from_directory

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"
web_blueprint = Blueprint("web", __name__)


@web_blueprint.get("/ui/")
def ui_home() -> Any:
    return send_from_directory(WEB_ROOT, "index.html")


@web_blueprint.get("/ui/exam")
def ui_exam() -> Any:
    return send_from_directory(WEB_ROOT / "exam", "index.html")


@web_blueprint.get("/ui/admin")
def ui_admin() -> Any:
    return send_from_directory(WEB_ROOT / "admin", "index.html")


@web_blueprint.get("/ui/proctor")
def ui_proctor() -> Any:
    return send_from_directory(WEB_ROOT / "proctor", "index.html")


@web_blueprint.get("/ui/ops")
def ui_ops() -> Any:
    return send_from_directory(WEB_ROOT / "ops", "index.html")


@web_blueprint.get("/ui/<path:filename>")
def ui_asset(filename: str) -> Any:
    # send_from_directory rejects paths that escape WEB_ROOT.
    return send_from_directory(WEB_ROOT, filename)
