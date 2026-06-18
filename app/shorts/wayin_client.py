import logging
import httpx

from app.config import settings

log = logging.getLogger("midas.shorts.wayin")


class WayinVideoError(RuntimeError):
    """Non-2xx response from the WayinVideo API."""


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.WAYINVIDEO_API_KEY}",
        "x-wayinvideo-api-version": "v2",
    }


def submit_clipping(video_url: str) -> str:
    """Submit an AI Clipping job. Returns project_id."""
    url = f"{settings.WAYINVIDEO_BASE_URL}/clipping"
    resp = httpx.post(
        url,
        headers=_headers(),
        json={"video_url": video_url, "export": True},
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise WayinVideoError(f"WayinVideo submit failed {resp.status_code}: {resp.text}")
    return resp.json()["data"]["project_id"]


def get_status(project_id: str) -> dict:
    """Poll a project. Returns the `data` payload (includes status, clips, error_message)."""
    url = f"{settings.WAYINVIDEO_BASE_URL}/clipping/{project_id}"
    resp = httpx.get(url, headers=_headers(), timeout=30.0)
    if resp.status_code != 200:
        raise WayinVideoError(f"WayinVideo status failed {resp.status_code}: {resp.text}")
    return resp.json()["data"]
