import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

PASSWORD = "dance123"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture
def settings(tmp_path: Path, monkeypatch) -> Settings:
    monkeypatch.setenv("TVSHARE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TVSHARE_PASSWORD", PASSWORD)
    monkeypatch.setenv("TVSHARE_CHUNK_SIZE", str(64 * 1024))
    return Settings()


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed(client: TestClient) -> TestClient:
    r = client.post("/api/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return client


def make_video(path: Path, args: list[str]) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-shortest", *args, str(path)],
        check=True,
    )
    return path


def upload(client: TestClient, path: Path, chunk: int, category_id=None, title="") -> dict:
    data = path.read_bytes()
    r = client.post("/api/uploads", json={
        "filename": path.name, "size": len(data), "title": title, "category_id": category_id,
    })
    assert r.status_code == 200, r.text
    upload_id = r.json()["upload_id"]
    offset = 0
    while offset < len(data):
        r = client.put(f"/api/uploads/{upload_id}?offset={offset}", content=data[offset:offset + chunk])
        assert r.status_code == 200, r.text
        offset = r.json()["received"]
    r = client.post(f"/api/uploads/{upload_id}/complete")
    assert r.status_code == 200, r.text
    return r.json()


def test_requires_auth(client: TestClient):
    assert client.get("/api/videos").status_code == 401
    assert client.get("/api/categories").status_code == 401
    assert client.post("/api/login", json={"password": "nope"}).status_code == 401


def test_bearer_token_works(client: TestClient):
    token = client.post("/api/login", json={"password": PASSWORD}).json()["token"]
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_login_rate_limited(client: TestClient):
    for _ in range(10):
        client.post("/api/login", json={"password": "wrong"})
    r = client.post("/api/login", json={"password": PASSWORD})
    assert r.status_code == 429


def test_categories_crud(authed: TestClient):
    a = authed.post("/api/categories", json={"name": "中国舞"}).json()
    b = authed.post("/api/categories", json={"name": "爵士"}).json()
    assert [c["name"] for c in authed.get("/api/categories").json()] == ["中国舞", "爵士"]
    authed.patch(f"/api/categories/{b['id']}", json={"name": "爵士舞", "sort_order": 0})
    assert [c["name"] for c in authed.get("/api/categories").json()] == ["爵士舞", "中国舞"]
    authed.delete(f"/api/categories/{a['id']}")
    assert len(authed.get("/api/categories").json()) == 1


def test_upload_resume_after_conflict(authed: TestClient, tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"a" * 1000)
    upload_id = authed.post("/api/uploads", json={"filename": "x.mp4", "size": 1000}).json()["upload_id"]
    assert authed.put(f"/api/uploads/{upload_id}?offset=0", content=b"a" * 400).json()["received"] == 400
    # A retried chunk at a stale offset is rejected with the real position.
    r = authed.put(f"/api/uploads/{upload_id}?offset=0", content=b"a" * 400)
    assert r.status_code == 409 and r.json()["received"] == 400
    assert authed.get(f"/api/uploads/{upload_id}").json()["received"] == 400
    # Completing early fails; too many bytes are refused.
    assert authed.post(f"/api/uploads/{upload_id}/complete").status_code == 400
    assert authed.put(f"/api/uploads/{upload_id}?offset=400", content=b"a" * 700).status_code == 400
    assert authed.get(f"/api/uploads/{upload_id}").json()["received"] == 400


@needs_ffmpeg
def test_upload_h264_is_remuxed(authed: TestClient, settings: Settings, tmp_path: Path):
    cat = authed.post("/api/categories", json={"name": "本周作业"}).json()
    src = make_video(tmp_path / "第一课.mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"])
    created = upload(authed, src, 64 * 1024, category_id=cat["id"])
    assert created["status"] == "processing"
    assert created["title"] == "第一课"

    authed.app.state.processor.wait_idle()
    v = authed.get(f"/api/videos/{created['id']}").json()
    assert v["status"] == "ready", v["error"]
    assert v["category_id"] == cat["id"]
    assert (v["width"], v["height"]) == (320, 240)
    assert 1.5 < v["duration"] < 2.5
    assert not (settings.videos_dir / f"{v['id']}.src").exists()

    assert [x["id"] for x in authed.get(f"/api/videos?category_id={cat['id']}").json()] == [v["id"]]
    assert authed.get("/api/videos?uncategorized=true").json() == []

    # Range requests are what make seeking on the TV work.
    r = authed.get(v["video_url"], headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    r = authed.get(v["thumb_url"])
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"


@needs_ffmpeg
def test_other_codec_is_transcoded(authed: TestClient, tmp_path: Path):
    src = make_video(tmp_path / "phone.mkv", ["-c:v", "mpeg4", "-c:a", "libopus"])
    created = upload(authed, src, 50 * 1024, title="新动作")
    authed.app.state.processor.wait_idle()
    v = authed.get(f"/api/videos/{created['id']}").json()
    assert v["status"] == "ready", v["error"]
    assert v["title"] == "新动作"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", "-"],
        input=authed.get(v["video_url"]).content, capture_output=True, check=True,
    )
    assert probe.stdout.decode().split() == ["h264", "aac"]


