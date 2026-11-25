"""
Production AI Agent — Part 6 Final Project.

Luồng của POST /ask:
    verify_api_key (401) → check_rate_limit (429) → check_budget (402) → LLM → record_cost

Chạy:  uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Chấm:  python check_production_ready.py
"""
import json
import logging
import math
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask

APP_VERSION = "1.0.0"
START_TIME = time.time()


# ─────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object hợp lệ
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    """Ghi cả bản ghi bằng json.dumps — không ghép chuỗi, nên ký tự " trong message luôn được escape."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "data", {}))     # field thêm: logger.info("x", extra={"data": {...}})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def _setup_logger() -> logging.Logger:
    # Logger riêng của app, không đụng vào root logger hay logger của uvicorn
    log = logging.getLogger("agent")
    log.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.setLevel(settings.log_level)
    log.propagate = False
    return log


logger = _setup_logger()


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"data": fields})


# ─────────────────────────────────────────────────────────
# Lifecycle + graceful shutdown (tiêu chí 11)
# ─────────────────────────────────────────────────────────
_state = {"shutting_down": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", version=APP_VERSION, environment=settings.environment, port=settings.port,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              daily_budget_usd=settings.daily_budget_usd, api_key_configured=bool(settings.agent_api_key))
    if not settings.agent_api_key:
        log_event("agent_api_key_missing", logging.WARNING,
                  detail="AGENT_API_KEY chưa đặt: mọi request /ask sẽ bị 401")
    yield
    # Tới đây uvicorn đã nhận SIGTERM, ngừng nhận kết nối mới và chờ xong các request đang chạy.
    # Không tự đăng ký signal handler: uvicorn đã xử lý SIGTERM, ghi đè handler dễ làm process không tắt.
    _state["shutting_down"] = True
    log_event("shutdown", uptime_seconds=round(time.time() - START_TIME, 1))
    r.close()


app = FastAPI(title="Production AI Agent", version=APP_VERSION, lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs",
              redoc_url=None)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """Log mỗi request thành 1 dòng JSON; gắn X-Request-ID để dò log theo request."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    quiet = request.url.path in ("/health", "/ready")       # probe gọi liên tục → chỉ log ở DEBUG
    log_event("request", logging.DEBUG if quiet else logging.INFO, request_id=request_id,
              method=request.method, path=request.url.path, status=response.status_code, ms=ms)
    return response


# ─────────────────────────────────────────────────────────
# Xử lý lỗi: mã lỗi rõ ràng, không lộ stack trace cho client
# ─────────────────────────────────────────────────────────
@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    log_event("redis_unavailable", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Dependency unavailable, try again later"},
                        headers={"Retry-After": "5"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc, extra={"data": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ─────────────────────────────────────────────────────────
# Health checks
# ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Liveness (tiêu chí 4): process còn chạy là 200 — KHÔNG phụ thuộc Redis."""
    return {"status": "ok", "version": APP_VERSION, "environment": settings.environment,
            "uptime_seconds": round(time.time() - START_TIME, 1)}


@app.get("/ready")
def ready():
    """Readiness (tiêu chí 5): Redis không kết nối được hoặc đang tắt → 503."""
    if _state["shutting_down"]:
        raise HTTPException(status_code=503, detail="Shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not reachable")
    return {"status": "ready", "redis": "ok"}


# ─────────────────────────────────────────────────────────
# Agent endpoint
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)


def _estimate_tokens(text: str) -> int:
    """Ước lượng ~4 ký tự / token (mock LLM không trả usage thật)."""
    return max(1, math.ceil(len(text) / 4))


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # 429 khi vượt RATE_LIMIT_PER_MINUTE / 60 giây
    check_budget()                     # 402 khi chi phí hôm nay >= DAILY_BUDGET_USD

    answer = llm_ask(body.question)

    input_tokens, output_tokens = _estimate_tokens(body.question), _estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    # Không log nội dung câu hỏi hay API key — chỉ log số liệu
    log_event("llm_call", question_chars=len(body.question), input_tokens=input_tokens,
              output_tokens=output_tokens, cost_usd=round(cost, 8))
    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": round(cost, 8)},
    }
