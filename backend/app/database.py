import logging
from supabase import create_client, Client

from .config import settings

logger = logging.getLogger(__name__)

# Dummy Base class for model compatibility
# Since we're using Supabase REST API, we don't need SQLAlchemy ORM
class Base:
    """Dummy base class for model definitions. Not used with Supabase REST API."""
    pass

# Initialize Supabase clients
supabase_client: Client = None
supabase_admin: Client = None

if settings.supabase_url and settings.supabase_anon_key:
    supabase_client = create_client(settings.supabase_url, settings.supabase_anon_key)
    logger.info(f"✓ Supabase client initialized with anon key")
else:
    logger.error("SUPABASE_URL and SUPABASE_ANON_KEY are required")

if settings.supabase_url and settings.supabase_service_role_key:
    supabase_admin = create_client(settings.supabase_url, settings.supabase_service_role_key)
    logger.info("✓ Supabase admin client initialized with service role key")
else:
    logger.warning("SUPABASE_SERVICE_ROLE_KEY not configured - some operations may fail or have RLS restrictions")

# For compatibility with existing code that expects a database session
class SupabaseSession:
    """Wrapper around Supabase client to provide session-like interface"""
    def __init__(self, client: Client):
        self.client = client
    
    def close(self):
        pass

def get_db():
    """Get Supabase client session for use in dependencies"""
    if supabase_admin:
        yield SupabaseSession(supabase_admin)
    elif supabase_client:
        yield SupabaseSession(supabase_client)
    else:
        yield None
