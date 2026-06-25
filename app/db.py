import logging
import threading

import httpx
from postgrest._sync.request_builder import SyncQueryRequestBuilder
from supabase import create_client, Client

from app.config import settings

log = logging.getLogger("midas.db")


# Per-thread client. The default supabase httpx client used HTTP/2 with a
# shared dynamic-table encoder that was not thread-safe (caused intermittent
# 500s under concurrent load — RuntimeError: deque mutated during iteration
# → server GOAWAY COMPRESSION_ERROR). Even after thread isolation, HTTP/2
# kept idle connections open long enough for the server / NAT to silently
# drop them, surfacing as ReadTimeout on the next request.
#
# Fix:
#  - per-thread clients (no shared state)
#  - force HTTP/1.1
#  - short keepalive so dead connections get reaped before reuse
#  - transport-level retries for ConnectError (stale-socket detection)
#  - explicit retry wrapper around postgrest .execute() for ReadTimeouts,
#    where the request was sent but the server never replied (typical when
#    Supabase's edge proxy half-closed an idle socket between our send
#    and its parser)
_local = threading.local()
_local_lock = threading.Lock()  # guards reset of dead per-thread clients

# How long an idle connection stays in the pool before we recycle it.
# Supabase's edge appears to drop idle keepalive sockets aggressively;
# 5s is empirically below that threshold.
_KEEPALIVE_EXPIRY_SECONDS = 5.0
_REQUEST_TIMEOUT_SECONDS = 30.0
_TRANSPORT_RETRIES = 2  # connection-level only (httpx limitation)
_EXECUTE_RETRIES = 2    # for ReadTimeout / RemoteProtocolError


def _http1_client_like(old: httpx.Client) -> httpx.Client:
    """Build an HTTP/1.1 replacement that preserves base_url, headers, and timeout."""
    transport = httpx.HTTPTransport(retries=_TRANSPORT_RETRIES)
    return httpx.Client(
        base_url=old.base_url,
        headers=old.headers,
        timeout=old.timeout,
        http1=True,
        http2=False,
        transport=transport,
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=_KEEPALIVE_EXPIRY_SECONDS,
        ),
    )


def _harden_supabase_client(client: Client) -> None:
    """Replace supabase's HTTP/2 sessions with HTTP/1.1 ones that recycle idle conns."""
    seen: set[int] = set()
    pg = getattr(client, "postgrest", None)
    if pg is not None and isinstance(getattr(pg, "session", None), httpx.Client):
        old = pg.session
        pg.session = _http1_client_like(old)
        seen.add(id(old))
        try:
            old.close()
        except Exception:
            pass

    storage = getattr(client, "storage", None)
    if storage is not None:
        for attr in ("session", "_client"):
            sess = getattr(storage, attr, None)
            if isinstance(sess, httpx.Client) and id(sess) not in seen:
                replacement = _http1_client_like(sess)
                try:
                    setattr(storage, attr, replacement)
                except Exception:
                    pass
                seen.add(id(sess))
                try:
                    sess.close()
                except Exception:
                    pass


def _reset_thread_client() -> None:
    """Drop the per-thread client so the next supabase() call rebuilds it."""
    with _local_lock:
        old = getattr(_local, "client", None)
        _local.client = None
        if old is not None:
            for attr_path in ("postgrest.session", "storage.session"):
                head, tail = attr_path.split(".")
                holder = getattr(old, head, None)
                sess = getattr(holder, tail, None) if holder is not None else None
                if isinstance(sess, httpx.Client):
                    try:
                        sess.close()
                    except Exception:
                        pass


# ── Retry wrapper around postgrest .execute() ────────────────────────────
# Retries on ReadTimeout / RemoteProtocolError / ConnectError. These are all
# "the connection was secretly dead, server didn't ack" failures and a fresh
# connection almost always succeeds. We monkey-patch once at import time so
# every call site benefits without changing call sites.
_RETRYABLE = (
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
)
_original_execute = SyncQueryRequestBuilder.execute


def _is_closed_client_error(exc: BaseException) -> bool:
    """httpx raises a bare RuntimeError when a request is issued on a closed client."""
    return isinstance(exc, RuntimeError) and "client has been closed" in str(exc)


def _execute_with_retry(self):
    last_exc: Exception | None = None
    for attempt in range(_EXECUTE_RETRIES + 1):
        try:
            return _original_execute(self)
        except _RETRYABLE as e:
            last_exc = e
        except RuntimeError as e:
            if not _is_closed_client_error(e):
                raise
            last_exc = e
        log.warning(
            "supabase %s %s failed (%s), attempt %d/%d — recycling client",
            self.http_method, self.path, type(last_exc).__name__,
            attempt + 1, _EXECUTE_RETRIES + 1,
        )
        # Recycle the thread's client AND rebind this request builder to the
        # fresh session. _reset_thread_client() closes the old httpx session,
        # but `self` still points at it — retrying without rebinding would just
        # raise "Cannot send a request, as the client has been closed."
        _reset_thread_client()
        fresh = supabase()
        new_session = getattr(getattr(fresh, "postgrest", None), "session", None)
        if isinstance(new_session, httpx.Client):
            self.session = new_session
    assert last_exc is not None
    raise last_exc


SyncQueryRequestBuilder.execute = _execute_with_retry


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
        _harden_supabase_client(client)
        _local.client = client
    return client
