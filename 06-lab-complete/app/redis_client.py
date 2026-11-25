"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

• redis.from_url() KHÔNG mở kết nối ngay — kết nối được tạo ở lệnh đầu tiên, nên app vẫn
  khởi động được khi Redis chưa sẵn sàng (container chạy một mình, Redis khởi động chậm...).
• Timeout ngắn: Redis chết thì lệnh lỗi sau ~1 giây thay vì treo request.
"""
import redis

from app.config import settings

r = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    """Dùng cho GET /ready: ping được Redis → True, mọi lỗi kết nối → False."""
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
