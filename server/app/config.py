import os
import secrets
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("TVSHARE_DATA_DIR", "./data")).resolve()
        # Family password. Parents log in to the mobile web page with it.
        self.password = os.environ.get("TVSHARE_PASSWORD", "")
        # Upload chunk size the server tells clients to use (bytes).
        self.chunk_size = int(os.environ.get("TVSHARE_CHUNK_SIZE", str(8 * 1024 * 1024)))
        # Longest edge of transcoded output; videos larger than this are downscaled.
        self.max_height = int(os.environ.get("TVSHARE_MAX_HEIGHT", "1080"))
        self.ffmpeg = os.environ.get("TVSHARE_FFMPEG", "ffmpeg")
        self.ffprobe = os.environ.get("TVSHARE_FFPROBE", "ffprobe")
        # Set to "1" when the site is served over HTTPS so the auth cookie is marked Secure.
        self.secure_cookie = os.environ.get("TVSHARE_SECURE_COOKIE", "0") == "1"

        self.videos_dir = self.data_dir / "videos"
        self.thumbs_dir = self.data_dir / "thumbs"
        self.uploads_dir = self.data_dir / "uploads"
        self.db_path = self.data_dir / "tvshare.db"
        self.secret_path = self.data_dir / "secret.key"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.videos_dir, self.thumbs_dir, self.uploads_dir):
            d.mkdir(parents=True, exist_ok=True)

    def secret(self) -> bytes:
        """Server-side signing key, generated once and kept in the data dir."""
        if not self.secret_path.exists():
            self.secret_path.write_bytes(secrets.token_bytes(32))
        return self.secret_path.read_bytes()
