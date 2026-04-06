from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from urllib.parse import quote, unquote

from .config import settings


def _normalize_database_url(url: str) -> str:
    """Normalize DB URL by safely URL-encoding password special characters."""
    if not url:
        return url

    prefixes = ("postgresql://", "postgresql+psycopg2://")
    if not url.startswith(prefixes):
        return url

    scheme, rest = url.split("://", 1)
    if "/" in rest:
        netloc, suffix = rest.split("/", 1)
        suffix = "/" + suffix
    else:
        netloc, suffix = rest, ""

    if "@" not in netloc or ":" not in netloc.split("@", 1)[0]:
        return url

    userinfo, hostport = netloc.rsplit("@", 1)
    username, raw_password = userinfo.split(":", 1)
    normalized_password = quote(unquote(raw_password), safe="")
    return f"{scheme}://{username}:{normalized_password}@{hostport}{suffix}"


database_url = settings.supabase_db_url.strip() or settings.database_url.strip()
database_url = _normalize_database_url(database_url)
if not database_url:
    raise RuntimeError("Missing DB config. Set SUPABASE_DB_URL (recommended) or DATABASE_URL.")

connect_args = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
