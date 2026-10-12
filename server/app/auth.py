import hashlib
import hmac
import secrets
import threading
import time

from fastapi import HTTPException, Request

COOKIE_NAME = "tvshare_token"


def family_token(secret: bytes, password: str) -> str:
    """The single access token shared by the family's phones and TVs.

    Derived from the password, so changing TVSHARE_PASSWORD signs every device out.
    """
    digest = hmac.new(secret, f"family:{password}".encode(), hashlib.sha256).hexdigest()
    return f"v1.{digest}"


def request_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def require_auth(request: Request) -> None:
    expected: str = request.app.state.token
    token = request_token(request)
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="未登录或登录已失效")


class LoginLimiter:
    """Slows down password guessing: at most `limit` failures per IP per window."""

    def __init__(self, limit: int = 10, window: float = 600) -> None:
        self.limit = limit
        self.window = window
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, ip: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(ip, []) if now - t < self.window]
        self._failures[ip] = recent
        return recent

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._recent(ip, time.time())) >= self.limit

    def fail(self, ip: str) -> None:
        with self._lock:
            self._recent(ip, time.time()).append(time.time())

    def reset(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)


class PairingStore:
    """Lets a TV get the family token without typing a password on the remote.

    The TV asks for a short code and shows it on screen; a logged-in parent enters
    the code on the phone; the TV's next poll receives the token.
    """

    TTL = 600

    def __init__(self) -> None:
        self._by_id: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        for pid in [p for p, s in self._by_id.items() if now - s["created"] > self.TTL]:
            del self._by_id[pid]

    def start(self) -> dict:
        now = time.time()
        with self._lock:
            self._purge(now)
            active = {s["code"] for s in self._by_id.values()}
            code = f"{secrets.randbelow(1_000_000):06d}"
            while code in active:
                code = f"{secrets.randbelow(1_000_000):06d}"
            pair_id = secrets.token_urlsafe(24)
            self._by_id[pair_id] = {"code": code, "created": now, "confirmed": False}
        return {"pair_id": pair_id, "code": code, "expires_in": self.TTL}

    def confirm(self, code: str) -> bool:
        with self._lock:
            self._purge(time.time())
            for session in self._by_id.values():
                if session["code"] == code and not session["confirmed"]:
                    session["confirmed"] = True
                    return True
        return False

    def poll(self, pair_id: str) -> str:
        """Returns 'pending', 'confirmed' (consumed on read) or 'expired'."""
        with self._lock:
            self._purge(time.time())
            session = self._by_id.get(pair_id)
            if session is None:
                return "expired"
            if session["confirmed"]:
                del self._by_id[pair_id]
                return "confirmed"
            return "pending"
