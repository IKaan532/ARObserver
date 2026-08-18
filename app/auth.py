import hashlib
import hmac
import logging
import secrets
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 260_000
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 60

UNRESTRICTED_PATHS = {"/login", "/health", "/durum"}
UNRESTRICTED_PREFIXES = ("/socket.io", "/_nicegui")

_failed_attempts: dict[str, list[float]] = {}
_authenticated_session_ids: set[str] = set()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = hashed.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(actual, expected)


def _resolve_admin_password_hash() -> str:
    if settings.admin_password_hash:
        return settings.admin_password_hash
    generated = secrets.token_urlsafe(12)
    logger.warning(
        "ADMIN_PASSWORD_HASH ayarlanmamış! Bu çalıştırma için geçici bir şifre üretildi: %s "
        "(kalıcı olması için `python -m cli.hash_password <şifre>` ile bir hash üretip "
        ".env dosyasına ADMIN_PASSWORD_HASH olarak ekleyin)",
        generated,
    )
    return hash_password(generated)


ADMIN_PASSWORD_HASH = _resolve_admin_password_hash()


def _is_locked_out(key: str) -> bool:
    attempts = [t for t in _failed_attempts.get(key, []) if time.monotonic() - t < LOGIN_LOCKOUT_SECONDS]
    _failed_attempts[key] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def _record_failed_attempt(key: str) -> None:
    _failed_attempts.setdefault(key, []).append(time.monotonic())


def attempt_login(password: str, client_key: str) -> bool:
    if _is_locked_out(client_key):
        return False
    if verify_password(password, ADMIN_PASSWORD_HASH):
        _failed_attempts.pop(client_key, None)
        return True
    _record_failed_attempt(client_key)
    return False


def mark_session_authenticated(session_id: str) -> None:
    _authenticated_session_ids.add(session_id)


def clear_session_authentication(session_id: str) -> None:
    _authenticated_session_ids.discard(session_id)


def _get_or_create_session_id(request: Request) -> str:
    session_id = request.session.get("id")
    if session_id is None:
        session_id = str(uuid.uuid4())
        request.session["id"] = session_id
    return session_id


def _is_session_authenticated(request: Request) -> bool:
    return _get_or_create_session_id(request) in _authenticated_session_ids


def is_safe_redirect_path(path: str) -> bool:
    return path.startswith("/") and not path.startswith("//") and not path.startswith("/\\")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(UNRESTRICTED_PREFIXES) or path in UNRESTRICTED_PATHS:
            return await call_next(request)
        if path.startswith("/api/"):
            if not _is_session_authenticated(request):
                return JSONResponse({"detail": "Kimlik doğrulama gerekli"}, status_code=401)
            return await call_next(request)
        if not _is_session_authenticated(request):
            if is_safe_redirect_path(path):
                request.session["redirect_to"] = path
            return RedirectResponse("/login")
        return await call_next(request)
