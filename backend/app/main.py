from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import settings
from .database import Base, engine
from .deps import verify_admin_basic_auth
from .routers import health, ingest, mobile, servers

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

allowed_hosts = [host.strip() for host in settings.allowed_hosts.split(",") if host.strip()]
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
        if settings.require_admin_auth and (not settings.admin_username.strip() or not settings.admin_password):
            raise RuntimeError("ADMIN_USERNAME and ADMIN_PASSWORD are required in production")
        if "*" in origins:
            raise RuntimeError("CORS_ALLOW_ORIGINS cannot include '*' in production")
        if not allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS must be set in production")

    Base.metadata.create_all(bind=engine)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(verify_admin_basic_auth)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"app_name": settings.app_name},
    )


app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(servers.router)
app.include_router(mobile.router)
