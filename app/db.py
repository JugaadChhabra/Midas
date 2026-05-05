from supabase import create_client, Client
from app.config import settings


_client: Client | None = None


def supabase() -> Client:
    global _client
    if _client is None:
        url = (settings.SUPABASE_URL or "").strip().strip('"').strip("'")
        key = (settings.SUPABASE_SERVICE_KEY or "").strip().strip('"').strip("'")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        if not key.startswith("eyJ"):
            raise RuntimeError(
                "SUPABASE_SERVICE_KEY does not look like a JWT (should start with 'eyJ'). "
                "Use the legacy service_role key from Project Settings → API."
            )
        _client = create_client(url, key)
    return _client
