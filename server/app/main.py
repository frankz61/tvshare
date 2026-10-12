import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import media
from .auth import COOKIE_NAME, LoginLimiter, PairingStore, family_token, require_auth
from .config import Settings
from .db import Database

log = logging.getLogger("tvshare")
STATIC_DIR = Path(__file__).parent / "static"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


# ---------- request bodies ----------

class LoginBody(BaseModel):
    password: str


class CategoryBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    sort_order: int | None = None


class UploadInit(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    title: str = Field(default="", max_length=100)
    category_id: int | None = None


class VideoPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    category_id: int | None = None
    # category_id=None is ambiguous ("unchanged" vs "uncategorized"), so moving
    # a video out of every category is an explicit flag.
    uncategorized: bool = False


class PairConfirm(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


# ---------- helpers ----------

def video_json(v: dict, progress: dict | None = None) -> dict:
    vid = v["id"]
    ready = v["status"] == "ready"
    return {
        # Only while processing: {"stage": "queued", "ahead": n} or
        # {"stage": "transcoding"|"finishing", "percent", "eta", "elapsed"} (seconds).
        "progress": progress,
        "id": vid,
        "title": v["title"],
        "category_id": v["category_id"],
        "status": v["status"],
        "duration": v["duration"],
        "width": v["width"],
        "height": v["height"],
        "size": v["size"],
        "error": v["error"],
        "created_at": v["created_at"],
        "video_url": f"/media/videos/{vid}.mp4" if ready else None,
        "thumb_url": f"/media/thumbs/{vid}.jpg" if ready else None,
    }


def upload_part(settings: Settings, upload_id: str) -> Path:
    return settings.uploads_dir / f"{upload_id}.part"


def check_id(value: str) -> str:
    if not ID_RE.match(value):
        raise HTTPException(status_code=404, detail="不存在")
    return value


def default_title(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem[:100] or "未命名视频"


# ---------- app ----------

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if not settings.password:
        raise RuntimeError("请设置环境变量 TVSHARE_PASSWORD（家庭密码）")
    settings.ensure_dirs()
    db = Database(settings.db_path)
    processor = media.Processor(settings, db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Abandoned uploads (phone closed mid-way, never resumed) are removed after two days.
        for upload_id in db.stale_uploads(time.time() - 2 * 86400):
            upload_part(settings, upload_id).unlink(missing_ok=True)
            db.delete_upload(upload_id)
        processor.start()
        yield
        processor.stop()

    app = FastAPI(title="TVShare", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.processor = processor
    app.state.token = family_token(settings.secret(), settings.password)
    limiter = LoginLimiter()

    def to_json(v: dict) -> dict:
        return video_json(v, processor.status(v["id"]) if v["status"] == "processing" else None)

    pairing = PairingStore()
    auth = [Depends(require_auth)]

    # ---- auth ----

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        if limiter.blocked(ip):
            raise HTTPException(status_code=429, detail="尝试次数太多，请 10 分钟后再试")
        if not secrets.compare_digest(body.password.encode(), settings.password.encode()):
            limiter.fail(ip)
            raise HTTPException(status_code=401, detail="密码不对")
        limiter.reset(ip)
        response.set_cookie(
            COOKIE_NAME, app.state.token, max_age=365 * 86400, httponly=True,
            samesite="lax", secure=settings.secure_cookie,
        )
        return {"token": app.state.token}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME)
        return {"ok": True}

    @app.get("/api/me", dependencies=auth)
    def me():
        return {"ok": True}

    # ---- TV pairing ----

    @app.post("/api/pair")
    def pair_start():
        return pairing.start()

    @app.get("/api/pair/{pair_id}")
    def pair_poll(pair_id: str):
        status = pairing.poll(pair_id)
        if status == "confirmed":
            return {"status": "confirmed", "token": app.state.token}
        return {"status": status}

    @app.post("/api/pair/confirm", dependencies=auth)
    def pair_confirm(body: PairConfirm):
        if not pairing.confirm(body.code):
            raise HTTPException(status_code=404, detail="配对码不对或已过期，请看电视上最新的配对码")
        return {"ok": True}

    # ---- categories ----

    @app.get("/api/categories", dependencies=auth)
    def list_categories():
        return db.list_categories()

    @app.post("/api/categories", dependencies=auth)
    def create_category(body: CategoryBody):
        return db.create_category(body.name.strip())

    @app.patch("/api/categories/{category_id}", dependencies=auth)
    def update_category(category_id: int, body: CategoryPatch):
        if db.get_category(category_id) is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        db.update_category(category_id, body.name.strip() if body.name else None, body.sort_order)
        return db.get_category(category_id)

    @app.delete("/api/categories/{category_id}", dependencies=auth)
    def delete_category(category_id: int):
        # Videos in it are kept and become uncategorized.
        db.delete_category(category_id)
        return {"ok": True}

    # ---- videos ----

    @app.get("/api/videos", dependencies=auth)
    def list_videos(category_id: int | None = None, uncategorized: bool = False):
        return [to_json(v) for v in db.list_videos(category_id, uncategorized)]

    @app.get("/api/videos/{video_id}", dependencies=auth)
    def get_video(video_id: str):
        v = db.get_video(check_id(video_id))
        if v is None:
            raise HTTPException(status_code=404, detail="视频不存在")
        return to_json(v)

    @app.patch("/api/videos/{video_id}", dependencies=auth)
    def update_video(video_id: str, body: VideoPatch):
        v = db.get_video(check_id(video_id))
        if v is None:
            raise HTTPException(status_code=404, detail="视频不存在")
        fields: dict = {}
        if body.title is not None:
            fields["title"] = body.title.strip()
        if body.uncategorized:
            fields["category_id"] = None
        elif body.category_id is not None:
            if db.get_category(body.category_id) is None:
                raise HTTPException(status_code=400, detail="分类不存在")
            fields["category_id"] = body.category_id
        db.update_video(video_id, **fields)
        return to_json(db.get_video(video_id))  # type: ignore[arg-type]

    @app.delete("/api/videos/{video_id}", dependencies=auth)
    def delete_video(video_id: str):
        check_id(video_id)
        db.delete_video(video_id)
        for p in (
            media.output_path(settings, video_id),
            media.source_path(settings, video_id),
            media.thumb_path(settings, video_id),
        ):
            p.unlink(missing_ok=True)
        return {"ok": True}

    @app.post("/api/videos/{video_id}/retry", dependencies=auth)
    def retry_video(video_id: str):
        v = db.get_video(check_id(video_id))
        if v is None or v["status"] != "failed":
            raise HTTPException(status_code=400, detail="只有处理失败的视频可以重试")
        if not media.source_path(settings, video_id).exists():
            raise HTTPException(status_code=400, detail="原始文件已不在，请重新上传")
        db.update_video(video_id, status="processing", error=None)
        processor.submit(video_id)
        return {"ok": True}

    # ---- resumable chunked upload ----
    # init -> PUT chunks at the current offset -> complete. A dropped connection
    # resumes from GET's `received` instead of starting a large video over.

    @app.post("/api/uploads", dependencies=auth)
    def upload_init(body: UploadInit):
        if body.category_id is not None and db.get_category(body.category_id) is None:
            raise HTTPException(status_code=400, detail="分类不存在")
        upload_id = secrets.token_urlsafe(16)
        title = body.title.strip() or default_title(body.filename)
        db.create_upload(upload_id, body.filename, body.size, title, body.category_id)
        upload_part(settings, upload_id).touch()
        return {"upload_id": upload_id, "chunk_size": settings.chunk_size, "received": 0}

    def get_upload_or_404(upload_id: str) -> dict:
        up = db.get_upload(check_id(upload_id))
        if up is None:
            raise HTTPException(status_code=404, detail="上传任务不存在，请重新上传")
        return up

    @app.get("/api/uploads/{upload_id}", dependencies=auth)
    def upload_status(upload_id: str):
        up = get_upload_or_404(upload_id)
        part = upload_part(settings, upload_id)
        return {"upload_id": upload_id, "size": up["size"], "received": part.stat().st_size if part.exists() else 0}

    @app.put("/api/uploads/{upload_id}", dependencies=auth)
    async def upload_chunk(upload_id: str, offset: int, request: Request):
        up = get_upload_or_404(upload_id)
        part = upload_part(settings, upload_id)
        current = part.stat().st_size if part.exists() else 0
        if offset != current:
            # Client is out of sync (e.g. a retried chunk already landed); tell it where to resume.
            return Response(
                content=f'{{"received": {current}}}', status_code=409, media_type="application/json"
            )
        written = 0
        with part.open("ab") as f:
            async for chunk in request.stream():
                written += len(chunk)
                if current + written > up["size"] or written > settings.chunk_size * 2:
                    f.truncate(current)
                    raise HTTPException(status_code=400, detail="分片大小不对")
                f.write(chunk)
        return {"received": current + written}

    @app.post("/api/uploads/{upload_id}/complete", dependencies=auth)
    def upload_complete(upload_id: str):
        up = get_upload_or_404(upload_id)
        part = upload_part(settings, upload_id)
        received = part.stat().st_size if part.exists() else 0
        if received != up["size"]:
            raise HTTPException(status_code=400, detail=f"文件还没传完（{received}/{up['size']}）")
        video_id = secrets.token_urlsafe(12)
        part.replace(media.source_path(settings, video_id))
        db.create_video(video_id, up["title"], up["category_id"], up["filename"])
        db.delete_upload(upload_id)
        processor.submit(video_id)
        return to_json(db.get_video(video_id))  # type: ignore[arg-type]

    @app.delete("/api/uploads/{upload_id}", dependencies=auth)
    def upload_cancel(upload_id: str):
        check_id(upload_id)
        upload_part(settings, upload_id).unlink(missing_ok=True)
        db.delete_upload(upload_id)
        return {"ok": True}

    # ---- media files (Range requests supported by FileResponse, needed for seeking) ----

    @app.get("/media/videos/{video_id}.mp4", dependencies=auth)
    def media_video(video_id: str):
        path = media.output_path(settings, check_id(video_id))
        if not path.exists():
            raise HTTPException(status_code=404, detail="视频不存在")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/media/thumbs/{video_id}.jpg", dependencies=auth)
    def media_thumb(video_id: str):
        path = media.thumb_path(settings, check_id(video_id))
        if not path.exists():
            raise HTTPException(status_code=404, detail="封面不存在")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/health")
    def health():
        return {"ok": True}

    # ---- mobile web page ----

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        create_app(),
        host=os.environ.get("TVSHARE_HOST", "0.0.0.0"),
        port=int(os.environ.get("TVSHARE_PORT", "8000")),
        proxy_headers=True,
        # Only trust X-Forwarded-For from a reverse proxy we know, otherwise the
        # login limiter could be bypassed by spoofing the header.
        forwarded_allow_ips=os.environ.get("TVSHARE_TRUSTED_PROXIES", "127.0.0.1"),
    )


if __name__ == "__main__":
    run()
