"""Feature-gated role authentication using timed signed bearer tokens."""

import json
from collections.abc import Callable, Iterable, Mapping
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from flask import Flask, current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


Handler = TypeVar("Handler", bound=Callable[..., Any])
ROLES = frozenset({"student", "proctor", "admin"})
ACCESS_TOKEN_MAX_AGE = 3600
STREAM_TOKEN_MAX_AGE = 60
_TOKEN_SALT = "bams-access-control-v1"


def access_control_enabled() -> bool:
    """Return whether role checks are enabled for the current application."""
    return bool(current_app.config.get("PHASE3_ACCESS_CONTROL", False))


def access_control_label() -> str:
    """Return the response/UI label for the current access-control mode."""
    return (
        "ENABLED (Phase 3)"
        if access_control_enabled()
        else "NOT ENABLED (Phase 3)"
    )


def access_control_status(enabled: bool | None = None) -> str:
    """Return the UI-visible access-control status."""
    if enabled is None:
        enabled = access_control_enabled()
    label = "ENABLED (Phase 3)" if enabled else "NOT ENABLED (Phase 3)"
    return f"ACCESS CONTROL {label}"


def initialize_access_control(app: Flask) -> None:
    """Load credentials and signing configuration when the feature is enabled."""
    if not app.config["PHASE3_ACCESS_CONTROL"]:
        app.extensions["bams_users"] = {}
        return

    users_file = app.config.get("BAMS_USERS_FILE")
    secret = app.config.get("BAMS_AUTH_SECRET")
    if not users_file:
        raise RuntimeError(
            "BAMS_USERS_FILE must point to an external user table when "
            "BAMS_ACCESS_CONTROL=1"
        )
    if not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError(
            "BAMS_AUTH_SECRET must contain at least 32 characters when "
            "BAMS_ACCESS_CONTROL=1"
        )

    path = Path(users_file)
    try:
        contents = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"could not load BAMS user table: {path}") from error

    rows = contents.get("users") if isinstance(contents, Mapping) else None
    if not isinstance(rows, list):
        raise RuntimeError("BAMS user table must contain a 'users' list")

    users: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise RuntimeError("each BAMS user must be a JSON object")
        username = row.get("username")
        password_hash = row.get("password_hash")
        role = row.get("role")
        student_id = row.get("student_id")
        if (
            not isinstance(username, str)
            or not username
            or username in users
            or not isinstance(password_hash, str)
            or not password_hash
            or not isinstance(role, str)
            or role not in ROLES
            or (
                role == "student"
                and (
                    type(student_id) is not int
                    or student_id <= 0
                )
            )
        ):
            raise RuntimeError(
                "BAMS users require unique usernames, password_hash values, "
                "a valid role, and a positive student_id for students"
            )
        users[username] = {
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "student_id": student_id if role == "student" else None,
        }

    app.extensions["bams_users"] = users
    app.extensions["bams_auth_serializer"] = URLSafeTimedSerializer(
        secret, salt=_TOKEN_SALT
    )


def issue_token(identity: Mapping[str, Any], *, stream: bool = False) -> str:
    """Sign an access or short-lived EventSource token."""
    payload = {
        "sub": identity.get("username", identity.get("sub")),
        "role": identity["role"],
    }
    if identity.get("student_id") is not None:
        payload["student_id"] = identity["student_id"]
    if stream:
        payload["scope"] = "stream"
    return current_app.extensions["bams_auth_serializer"].dumps(payload)


def authenticated_identity() -> Mapping[str, Any] | None:
    """Return the verified identity attached by the role decorator."""
    return getattr(g, "bams_identity", None)


def student_owns_resource(student_id: int) -> bool:
    """Check that the authenticated student owns the requested resource."""
    if not access_control_enabled():
        return True
    identity = authenticated_identity()
    return (
        identity is not None
        and identity.get("role") == "student"
        and identity.get("student_id") == student_id
    )


def _request_token(allow_stream_query: bool) -> tuple[str | None, bool]:
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return authorization[7:].strip(), False
    if allow_stream_query:
        return request.args.get("token"), True
    return None, False


def _load_identity(token: str, *, stream_query: bool) -> Mapping[str, Any] | None:
    serializer = current_app.extensions["bams_auth_serializer"]
    max_age = STREAM_TOKEN_MAX_AGE if stream_query else ACCESS_TOKEN_MAX_AGE
    try:
        payload = serializer.loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, Mapping):
        return None
    username = payload.get("sub")
    role = payload.get("role")
    if (
        not isinstance(username, str)
        or not isinstance(role, str)
        or role not in ROLES
        or username not in current_app.extensions["bams_users"]
        or current_app.extensions["bams_users"][username]["role"] != role
        or (
            role == "student"
            and payload.get("student_id")
            != current_app.extensions["bams_users"][username]["student_id"]
        )
    ):
        return None
    if stream_query and payload.get("scope") != "stream":
        return None
    if not stream_query and payload.get("scope") is not None:
        return None
    return payload


def authentication_error(message: str, status: int) -> tuple[Any, int]:
    """Build the standard enabled-mode authentication error response."""
    return jsonify({
        "error": message,
        "access_control": access_control_label(),
    }), status


def requires_role(
    role: str | Iterable[str],
    *,
    allow_stream_query: bool = False,
) -> Callable[[Handler], Handler]:
    """Require one of the specified roles only when access control is enabled."""
    allowed_roles = {role} if isinstance(role, str) else set(role)
    if not allowed_roles or not allowed_roles <= ROLES:
        raise ValueError("requires_role expects one or more valid BAMS roles")

    def decorator(handler: Handler) -> Handler:
        @wraps(handler)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            if not access_control_enabled():
                return handler(*args, **kwargs)

            token, from_query = _request_token(allow_stream_query)
            if not token:
                return authentication_error("authentication required", 401)
            identity = _load_identity(token, stream_query=from_query)
            if identity is None:
                return authentication_error("invalid or expired token", 401)
            if identity["role"] not in allowed_roles:
                return authentication_error("insufficient role", 403)
            g.bams_identity = identity
            return handler(*args, **kwargs)

        return guarded  # type: ignore[return-value]

    return decorator
