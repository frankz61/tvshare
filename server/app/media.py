"""Turns whatever the phone uploaded into an MP4 every Android TV can play.

Phones record HEVC/HDR, .mov, odd rotations and sometimes 4K. Cheap TV boxes
handle H.264 8-bit 1080p reliably, so anything else is transcoded to that.
"""

import json
import logging
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .config import Settings
from .db import Database

log = logging.getLogger("tvshare.media")

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


def probe(settings: Settings, path: Path) -> dict:
    out = subprocess.run(
        [settings.ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True,
        check=True,
    )
    return json.loads(out.stdout)


def _streams(info: dict, kind: str) -> list[dict]:
    return [s for s in info.get("streams", []) if s.get("codec_type") == kind]


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            return int(side["rotation"]) % 360
    return int(stream.get("tags", {}).get("rotate", 0)) % 360


def display_size(video: dict) -> tuple[int, int]:
    w, h = int(video.get("width", 0)), int(video.get("height", 0))
    if _rotation(video) in (90, 270):
        w, h = h, w
    return w, h


def can_remux(settings: Settings, info: dict) -> bool:
    """True when the source is already TV-friendly and only needs faststart."""
    videos = _streams(info, "video")
    if not videos:
        return False
    v = videos[0]
    w, h = display_size(v)
    audio_ok = all(a.get("codec_name") == "aac" for a in _streams(info, "audio")[:1])
    container_ok = "mp4" in info.get("format", {}).get("format_name", "")
    return (
        v.get("codec_name") == "h264"
        and v.get("pix_fmt") == "yuv420p"
        and min(w, h) <= settings.max_height
        and audio_ok
        and container_ok
    )


_zscale_available: bool | None = None


def has_zscale(settings: Settings) -> bool:
    global _zscale_available
    if _zscale_available is None:
        try:
            out = subprocess.run([settings.ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True)
            _zscale_available = " zscale " in out.stdout
        except OSError:
            _zscale_available = False
    return _zscale_available


def _input_threads(settings: Settings) -> list[str]:
    n = settings.ffmpeg_threads
    return ["-threads", str(n)] if n > 0 else []


def _output_threads(settings: Settings) -> list[str]:
    n = settings.ffmpeg_threads
    return ["-threads", str(n), "-filter_threads", str(n)] if n > 0 else []


def low_priority(cmd: list[str]) -> list[str]:
    """Run ffmpeg niced so other services on the box get the CPU first."""
    nice = shutil.which("nice")
    return [nice, "-n", "10", *cmd] if nice else cmd


def transcode_command(settings: Settings, src: Path, dst: Path, info: dict) -> list[str]:
    if can_remux(settings, info):
        return [
            settings.ffmpeg, "-y", "-v", "error", "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
            "-movflags", "+faststart", str(dst),
        ]

    limit = settings.max_height
    # Cap the shorter edge so portrait videos keep their full resolution too.
    filters = [
        f"scale='if(gt(iw,ih),-2,min({limit},iw))':'if(gt(iw,ih),min({limit},ih),-2)'"
    ]
    v = _streams(info, "video")[0]
    if v.get("color_transfer") in HDR_TRANSFERS and has_zscale(settings):
        # iPhone HDR footage looks washed out on SDR TVs without tone mapping.
        filters.insert(0, (
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
        ))
    filters.append("format=yuv420p")
    return [
        settings.ffmpeg, "-y", "-v", "error", *_input_threads(settings), "-i", str(src),
        *_output_threads(settings),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart", str(dst),
    ]


def make_thumbnail(settings: Settings, video: Path, thumb: Path, duration: float) -> None:
    at = max(0.0, min(duration * 0.2, 15.0)) if duration else 0.0
    subprocess.run(
        low_priority([
            settings.ffmpeg, "-y", "-v", "error", *_input_threads(settings), "-ss", f"{at:.2f}", "-i", str(video),
            *_output_threads(settings), "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(thumb),
        ]),
        capture_output=True,
        check=True,
    )


def source_path(settings: Settings, video_id: str) -> Path:
    return settings.videos_dir / f"{video_id}.src"


def output_path(settings: Settings, video_id: str) -> Path:
    return settings.videos_dir / f"{video_id}.mp4"


def thumb_path(settings: Settings, video_id: str) -> Path:
    return settings.thumbs_dir / f"{video_id}.jpg"


ProgressCallback = Callable[[str, float, float], None]  # (stage, seconds done, total seconds)


def parse_out_time(line: str) -> float | None:
    """Seconds encoded so far, from one line of ffmpeg's `-progress` output."""
    key, _, value = line.strip().partition("=")
    if key != "out_time_us":
        return None
    try:
        return max(0.0, int(value) / 1_000_000)
    except ValueError:  # "N/A" before the first frame
        return None


def run_ffmpeg(cmd: list[str], total: float, on_progress: ProgressCallback | None) -> tuple[int, str]:
    """Runs ffmpeg niced, reporting progress from its `-progress` key=value lines (~2/s)."""
    cmd = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    with tempfile.TemporaryFile(mode="w+") as err:
        proc = subprocess.Popen(low_priority(cmd), stdout=subprocess.PIPE, stderr=err, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            done = parse_out_time(line)
            if done is not None and on_progress:
                on_progress("transcoding", min(done, total) if total else done, total)
        proc.wait()
        err.seek(0)
        return proc.returncode, err.read()


def process_video(
    settings: Settings, db: Database, video_id: str, on_progress: ProgressCallback | None = None
) -> None:
    src = source_path(settings, video_id)
    dst = output_path(settings, video_id)
    tmp = dst.with_suffix(".tmp.mp4")
    try:
        info = probe(settings, src)
        if not _streams(info, "video"):
            raise ValueError("文件里没有视频画面")
        total = float(info.get("format", {}).get("duration") or 0)
        cmd = transcode_command(settings, src, tmp, info)
        returncode, stderr = run_ffmpeg(cmd, total, on_progress)
        if returncode != 0:
            raise RuntimeError(stderr.strip()[-500:] or "转码失败")
        tmp.replace(dst)
        if on_progress:
            on_progress("finishing", total, total)

        out_info = probe(settings, dst)
        v = _streams(out_info, "video")[0]
        w, h = display_size(v)
        duration = float(out_info.get("format", {}).get("duration") or 0)
        make_thumbnail(settings, dst, thumb_path(settings, video_id), duration)

        if db.get_video(video_id) is None:
            # Deleted while we were working on it.
            dst.unlink(missing_ok=True)
            thumb_path(settings, video_id).unlink(missing_ok=True)
        else:
            db.update_video(
                video_id, status="ready", duration=duration, width=w, height=h,
                size=dst.stat().st_size, error=None,
            )
        src.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - record any failure on the video
        log.exception("processing %s failed", video_id)
        tmp.unlink(missing_ok=True)
        if db.get_video(video_id) is not None:
            db.update_video(video_id, status="failed", error=str(exc)[:500])


class Processor:
    """Single background worker; transcoding is CPU-bound, so one at a time.

    Also keeps the queue order and the running job's progress in memory (never in
    the database), so the phone page can show "queued" / "37%, about 1 min left".
    """

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.queue: queue.Queue[str | None] = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="tvshare-processor", daemon=True)
        self._lock = threading.Lock()
        self._pending: list[str] = []
        self._current: dict | None = None

    def status(self, video_id: str) -> dict | None:
        """Progress for a video that is processing, or None if the worker doesn't know it."""
        with self._lock:
            cur = self._current
            if cur and cur["id"] == video_id:
                done, total = cur["done"], cur["total"]
                percent = min(99.0, done / total * 100) if total else None
                elapsed = time.monotonic() - cur["started"]
                # Estimate only once there is something to extrapolate from.
                eta = elapsed / done * (total - done) if total and done >= total * 0.02 else None
                return {
                    "stage": cur["stage"],
                    "percent": round(percent, 1) if percent is not None else None,
                    "eta": round(eta) if eta is not None else None,
                    "elapsed": round(elapsed),
                }
            if video_id in self._pending:
                return {"stage": "queued", "ahead": self._pending.index(video_id) + (1 if cur else 0)}
        return None

    def _report(self, stage: str, done: float, total: float) -> None:
        with self._lock:
            if self._current:
                self._current.update(stage=stage, done=done, total=total)

    def start(self) -> None:
        if shutil.which(self.settings.ffmpeg) is None:
            log.warning("ffmpeg not found (%s); uploads will fail to process", self.settings.ffmpeg)
        self.thread.start()
        for video_id in self.db.videos_with_status("processing"):
            self.submit(video_id)

    def submit(self, video_id: str) -> None:
        with self._lock:
            self._pending.append(video_id)
        self.queue.put(video_id)

    def stop(self) -> None:
        self.queue.put(None)

    def wait_idle(self) -> None:
        self.queue.join()

    def _run(self) -> None:
        while True:
            video_id = self.queue.get()
            try:
                if video_id is None:
                    return
                with self._lock:
                    if video_id in self._pending:
                        self._pending.remove(video_id)
                    self._current = {
                        "id": video_id, "stage": "transcoding", "done": 0.0, "total": 0.0,
                        "started": time.monotonic(),
                    }
                process_video(self.settings, self.db, video_id, self._report)
            finally:
                with self._lock:
                    self._current = None
                self.queue.task_done()
