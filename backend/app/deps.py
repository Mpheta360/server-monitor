import json
from dataclasses import dataclass
from urllib import error, request

from fastapi import Header, HTTPException, Request, status

from .config import settings

DASHBOARD_SESSION_COOKIE_NAME = "monitor_supabase_session"


def _supabase_auth_config() -> tuple[str, str]:
    supabase_url = settings.supabase_url.strip().rstrip("/")
    anon_key = settings.supabase_anon_key.strip()
    if not supabase_url or not anon_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase authentication is not configured",
        )
    return supabase_url, anon_key


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


def _extract_dashboard_token(request_obj: Request, authorization: str | None) -> str:
    if authorization and authorization.strip():
        return _extract_bearer_token(authorization)

    cookie_token = request_obj.cookies.get(DASHBOARD_SESSION_COOKIE_NAME, "").strip()
    if cookie_token:
        return cookie_token

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def _verify_with_supabase(token: str) -> AuthenticatedUser:
    supabase_url, anon_key = _supabase_auth_config()

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


def authenticate_supabase_password(email: str, password: str) -> tuple[str, int]:
    if not email.strip() or not password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email and password are required")

    supabase_url, anon_key = _supabase_auth_config()
    body = json.dumps({"email": email.strip(), "password": password}).encode("utf-8")
    url = f"{supabase_url}/auth/v1/token?grant_type=password"
    req = request.Request(
        url,
        method="POST",
        data=body,
        headers={
            "apikey": anon_key,
            "Content-Type": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=settings.supabase_auth_timeout_seconds) as resp:
            raw_body = resp.read().decode("utf-8")
            if resp.status != 200:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    except error.HTTPError as exc:
        if exc.code in (400, 401, 403, 422):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
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
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Invalid response from Supabase") from exc

    access_token = str(payload.get("access_token", "")).strip()
    expires_in = int(payload.get("expires_in") or 3600)
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return access_token, max(expires_in, 1)


def has_valid_dashboard_session(request_obj: Request) -> bool:
    token = request_obj.cookies.get(DASHBOARD_SESSION_COOKIE_NAME, "").strip()
    if not token:
        return False
    try:
        _verify_with_supabase(token)
        return True
    except HTTPException:
        return False


def require_dashboard_user(request_obj: Request, authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if not settings.require_admin_auth:
        return AuthenticatedUser(id="local-dev", email=None, role="admin")
    token = _extract_dashboard_token(request_obj, authorization)
    return _verify_with_supabase(token)


def verify_admin_basic_auth(request_obj: Request, authorization: str | None = Header(default=None)) -> None:
    # Kept for backward compatibility with existing routers.
    require_dashboard_user(request_obj, authorization)


def require_supabase_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    token = _extract_bearer_token(authorization)
    return _verify_with_supabase(token)
