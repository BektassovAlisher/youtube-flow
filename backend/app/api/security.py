"""Access token for everything that changes data or spends API credits, and per-client hourly limits."""
import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

import config
from errors import UserError


def require_token(request: Request) -> None:
    """With API_TOKEN set, POST/DELETE need "Authorization: Bearer <API_TOKEN>". The web app adds it for signed-in users."""
    if not config.API_TOKEN:
        return
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(token.encode(), config.API_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Нужно войти, чтобы это сделать.")


def client_id(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


class RateLimiter:
    """Sliding one-hour window per (bucket, client). A limit of 0 turns the bucket off."""

    def __init__(self, window: float = 3600):
        self.window = window
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, bucket: str, client: str, limit: int) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[(bucket, client)]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= limit:
                minutes = int((self.window - (now - hits[0])) // 60) + 1
                raise UserError(f"Слишком много запросов. Попробуйте через {minutes} мин.", status=429)
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
