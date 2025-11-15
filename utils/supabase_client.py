from supabase import create_client, Client
import os

# Global client instance
_supabase_client: Client = None

def get_client() -> Client:
    """Get or create Supabase client instance (lazy initialization)."""
    global _supabase_client
    
    if _supabase_client is not None:
        return _supabase_client
    
    url: str = os.environ.get("SUPABASE_URL")
    # Check for both SUPABASE_SERVICE_ROLE_KEY and SUPABASE_ANON_KEY
    # Service role key is preferred for admin operations, but anon key works for auth
    key: str = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") 
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_KEY")
    )

    if not url or not key:
        raise ValueError(
            "Supabase credentials not found. Please set SUPABASE_URL and "
            "either SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY in your environment variables."
        )

    _supabase_client = create_client(url, key)
    return _supabase_client

# For backwards compatibility, create a proxy object
class _SupabaseProxy:
    """Proxy object that lazily initializes Supabase client on attribute access."""
    def __getattr__(self, name):
        return getattr(get_client(), name)
    
    def __call__(self, *args, **kwargs):
        return get_client()(*args, **kwargs)

supabase = _SupabaseProxy()