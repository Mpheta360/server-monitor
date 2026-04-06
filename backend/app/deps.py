import json
from base64 import b64decode
from dataclasses import dataclass
from hmac import compare_digest
from urllib import error, request

from fastapi import Header, HTTPException, status

from .config import settings


def verify_ingest_token(authorization: str | None = Header(default=None)) -> None:
    expected = settings.ingest_api_token.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingest authentication is not configured",
        )

    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    scheme, _, provided = authorization.partition(" ")
    if scheme.lower() != "bearer" or provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ingest token")


def verify_admin_basic_auth(authorization: str | None = Header(default=None)) -> None:
    if not settings.require_admin_auth:
        return

    username = settings.admin_username.strip()
    password = settings.admin_password
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Admin authentication is not configured",
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Basic realm=monitor-admin"},
        )

    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Basic realm=monitor-admin"},
        )

    try:
        decoded = b64decode(encoded).decode("utf-8")
        provided_user, provided_pass = decoded.split(":", 1)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid basic auth credentials",
            headers={"WWW-Authenticate": "Basic realm=monitor-admin"},
        ) from exc

    is_valid = compare_digest(provided_user, username) and compare_digest(provided_pass, password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin username or password",
            headers={"WWW-Authenticate": "Basic realm=monitor-admin"},
        )


@dataclass
class AuthenticatedUser:
    id: str
    email: str | None
    role: str | None


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Authorization header format")
    return token.strip()


def _verify_with_supabase(token: str) -> AuthenticatedUser:
    supabase_url = settings.supabase_url.strip().rstrip("/")
    anon_key = settings.supabase_anon_key.strip()
    if not supabase_url or not anon_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase authentication is not configured",
        )

    url = f"{supabase_url}/auth/v1/user"
    req = request.Request(
        url,
        method="GET",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {token}",
        },
    )

    try:
        with request.urlopen(req, timeout=settings.supabase_auth_timeout_seconds) as resp:
            raw_body = resp.read().decode("utf-8")
            if resp.status != 200:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")
    except error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase authentication service unavailable",
        ) from exc
    except (error.URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach Supabase authentication service",
        ) from exc

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload from auth provider") from exc

    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Supabase user payload")

    app_metadata = payload.get("app_metadata") or {}
    return AuthenticatedUser(
        id=user_id,
        email=payload.get("email"),
        role=app_metadata.get("role") or payload.get("role"),
    )


def require_supabase_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    token = _extract_bearer_token(authorization)
    return _verify_with_supabase(token)
