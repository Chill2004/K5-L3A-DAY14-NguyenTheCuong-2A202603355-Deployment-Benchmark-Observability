"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.

Giá trị mặc định chỉ để chạy local cho tiện; secret (AGENT_API_KEY) KHÔNG có default:
thiếu key thì /ask từ chối mọi request (xem auth.py) chứ không mở cửa với một key ai cũng biết.
"""
import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    # Server
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Security
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # Redis — state dùng chung giữa các worker / instance
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Rate limit: số request tối đa mỗi API key trong 60 giây
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))

    # Cost guard: ngân sách LLM mỗi ngày (USD), giá token
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 1.0))
    price_input_per_1k: float = field(default_factory=lambda: _env_float("PRICE_INPUT_PER_1K", 0.00015))
    price_output_per_1k: float = field(default_factory=lambda: _env_float("PRICE_OUTPUT_PER_1K", 0.0006))


settings = Settings()
