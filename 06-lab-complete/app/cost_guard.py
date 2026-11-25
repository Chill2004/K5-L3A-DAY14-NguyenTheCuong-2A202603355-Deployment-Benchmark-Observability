"""
Cost guard (tiêu chí 8).

• Cộng dồn chi phí LLM (tính theo token) vào Redis, key theo ngày UTC: `cost:YYYY-MM-DD`
  → sang ngày mới key đổi, tổng tự về 0; key cũ tự hết hạn sau 2 ngày.
• Tổng chi phí trong ngày >= DAILY_BUDGET_USD → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

COST_KEY_TTL_SECONDS = 2 * 24 * 3600


def _today_key() -> str:
    return "cost:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def current_spend() -> float:
    return float(r.get(_today_key()) or 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    spent = current_spend()
    budget = settings.daily_budget_usd
    if spent >= budget:
        raise HTTPException(
            status_code=402,
            detail={"error": "Daily budget exceeded", "spent_usd": round(spent, 6),
                    "budget_usd": budget, "resets": "00:00 UTC"},
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng (INCRBYFLOAT, nguyên tử)."""
    cost = (input_tokens / 1000) * settings.price_input_per_1k \
        + (output_tokens / 1000) * settings.price_output_per_1k
    key = _today_key()
    pipe = r.pipeline(transaction=True)
    pipe.incrbyfloat(key, cost)
    pipe.expire(key, COST_KEY_TTL_SECONDS)
    pipe.execute()
    return cost
