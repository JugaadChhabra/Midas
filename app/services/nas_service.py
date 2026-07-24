"""NAS access for the shorts cutter. SMB in production; a plain-filesystem
'local' mode makes it testable and usable without a NAS.

All relative paths are relative to the SMB share root (//SERVER/SHARE). In
local mode they resolve under `local_root`, a directory that stands in for
the share."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


class NASService:
    def __init__(self) -> None:
        self.mode = settings.NAS_MODE
        self.server = settings.NAS_SERVER
        self.share = settings.NAS_SHARE
        self.local_root = Path(settings.NAS_LOCAL_ROOT).resolve()
        self._connected = False

    # --- path helpers ---------------------------------------------------
    def _rel(self, relative_path: str) -> str:
        return relative_path.strip("/").replace("\\", "/")

    def _remote(self, relative_path: str) -> str:
        win = self._rel(relative_path).replace("/", "\\")
        return rf"\\{self.server}\{self.share}\{win}"

    def _local(self, relative_path: str) -> Path:
        return self.local_root / self._rel(relative_path)

    def _connect(self) -> None:
        if self.mode != "smb" or self._connected:
            return
        import smbclient
        kwargs = {"username": settings.NAS_USERNAME,
                  "password": settings.NAS_PASSWORD,
                  "port": settings.NAS_PORT,
                  "auth_protocol": settings.NAS_AUTH_PROTOCOL}
        domain = (settings.NAS_DOMAIN or "").strip()
        if domain:
            kwargs["username"] = f"{domain}\\{settings.NAS_USERNAME}"
        smbclient.register_session(self.server, **kwargs)
        self._connected = True

    # --- operations -----------------------------------------------------
    def makedirs(self, relative_dir: str) -> None:
        if self.mode == "local":
            self._local(relative_dir).mkdir(parents=True, exist_ok=True)
            return
        import smbclient
        self._connect()
        smbclient.makedirs(self._remote(relative_dir), exist_ok=True)

    def list_video_files(self, relative_dir: str) -> list[str]:
        if self.mode == "local":
            d = self._local(relative_dir)
            if not d.is_dir():
                return []
            names = [e.name for e in d.iterdir()
                     if e.is_file() and e.suffix.lower() in VIDEO_EXTENSIONS]
            return sorted(names)
        import smbclient
        self._connect()
        base = self._remote(relative_dir)
        if not smbclient.path.exists(base):
            return []
        names = [e.name for e in smbclient.scandir(base)
                 if not e.is_dir() and Path(e.name).suffix.lower() in VIDEO_EXTENSIONS]
        return sorted(names)

    def copy_to_local(self, relative_path: str, local_dest: Path) -> Path:
        local_dest = Path(local_dest)
        local_dest.parent.mkdir(parents=True, exist_ok=True)
        if self.mode == "local":
            shutil.copyfile(self._local(relative_path), local_dest)
            return local_dest
        import smbclient
        self._connect()
        with smbclient.open_file(self._remote(relative_path), mode="rb") as src, \
                open(local_dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return local_dest

    def copy_from_local(self, local_src: Path, relative_path: str) -> None:
        parent = str(Path(self._rel(relative_path)).parent)
        self.makedirs(parent)
        if self.mode == "local":
            shutil.copyfile(local_src, self._local(relative_path))
            return
        import smbclient
        self._connect()
        with open(local_src, "rb") as src, \
                smbclient.open_file(self._remote(relative_path), mode="wb") as dst:
            shutil.copyfileobj(src, dst)

    def move(self, src_relative: str, dst_relative: str) -> None:
        parent = str(Path(self._rel(dst_relative)).parent)
        self.makedirs(parent)
        if self.mode == "local":
            shutil.move(str(self._local(src_relative)), str(self._local(dst_relative)))
            return
        import smbclient
        self._connect()
        smbclient.rename(self._remote(src_relative), self._remote(dst_relative))


nas_service = NASService()
