import threading

from supabase import create_client, Client
from app.config import settings


# Per-thread client. The underlying httpx HTTP/2 hpack encoder is not
# thread-safe; FastAPI's sync threadpool was sharing one client across
# threads and corrupting the dynamic header table (RuntimeError: deque
# mutated during iteration → server GOAWAY COMPRESSION_ERROR).
_local = threading.local()


def supabase() -> Client:
    client = getattr(_local, "client", None)
    if client is None:
        url = (settings.SUPABASE_URL or "").strip().strip('"').strip("'")
        key = (settings.SUPABASE_SERVICE_KEY or "").strip().strip('"').strip("'")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        if not key.startswith("eyJ"):
            raise RuntimeError(
                "SUPABASE_SERVICE_KEY does not look like a JWT (should start with 'eyJ'). "
                "Use the legacy service_role key from Project Settings → API."
            )
        client = create_client(url, key)
        _local.client = client
    return client
