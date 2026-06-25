import logging
import httpx

from app.config import settings

log = logging.getLogger("midas.shorts.wayin")


class WayinVideoError(RuntimeError):
    """Wraps any failure talking to the WayinVideo API.

    `status_code` is the upstream HTTP status, or None for client-side
    failures (missing config, network error, timeout, bad JSON).
    """
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class WayinVideoNotConfigured(WayinVideoError):
    """WAYINVIDEO_API_KEY is missing — surfaced as 503 by the route."""


def _headers() -> dict:
    key = (settings.WAYINVIDEO_API_KEY or "").strip()
    if not key:
        raise WayinVideoNotConfigured(
            "WAYINVIDEO_API_KEY is not set. Add it to your .env and restart the server."
        )
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "x-wayinvideo-api-version": "v2",
    }


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        return httpx.request(method, url, timeout=30.0, **kwargs)
    except httpx.TimeoutException as e:
        log.error("WayinVideo %s %s timed out: %s", method, url, e)
        raise WayinVideoError(f"WayinVideo request timed out: {e}") from e
    except httpx.HTTPError as e:
        log.error("WayinVideo %s %s network error: %s", method, url, e)
        raise WayinVideoError(f"WayinVideo network error: {e}") from e


def _check(resp: httpx.Response, action: str) -> dict:
    if resp.status_code != 200:
        body = resp.text[:500]
        log.error("WayinVideo %s failed %d: %s", action, resp.status_code, body)
        raise WayinVideoError(
            f"WayinVideo {action} failed ({resp.status_code}): {body}",
            status_code=resp.status_code,
        )
    try:
        return resp.json()
    except ValueError as e:
        log.error("WayinVideo %s returned non-JSON body: %s", action, resp.text[:500])
        raise WayinVideoError(f"WayinVideo {action} returned non-JSON: {e}") from e


def _clip_payload(video_url: str) -> dict:
    """Build the POST /clips body from configured export/reframe settings."""
    body: dict = {
        "video_url":      video_url,
        "enable_export":  True,
        "resolution":     settings.WAYINVIDEO_RESOLUTION,
        "enable_caption": settings.WAYINVIDEO_CAPTIONS,
    }
    if settings.WAYINVIDEO_REFRAME:
        # ratio is required by the API whenever AI Reframe is on.
        body["enable_ai_reframe"] = True
        body["ratio"] = settings.WAYINVIDEO_RATIO
        # Only send reframe_layout for non-default layouts. "Auto" (the API default)
        # is the subject-tracking crop-to-fill we want — omitting the field gives the
        # same proven-working shape as WayinVideo's reference integrations. Note the
        # "Full"/"Fit" layouts PRESERVE the full source frame and therefore letterbox.
        layout = (settings.WAYINVIDEO_REFRAME_LAYOUT or "").strip()
        if layout and layout.lower() != "auto":
            body["reframe_layout"] = layout
    return body


def submit_clipping(video_url: str) -> str:
    """Submit an AI Clipping task. Returns the task id (used as project_id downstream)."""
    url = f"{settings.WAYINVIDEO_BASE_URL}/clips"
    log.info("WayinVideo submit_clipping video_url=%s", video_url)
    resp = _request("POST", url, headers=_headers(), json=_clip_payload(video_url))
    payload = _check(resp, "submit")
    try:
        project_id = payload["data"]["id"]
    except (KeyError, TypeError) as e:
        raise WayinVideoError(f"WayinVideo submit: unexpected response shape: {payload}") from e
    log.info("WayinVideo submit_clipping ok project_id=%s", project_id)
    return project_id


def get_status(project_id: str) -> dict:
    """Poll a task. Returns the `data` payload (includes status, clips, error_message)."""
    url = f"{settings.WAYINVIDEO_BASE_URL}/clips/results/{project_id}"
    resp = _request("GET", url, headers=_headers())
    payload = _check(resp, "status")
    return payload.get("data") or {}
