"""
API Key authentication (tiêu chí 6).

• Client gửi header  X-API-Key: <key>
• Key phải trùng biến môi trường AGENT_API_KEY
• Thiếu hoặc sai key → HTTP 401 (không phải 403 hay 422)
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

# auto_error=False: thiếu header thì FastAPI KHÔNG tự trả 403/422, để hàm dưới tự trả 401
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho /ask. Trả về key hợp lệ để dùng làm khoá rate limit."""
    expected = settings.agent_api_key
    # Server chưa cấu hình key → từ chối tất cả, không bao giờ chấp nhận key rỗng.
    # compare_digest so sánh thời gian hằng số, tránh dò key bằng timing attack.
    if not api_key or not expected or not hmac.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include header: X-API-Key: <key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
