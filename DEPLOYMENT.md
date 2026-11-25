# Deployment Information

## Public URL

https://agent-production-58f1ea7e.up.railway.app

## Platform

**Railway**. Project `day14-agent` gồm 2 service:

| Service | Nguồn | Vai trò |
|---------|-------|---------|
| `agent` | `06-lab-complete/` (Dockerfile multi-stage, cấu hình `railway.toml`) | AI agent Part 6: FastAPI + uvicorn 2 worker |
| `Redis` | Railway Redis database | State dùng chung: rate limit (sorted set) + chi phí theo ngày |

Agent gọi Redis qua mạng nội bộ của Railway (`redis.railway.internal:6379`); Redis không mở ra Internet.

Deploy bằng Railway CLI, chạy trong thư mục `06-lab-complete/`:

```bash
railway login
railway init --name day14-agent
railway add --database redis
railway add --service agent
railway variables --service agent --set "AGENT_API_KEY=<random>" --set 'REDIS_URL=${{Redis.REDIS_URL}}' ...
railway up --service agent --ci
railway domain --service agent
```

## Test Commands

```bash
BASE=https://agent-production-58f1ea7e.up.railway.app
AGENT_API_KEY=<key đặt trên Railway>     # không ghi key thật vào repo
```

### Tự kiểm (CP6): mỗi lệnh chỉ in mã HTTP

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy ngày 2026-11-25:

```text
200
200
401
200
```

### Health Check

```bash
curl https://agent-production-58f1ea7e.up.railway.app/health
# {"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":25.9}

curl https://agent-production-58f1ea7e.up.railway.app/ready
# {"status":"ready","redis":"ok"}
```

### API Test (with authentication)

```bash
curl -X POST https://agent-production-58f1ea7e.up.railway.app/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":5,"output_tokens":20,"cost_usd":1.275e-05}}
```

### Rate limit (10 request / 60 giây)

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST "$BASE/ask" \
    -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d "{\"question\":\"test $i\"}"
done
# 200 200 200 200 200 200 200 200 429 429 429 429
# (2 request "có key" ở trên + 8 request = đủ 10 → request thứ 11 bị 429)
```

### Script chấm với URL public

```bash
cd 06-lab-complete
python check_production_ready.py --public-url https://agent-production-58f1ea7e.up.railway.app
# ✅ Public URL: GET https://agent-production-58f1ea7e.up.railway.app/health → 200
```

## Environment Variables Set

Đặt trên service `agent` bằng `railway variables`, **không** ghi trong code hay file config:

| Biến | Giá trị | Ghi chú |
|------|---------|---------|
| `AGENT_API_KEY` | chuỗi ngẫu nhiên 43 ký tự | secret; chỉ lưu trên Railway và một file trên máy cá nhân, ngoài repo |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | biến tham chiếu: Railway tự điền URL nội bộ (kèm mật khẩu) của service Redis |
| `ENVIRONMENT` | `production` | ẩn `/docs` ở production |
| `RATE_LIMIT_PER_MINUTE` | `10` | |
| `DAILY_BUDGET_USD` | `1.0` | |
| `LOG_LEVEL` | `INFO` | |
| `PORT` | do Railway tự cấp (`8080`) | không tự đặt; `CMD` trong Dockerfile dùng `${PORT:-8000}` |

Log khởi động trên Railway xác nhận app đọc đúng cấu hình (không log key, chỉ log `api_key_configured`):

```text
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
[INFO] ts="2026-11-25T10:23:04.980+00:00" logger="agent" event="startup" version="1.0.0" environment="production" port=8080 rate_limit_per_minute=10 daily_budget_usd=1 api_key_configured=true
```

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
