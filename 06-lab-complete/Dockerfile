# ============================================================
# Production Dockerfile — multi-stage
#   Stage builder: cài dependencies vào một virtualenv /opt/venv
#   Stage runtime: image slim sạch, chỉ copy venv + code, chạy bằng user non-root
# Build: docker build -t day14-agent .
# Run:   docker run -p 8000:8000 -e AGENT_API_KEY=... -e REDIS_URL=... day14-agent
# ============================================================

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Virtualenv ở đường dẫn cố định → copy nguyên thư mục sang stage runtime,
# không phụ thuộc HOME của user như khi dùng `pip install --user`
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# requirements trước, code sau → sửa code không phải cài lại dependencies (layer cache)
COPY requirements.txt .
RUN pip install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# User non-root, không có shell đăng nhập
RUN groupadd --system app && useradd --system --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app

EXPOSE 8000

# Gọi /health theo đúng cổng PORT (Railway/Render có thể đổi cổng)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=3)" || exit 1

# `exec` thay shell bằng uvicorn → uvicorn là PID 1, nhận SIGTERM trực tiếp khi `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
