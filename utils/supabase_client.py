from supabase import create_client, Client
import os

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
        "either SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY in your .env file."
    )

supabase: Client = create_client(url, key)