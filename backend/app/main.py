from pathlib import Path
import logging
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .database import supabase_admin, supabase_client
from .deps import (
    DASHBOARD_SESSION_COOKIE_NAME,
    authenticate_supabase_password,
    has_valid_dashboard_session,
    verify_admin_basic_auth,
)
from .routers import health, ingest, mobile, servers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

docs_url = "/docs" if settings.api_docs_enabled else None
openapi_url = "/openapi.json" if settings.api_docs_enabled else None
redoc_url = "/redoc" if settings.api_docs_enabled else None

app = FastAPI(title=settings.app_name, docs_url=docs_url, openapi_url=openapi_url, redoc_url=redoc_url)

origins = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
if not origins:
    origins = []

allow_credentials = "*" not in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

configured_allowed_hosts = [host.strip() for host in settings.allowed_hosts.split(",") if host.strip()]
allowed_hosts = list(configured_allowed_hosts)
for internal_host in ("127.0.0.1", "localhost", "backend"):
    if internal_host not in allowed_hosts:
        allowed_hosts.append(internal_host)

if allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response


@app.on_event("startup")
def on_startup() -> None:
    is_production = settings.app_env.strip().lower() == "production"
    if is_production:
        if not settings.ingest_api_token.strip():
            raise RuntimeError("INGEST_API_TOKEN is required in production")
        if settings.require_admin_auth and (not settings.supabase_url.strip() or not settings.supabase_anon_key.strip()):
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required when REQUIRE_ADMIN_AUTH=true")
        if "*" in origins:
            raise RuntimeError("CORS_ALLOW_ORIGINS cannot include '*' in production")
        if not configured_allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS must be set in production")

    if supabase_admin or supabase_client:
        logger.info("✓ Supabase connection configured")
        logger.info("To create tables: Run the SQL from app/schema.sql in your Supabase SQL editor")
    else:
        logger.warning("⚠ Supabase not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env")


@app.get("/sign-in", response_class=HTMLResponse)
def sign_in_page(request: Request):
    if not settings.require_admin_auth:
        return RedirectResponse(url="/", status_code=303)
    if has_valid_dashboard_session(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="sign_in.html",
        context={"app_name": settings.app_name, "error": None},
    )


@app.post("/sign-in", response_class=HTMLResponse)
async def sign_in_submit(request: Request):
    if not settings.require_admin_auth:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    email = str(form.get("email", "")).strip()
    password = str(form.get("password", ""))

    try:
        access_token, expires_in = authenticate_supabase_password(email, password)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=DASHBOARD_SESSION_COOKIE_NAME,
            value=access_token,
            max_age=expires_in,
            httponly=True,
            samesite="lax",
            secure=settings.app_env.strip().lower() == "production",
            path="/",
        )
        return response
    except HTTPException as exc:
        if exc.status_code >= 500:
            message = "Authentication service unavailable. Please try again."
        else:
            message = "Invalid email or password"

    return templates.TemplateResponse(
        request=request,
        name="sign_in.html",
        context={"app_name": settings.app_name, "error": message},
        status_code=401,
    )


@app.post("/sign-out")
def sign_out():
    response = RedirectResponse(url="/sign-in", status_code=303)
    response.delete_cookie(DASHBOARD_SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if settings.require_admin_auth:
        try:
            verify_admin_basic_auth(request_obj=request, authorization=request.headers.get("authorization"))
        except HTTPException:
            return RedirectResponse(url="/sign-in", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"app_name": settings.app_name},
    )


app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(servers.router)
app.include_router(mobile.router)
