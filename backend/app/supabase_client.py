import logging
from supabase import create_client
from .config import settings

logger = logging.getLogger(__name__)

# Initialize Supabase client with anon key for user operations
if settings.supabase_url and settings.supabase_anon_key:
    supabase = create_client(settings.supabase_url, settings.supabase_anon_key)
    logger.info(f"✓ Successfully initialized Supabase client at {settings.supabase_url}")
else:
    supabase = None
    logger.error("Supabase credentials not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY")

# Admin client with service role key for backend operations
supabase_admin = None
if settings.supabase_url and settings.supabase_service_role_key:
    supabase_admin = create_client(settings.supabase_url, settings.supabase_service_role_key)
    logger.info("✓ Supabase admin client initialized")
else:
    logger.warning("Supabase service role key not configured - admin operations will be limited")