@needs_ffmpeg
def test_bad_file_fails_and_video_edit_delete(authed: TestClient, settings: Settings, tmp_path: Path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video" * 100)
    created = upload(authed, junk, 1024)
    authed.app.state.processor.wait_idle()
    v = authed.get(f"/api/videos/{created['id']}").json()
    assert v["status"] == "failed" and v["error"]

    cat = authed.post("/api/categories", json={"name": "A"}).json()
    v = authed.patch(f"/api/videos/{v['id']}", json={"title": "改名", "category_id": cat["id"]}).json()
    assert (v["title"], v["category_id"]) == ("改名", cat["id"])
    v = authed.patch(f"/api/videos/{v['id']}", json={"uncategorized": True}).json()
    assert v["category_id"] is None

    assert authed.delete(f"/api/videos/{v['id']}").status_code == 200
    assert authed.get(f"/api/videos/{v['id']}").status_code == 404
    assert not (settings.videos_dir / f"{v['id']}.src").exists()


def test_ffmpeg_thread_limit(settings: Settings, tmp_path: Path):
    from app import media

    info = {
        "format": {"format_name": "matroska"},
        "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080}],
    }
    assert "-threads" not in media.transcode_command(settings, tmp_path / "a", tmp_path / "b", info)

    settings.ffmpeg_threads = 1
    cmd = media.transcode_command(settings, tmp_path / "a", tmp_path / "b", info)
    i = cmd.index("-i")
    # Limits both the decoder (before -i) and the encoder/filters (after -i).
    assert cmd[i - 2:i] == ["-threads", "1"]
    assert cmd[i + 2:i + 6] == ["-threads", "1", "-filter_threads", "1"]


@needs_ffmpeg
def test_single_thread_transcode_works(authed: TestClient, tmp_path: Path):
    authed.app.state.settings.ffmpeg_threads = 1
    src = make_video(tmp_path / "one.mkv", ["-c:v", "mpeg4", "-c:a", "libopus"])
    created = upload(authed, src, 64 * 1024)
    authed.app.state.processor.wait_idle()
    assert authed.get(f"/api/videos/{created['id']}").json()["status"] == "ready"


def test_long_names_are_trimmed_not_rejected(authed: TestClient):
    # A real YouTube download name (110 chars, with an emoji) that used to get a 422.
    name = "30 Minutes of Beautiful Relaxing Music 🌿 Soothing Piano Music & Nature Sounds for Reduce Stress [3YT5Otj-ZoE].mp4"
    r = authed.post("/api/uploads", json={"filename": name, "size": 10, "title": name[:-4]})
    assert r.status_code == 200, r.text
    r = authed.post("/api/uploads", json={"filename": "x" * 400 + ".mp4", "size": 10})
    assert r.status_code == 200, r.text
    upload_id = r.json()["upload_id"]
    authed.put(f"/api/uploads/{upload_id}?offset=0", content=b"0123456789")
    v = authed.post(f"/api/uploads/{upload_id}/complete").json()
    assert v["title"] == "x" * 100


def test_parse_out_time():
    from app.media import parse_out_time

    assert parse_out_time("out_time_us=2500000\n") == 2.5
    assert parse_out_time("out_time_us=N/A") is None
    assert parse_out_time("progress=continue") is None


def test_processor_status(settings: Settings):
    import time as _time

    from app.db import Database
    from app.media import Processor

    settings.ensure_dirs()
    p = Processor(settings, Database(settings.db_path))  # worker thread not started
    p._pending = ["b", "c"]
    p._current = {"id": "a", "stage": "transcoding", "done": 30.0, "total": 120.0, "started": _time.monotonic() - 60}
    st = p.status("a")
    assert st["stage"] == "transcoding" and st["percent"] == 25.0
    assert 170 <= st["eta"] <= 190  # 30s of video took 60s -> 90s left takes ~180s
    assert p.status("b") == {"stage": "queued", "ahead": 1}
    assert p.status("c") == {"stage": "queued", "ahead": 2}
    assert p.status("zzz") is None


@needs_ffmpeg
def test_transcode_reports_progress(settings: Settings, tmp_path: Path):
    from app import media
    from app.db import Database

    settings.ensure_dirs()
    db = Database(settings.db_path)
    make_video(tmp_path / "p.mkv", ["-c:v", "mpeg4", "-c:a", "libopus"]).replace(media.source_path(settings, "vid12345"))
    db.create_video("vid12345", "t", None, "p.mkv")
    events: list[tuple[str, float, float]] = []
    media.process_video(settings, db, "vid12345", lambda *e: events.append(e))
    assert db.get_video("vid12345")["status"] == "ready"
    transcoding = [e for e in events if e[0] == "transcoding"]
    assert transcoding and all(1.5 < total < 2.5 for _, _, total in transcoding)
    assert [d for _, d, _ in transcoding] == sorted(d for _, d, _ in transcoding)
    assert events[-1][0] == "finishing"


def test_tv_pairing(client: TestClient):
    start = client.post("/api/pair").json()
    assert len(start["code"]) == 6
    assert client.get(f"/api/pair/{start['pair_id']}").json() == {"status": "pending"}

    # Confirming requires a logged-in parent.
    assert client.post("/api/pair/confirm", json={"code": start["code"]}).status_code == 401
    client.post("/api/login", json={"password": PASSWORD})
    assert client.post("/api/pair/confirm", json={"code": "000000" if start["code"] != "000000" else "111111"}).status_code == 404
    assert client.post("/api/pair/confirm", json={"code": start["code"]}).status_code == 200

    client.cookies.clear()
    r = client.get(f"/api/pair/{start['pair_id']}").json()
    assert r["status"] == "confirmed"
    assert client.get("/api/videos", headers={"Authorization": f"Bearer {r['token']}"}).status_code == 200
    # Token is handed out once.
    assert client.get(f"/api/pair/{start['pair_id']}").json() == {"status": "expired"}
