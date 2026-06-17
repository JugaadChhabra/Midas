import io
import logging
from typing import BinaryIO

from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

from app.youtube_client import youtube_for_channel

log = logging.getLogger("midas.shorts.upload")

# 8 MB chunks: a balance between memory and round-trip count for resumable upload.
_CHUNK_SIZE = 8 * 1024 * 1024


class YouTubeUploadError(RuntimeError):
    """Raised when the resumable upload loop terminates without a video id."""


def upload_short(
    channel_id: str,
    source: BinaryIO | str,
    title: str,
    description: str,
    tags: list[str],
) -> str:
    """Upload one short to YouTube, returns the new yt_video_id.

    `source` is either a filesystem path (str) or a binary file-like object
    opened for reading. Privacy is hardcoded to `private` for the prototype.
    """
    yt = youtube_for_channel(channel_id)

    if isinstance(source, str):
        media = MediaFileUpload(source, mimetype="video/mp4", chunksize=_CHUNK_SIZE, resumable=True)
    else:
        media = MediaIoBaseUpload(source, mimetype="video/mp4", chunksize=_CHUNK_SIZE, resumable=True)

    body = {
        "snippet": {
            "title": title[:100],          # YT title cap
            "description": description or "",
            "tags": tags or [],
            "categoryId": "22",            # People & Blogs
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }

    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            log.info("Upload progress: %d%%", int(status.progress() * 100))

    if not response or "id" not in response:
        raise YouTubeUploadError(f"Upload finished without video id: {response!r}")
    return response["id"]
