"""
Rate limiting (tiêu chí 7) — sliding window 60 giây bằng Redis sorted set.

Mỗi API key có một sorted set `ratelimit:<hash key>`: member là id request, score là timestamp.
Mọi worker / instance dùng chung Redis nên đếm chung, và state vẫn còn sau khi restart agent.
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _redis_key(api_key: str) -> str:
    # Không lưu API key gốc trong Redis — chỉ lưu hash
    return "ratelimit:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]


def check_rate_limit(key: str) -> None:
    """Vượt RATE_LIMIT_PER_MINUTE request / 60 giây → HTTP 429 + Retry-After."""
    limit = settings.rate_limit_per_minute
    rkey = _redis_key(key)
    now = time.time()
    member = f"{now}:{uuid.uuid4().hex[:8]}"   # id duy nhất, 2 request cùng thời điểm không đè nhau

    # MULTI/EXEC: 4 lệnh chạy nguyên khối, worker khác không chen vào giữa được
    pipe = r.pipeline(transaction=True)
    pipe.zremrangebyscore(rkey, 0, now - WINDOW_SECONDS)   # bỏ request ngoài cửa sổ
    pipe.zadd(rkey, {member: now})                         # ghi request hiện tại
    pipe.zcard(rkey)                                       # đếm request trong cửa sổ
    pipe.expire(rkey, WINDOW_SECONDS + 1)                  # key tự xoá khi không còn dùng
    _, _, count, _ = pipe.execute()

    if count > limit:
        r.zrem(rkey, member)                               # request bị chặn không tính vào quota
        oldest = r.zrange(rkey, 0, 0, withscores=True)
        retry_after = WINDOW_SECONDS
        if oldest:
            retry_after = max(1, math.ceil(oldest[0][1] + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit,
                    "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after),
                     "X-RateLimit-Limit": str(limit),
                     "X-RateLimit-Remaining": "0"},
        )
