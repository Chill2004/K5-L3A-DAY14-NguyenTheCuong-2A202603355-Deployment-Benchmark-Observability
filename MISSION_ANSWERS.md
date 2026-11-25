# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found

File: `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng code | Vì sao nguy hiểm |
|---|--------------|-----------|------------------|
| 1 | Hardcode secret: `OPENAI_API_KEY` và `DATABASE_URL` (có cả mật khẩu DB) ghi thẳng trong code | 17–18 | Push lên GitHub là lộ key ngay; xoá file sau đó cũng không đủ vì secret vẫn nằm trong lịch sử git. Muốn đổi key phải sửa code và deploy lại |
| 2 | Log ra secret: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Ai đọc được log (đồng nghiệp, dịch vụ gom log, dashboard của cloud) đều lấy được key. Mình đã thấy dòng `Using key: sk-hardcoded-...` trong log khi chạy thật |
| 3 | Config cố định trong code: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Không đổi được hành vi giữa dev/staging/production mà không sửa code. Production chạy luôn với `DEBUG=True` |
| 4 | Dùng `print()` thay cho logging | 33, 38 | Không có level (INFO/ERROR), không có thời gian, không phải JSON nên công cụ gom log không parse hay lọc được. Còn in nguyên câu hỏi và câu trả lời của user ra log |
| 5 | Không có `/health` và `/ready` | 42 | Gọi `GET /health` trả 404. Platform không biết container đã treo để restart, load balancer không biết instance nào sẵn sàng để chia traffic |
| 6 | `host="localhost"` | 51 | Chỉ nhận kết nối từ chính máy đó. Chạy trong container thì bên ngoài không gọi vào được; phải dùng `0.0.0.0` |
| 7 | Port cố định `port=8000` | 52 | Railway/Render cấp cổng qua biến `PORT`. App không đọc biến này thì nghe sai cổng, health check của platform fail và deploy thất bại |
| 8 | `reload=True` | 53 | Chế độ dev: theo dõi file liên tục, tốn CPU, có thể tự restart giữa chừng. Không dùng được nhiều worker |
| 9 | Không xử lý SIGTERM / graceful shutdown | — | Khi platform tắt hoặc deploy bản mới, request đang chạy bị cắt ngang, user nhận lỗi, kết nối DB/Redis không được đóng sạch |

### Exercise 1.2: Chạy bản develop

```bash
curl -i -X POST "http://localhost:8000/ask?question=Hello"
curl -i http://localhost:8000/health
```

Log server:

```text
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.
INFO:     127.0.0.1:54056 - "POST /ask?question=Hello HTTP/1.1" 200 OK
INFO:     127.0.0.1:54068 - "GET /health HTTP/1.1" 404 Not Found
```

Nhận xét: bản develop **chạy được** (`/ask` trả 200) nhưng **chưa production-ready**:

- Secret bị lộ ngay trong log của chính lần chạy này (`Using key: sk-hardcoded-...`).
- `/health` trả 404, nên platform cloud không có cách nào kiểm tra app còn sống.
- App nghe ở `localhost:8000` cố định, nên khi chạy trong container hoặc trên Railway/Render (cổng do biến `PORT` quyết định) sẽ không nhận được request.
- Log là `print()` dạng text, không có level và thời gian, không dùng được với công cụ gom log.

"Chạy được trên máy mình" mới chỉ chứng minh logic đúng, chưa chứng minh app chạy được ở môi trường khác.

### Exercise 1.3: Comparison table

| Feature | Develop | Production | Tại sao quan trọng? |
|---------|---------|------------|---------------------|
| Config | Hằng số trong code (`DEBUG = True`, `MAX_TOKENS = 500`) | Class `Settings` trong `config.py` đọc mọi giá trị bằng `os.getenv(...)` có default; `validate()` dừng app nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` | Một image chạy được ở mọi môi trường, chỉ đổi biến môi trường. Thiếu config bắt buộc thì app báo lỗi ngay lúc khởi động (fail fast) thay vì chạy sai âm thầm |
| Secrets | Key và mật khẩu DB ghi trong code, còn bị in ra log | Đọc từ env, `.env.example` để trống giá trị, log chỉ ghi `question_length` chứ không ghi secret hay nội dung | Không bị lộ khi push code hoặc khi người khác đọc log; đổi key (rotate) không cần sửa code |
| Host / Port | `localhost:8000` cố định | `HOST` mặc định `0.0.0.0`, `PORT` lấy từ env (chạy `PORT=9000 python app.py` thì app nghe ở 9000) | `0.0.0.0` để nhận được request từ ngoài container; `PORT` để platform tự chọn cổng. Thiếu một trong hai thì deploy xong cũng không gọi được |
| Health check | Không có, `GET /health` trả 404 | `GET /health` trả 200 kèm `status`, `uptime_seconds`, `version` | Platform gọi định kỳ; không trả 200 thì tự restart container. Thiếu nó thì app treo mà không ai biết |
| Readiness | Không có | `GET /ready` trả 503 khi `is_ready=False` (đang khởi động hoặc đang tắt), 200 khi sẵn sàng | Load balancer chỉ chia traffic cho instance đã sẵn sàng. Thiếu nó thì request bị gửi vào instance chưa khởi động xong hoặc đang tắt, và user nhận lỗi |
| Logging | `print()` dạng text, in cả secret | Module `logging` có level, mỗi dòng có thời gian (cố gắng ở dạng JSON, xem "Quan sát thêm") | Log có cấu trúc thì dịch vụ gom log (Loki, Datadog, Cloud Logging) parse, lọc và cảnh báo được. Không có level thì không tách được lỗi khỏi thông tin thường |
| Shutdown | Tắt đột ngột | `lifespan` đặt `is_ready=False` rồi log `shutting down gracefully` và `Shutdown complete`; có handler SIGTERM | Khi deploy bản mới hoặc scale down, request đang chạy được làm xong và kết nối được đóng sạch. Thiếu nó thì user bị cắt request giữa chừng |
| Debug / reload | `reload=True` luôn bật | `reload=settings.debug`, chỉ bật khi `DEBUG=true` | Production không tốn tài nguyên theo dõi file, không tự restart bất ngờ |

Chạy bản production: `OPENAI_API_KEY=dummy python app.py`

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":6.9,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T08:07:39.390885+00:00"}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
content-type: application/json

{"ready":true}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

Log server (khởi động, rồi Ctrl+C):

```text
{"time":"2026-11-25 15:03:52,143","level":"INFO","msg":"Starting AI Agent on 0.0.0.0:8000"}
{"time":"2026-11-25 15:03:52,164","level":"INFO","msg":"{"event": "startup", "app": "AI Agent", "version": "1.0.0", "env": "development", "port": 8000}"}
{"time":"2026-11-25 15:03:52,265","level":"INFO","msg":"Agent is ready to serve requests"}
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Shutting down
{"time":"2026-11-25 15:04:10,441","level":"INFO","msg":"Agent shutting down gracefully — finishing in-flight requests..."}
{"time":"2026-11-25 15:04:10,541","level":"INFO","msg":"Shutdown complete"}
```

### Quan sát thêm

- **Log JSON biến mất khi `OPENAI_API_KEY` trống.** Lần chạy đầu (không đặt key) chỉ thấy `WARNING:root:OPENAI_API_KEY not set` và log của uvicorn, không thấy dòng `startup` hay `Agent is ready`. Lý do là `app.py` import `config` trước, và lúc import thì `config.py:45` đã gọi `logging.warning(...)`. Root logger chưa có handler nên Python tự cấu hình nó với format mặc định và level WARNING. Sau đó `logging.basicConfig(...)` ở `app.py:28` không còn tác dụng vì root logger đã có handler (trừ khi truyền `force=True`), nên mọi log INFO bị bỏ qua. Chạy lại với `OPENAI_API_KEY=dummy` (không còn warning) thì log JSON xuất hiện đầy đủ. Bài học: phải cấu hình logging **trước** khi bất kỳ module nào ghi log.
- **Log "JSON" chưa phải JSON hợp lệ.** Dòng `{"time":"...","level":"INFO","msg":"{"event": "startup", ...}"}` có JSON lồng trong `msg` mà không escape dấu `"`, nên `json.loads()` sẽ báo lỗi. Nguyên nhân là format log được ghép bằng chuỗi (`'{"time":"%(asctime)s",...,"msg":"%(message)s"}'`) thay vì dùng `json.dumps`. Ở Part 6, tiêu chí Structured logging yêu cầu mọi dòng log là JSON hợp lệ, nên phải viết một `logging.Formatter` riêng gọi `json.dumps({...})` cho cả bản ghi.
- **Traceback khi bấm Ctrl+C.** Xuất hiện *sau* khi app đã tắt xong (`Shutdown complete`, `Finished server process`). Nguyên nhân là uvicorn 0.30.0 (bản ghim trong requirements) cũ hơn Python 3.14 nên xử lý SIGINT không khớp. Platform cloud tắt container bằng SIGTERM nên không bị ảnh hưởng.
- **`python-dotenv` có trong requirements nhưng không được dùng.** `config.py` không gọi `load_dotenv()`, nên file `.env` vừa copy không thực sự được nạp; app chạy bằng giá trị default của `os.getenv`. Biến môi trường đặt trực tiếp (vd `OPENAI_API_KEY=dummy`, `PORT=9000`) thì có tác dụng.

## Part 2: Docker

### Exercise 2.1: Dockerfile questions

File: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` (dòng 8), bản Python **đầy đủ** dựa trên Debian, có sẵn gcc, header và nhiều công cụ build. Tiện nhưng rất nặng (image cuối 1.67 GB, xem 2.3).
2. **Working directory:** `/app` (dòng 11). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều chạy tương đối với thư mục này; nếu chưa có thì Docker tự tạo.
3. **Vì sao COPY requirements.txt trước:** để tận dụng **layer cache**. Mỗi lệnh trong Dockerfile tạo một layer; Docker chỉ build lại từ layer đầu tiên có input thay đổi. Dependencies (dòng 14–17) ít khi đổi, còn code (`app.py`, dòng 20) đổi liên tục. Đặt `requirements.txt` + `pip install` trước thì khi sửa code, Docker dùng lại layer đã cài package và chỉ copy lại code, build mất vài giây. Nếu `COPY . .` trước rồi mới `pip install`, mỗi lần sửa một dòng code là phải cài lại toàn bộ dependencies.
4. **CMD vs ENTRYPOINT:**
   - `CMD` là lệnh **mặc định**, bị **thay thế hoàn toàn** khi truyền lệnh lúc chạy: `docker run my-agent:develop python -c "print(1)"` sẽ chạy `python -c ...` thay vì `python app.py`.
   - `ENTRYPOINT` là phần **cố định** của lệnh; tham số truyền vào `docker run` được **nối thêm** vào sau nó, không thay thế (muốn đổi phải dùng `--entrypoint`).
   - Hay dùng kết hợp: `ENTRYPOINT` là chương trình, `CMD` là tham số mặc định. Dockerfile này chỉ dùng `CMD ["python", "app.py"]`, ở dạng exec (mảng JSON) để Python là PID 1 và nhận được SIGTERM trực tiếp.

### Exercise 2.2: Build và run

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm --name cp2-develop -p 8000:8000 my-agent:develop
```

```text
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":3.9,"container":true}
```

Bản app này khác Part 1 ở chỗ nghe `0.0.0.0` và đọc `PORT` từ env, nhờ vậy mới gọi được từ bên ngoài container. Nếu vẫn để `host="localhost"` như Part 1 thì `-p 8000:8000` cũng không giúp được, vì app chỉ nhận kết nối từ bên trong chính container.

### Exercise 2.3: Image size comparison

```text
$ docker images my-agent
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   284e8c085983        240MB         57.4MB
my-agent:develop    90f23b006886       1.67GB          426MB
```

- Develop: **1670 MB** (disk usage; 426 MB nén)
- Production: **240 MB** (disk usage; 57.4 MB nén)
- Difference: **giảm 85.6%** ((1670 − 240) / 1670). Tính theo dung lượng nén: giảm 86.5%.

**Multi-stage trong `02-docker/production/Dockerfile`:**

- **Stage 1 `builder`** (dòng 16–29): từ `python:3.11-slim`, cài thêm `gcc` và `libpq-dev` rồi `pip install --user` vào `/root/.local`. Stage này chỉ dùng để build, không được deploy.
- **Stage 2 `runtime`** (dòng 36–72): bắt đầu lại từ một `python:3.11-slim` sạch, chỉ `COPY --from=builder` thư mục package đã cài cùng `main.py` và `utils/`. Ngoài ra tạo user `appuser` (không chạy bằng root), có `HEALTHCHECK`, chạy uvicorn 2 worker.

**Vì sao nhỏ hơn:**

1. Base image `-slim` bỏ bớt gcc, header, tài liệu và nhiều gói Debian của bản đầy đủ. Đây là phần giảm lớn nhất.
2. `gcc`, `libpq-dev`, cache của apt và pip chỉ nằm ở stage builder. Image cuối chỉ chứa layer của stage cuối, nên những công cụ build đó không đi theo.
3. Image nhỏ hơn thì pull/deploy nhanh hơn, và ít package hơn cũng có nghĩa là ít lỗ hổng bảo mật tiềm ẩn hơn.

### Exercise 2.4: Docker Compose stack

```bash
cd 02-docker/production
touch .env.local
docker compose -p k5-day14-docker up -d --build
```

**Sơ đồ:**

```text
             Client (curl)
                  │  http://localhost:8081  (host port → nginx:80)
                  ▼
        ┌──────────────────┐
        │  nginx:alpine    │  reverse proxy + load balancer
        │  rate limit 10r/s│  thêm security headers
        └────────┬─────────┘
                 │ proxy_pass http://agent:8000   (network "internal")
                 ▼
        ┌──────────────────┐
        │  agent (FastAPI) │  build từ Dockerfile production (target runtime)
        │  không mở port ra│  ngoài, chỉ đi được qua Nginx
        └───┬──────────┬───┘
            │          │  depends_on: condition service_healthy
            ▼          ▼
   ┌──────────────┐ ┌──────────────────┐
   │ redis:7      │ │ qdrant v1.9.0    │
   │ :6379        │ │ :6333            │
   │ vol redis_data│ │ vol qdrant_data │
   └──────────────┘ └──────────────────┘
```

**Các service được start:** `agent`, `redis`, `qdrant`, `nginx`, tất cả nằm chung bridge network `internal`.

**Chúng giao tiếp thế nào:**

- Các container gọi nhau bằng **tên service** nhờ DNS nội bộ của Docker (`agent:8000`, `redis://redis:6379/0`, `http://qdrant:6333`), không dùng `localhost`.
- Chỉ `nginx` publish port ra máy host; `agent`, `redis`, `qdrant` không mở port ra ngoài, nên client bắt buộc phải đi qua Nginx.
- `depends_on` với `condition: service_healthy` bắt agent chờ Redis và Qdrant qua healthcheck rồi mới start; Nginx start sau agent.

**Test qua Nginx:**

```text
$ curl -i http://localhost:8081/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block

{"status":"ok","uptime_seconds":27.8,"version":"2.0.0","timestamp":"2026-11-25T08:55:41.549693"}

$ curl -i -X POST http://localhost:8081/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

Log của agent (`docker compose -p k5-day14-docker logs agent`):

```text
INFO:     172.19.0.5:49496 - "GET /health HTTP/1.1" 200 OK
{"time":"2026-11-25 08:55:41,582","level":"INFO","msg":"{"event": "request", "q_len": 21}"}
INFO:     172.19.0.5:49496 - "POST /ask HTTP/1.1" 200 OK
INFO:     127.0.0.1:38182 - "GET /health HTTP/1.1" 200 OK
```

`172.19.0.5` là IP của container Nginx trong network `internal`, chứng tỏ request đi Client → Nginx → Agent. `127.0.0.1` là `HEALTHCHECK` Docker tự gọi bên trong container agent.

**Ghi chú khi chạy:**

- **Cổng 80 bị Windows chặn** (`bind: An attempt was made to access a socket in a way forbidden by its access permissions`). Mình không sửa `docker-compose.yml` mà thêm một file override ngoài repo với `ports: !override ["8081:80"]`, chạy bằng `docker compose -f docker-compose.yml -f <override>.yml up -d`. Vì vậy test ở `localhost:8081` thay vì `localhost`.
- **Đặt `-p k5-day14-docker`** để tên project và image không trùng với stack `production` của Part 5 và Part 7 (README, lưu ý số 7).
- Compose báo `the attribute version is obsolete`: Compose v2 bỏ qua trường `version: "3.9"`, không ảnh hưởng.
- `main.py` của bài này **không thật sự dùng** Redis hay Qdrant (không có dòng nào import hay kết nối), dù compose truyền `REDIS_URL` và `QDRANT_URL`. Stack chỉ minh hoạ cách ghép service. Phải đến Part 5 và Part 6 thì state mới thật sự nằm trong Redis.

## Part 3: Cloud Deployment

Lớp K5 deploy luôn agent Part 6 (`06-lab-complete/`), không deploy app mẫu trong `03-cloud-deployment/` (xem CHECKPOINTS, CP6).

### Exercise 3.1: Railway deployment

- **URL:** https://agent-production-58f1ea7e.up.railway.app
- **Platform:** Railway. Project `day14-agent` gồm service `agent` (build từ Dockerfile của `06-lab-complete/`) và service `Redis`.
- **Chi tiết** (lệnh deploy, biến môi trường, kết quả test): [DEPLOYMENT.md](DEPLOYMENT.md)
- **Screenshot:** [dashboard](screenshots/dashboard.png) · [running](screenshots/running.png) · [test](screenshots/test.png)

4 lệnh tự kiểm của CP6 (mỗi lệnh chỉ in mã HTTP):

```text
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"                         → 200
$ curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"                          → 200
$ curl ... -X POST "$BASE/ask" (không có key)                                      → 401
$ curl ... -X POST "$BASE/ask" -H "X-API-Key: $AGENT_API_KEY"                       → 200
```

Script chấm với URL public: `✅ Public URL: GET https://agent-production-58f1ea7e.up.railway.app/health → 200`.

**Cách đặt biến môi trường trên cloud:** dùng `railway variables --set` cho service `agent`. Key của `AGENT_API_KEY` được sinh ngẫu nhiên và chỉ nằm trên Railway cùng một file trên máy cá nhân, ngoài repo. `REDIS_URL` dùng biến tham chiếu `${{Redis.REDIS_URL}}`: Railway tự điền URL **nội bộ** của service Redis (`redis.railway.internal:6379`, có mật khẩu), nên không phải copy mật khẩu Redis bằng tay và Redis không mở ra Internet. `PORT` không tự đặt: Railway cấp `8080`, và log khởi động cho thấy uvicorn nghe đúng cổng đó nhờ `${PORT:-8000}` trong `CMD`.

**Cách xem logs:** `railway logs --service agent`, hoặc Dashboard → service `agent` → Deployments → View logs. Railway nhận ra log JSON của app và hiển thị thành field có cấu trúc:

```text
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
[INFO] ts="2026-11-25T10:23:04.980+00:00" logger="agent" event="startup" version="1.0.0" environment="production" port=8080 rate_limit_per_minute=10 daily_budget_usd=1 api_key_configured=true
INFO:     100.64.0.1:24708 - "GET /health HTTP/1.1" 200 OK
```

**Ghi chú:** khi chạy CLI, Railway cảnh báo định dạng `railway.toml` (Config as Code) sẽ được thay bằng `.railway/railway.ts`, nhưng file hiện tại vẫn dùng được tới 2026-12-01. Mình giữ `railway.toml` vì script chấm kiểm tra đúng file này.

### So sánh railway.toml và render.yaml

So sánh bản mẫu (`03-cloud-deployment/railway/railway.toml`, `03-cloud-deployment/render/render.yaml`) và bản mình viết cho Part 6 (`06-lab-complete/`):

| Khía cạnh | `railway.toml` | `render.yaml` |
|-----------|----------------|---------------|
| Định dạng, phạm vi | TOML, cấu hình **một service** (service đang deploy). Các service khác (Redis) tạo riêng bằng CLI hoặc dashboard | YAML Blueprint, mô tả **cả hạ tầng** trong một file: nhiều service, database, biến môi trường. Render tạo đủ mọi thứ từ file này |
| Cách build | `[build] builder = "NIXPACKS"` (tự nhận diện Python) ở bản mẫu; `"DOCKERFILE"` ở bản Part 6 | `runtime: python` + `buildCommand: pip install ...` ở bản mẫu; `runtime: docker` + `dockerfilePath` ở bản Part 6 |
| Lệnh chạy | `startCommand = "uvicorn app:app --host 0.0.0.0 --port $PORT"` (bản Part 6 bỏ dòng này, dùng `CMD` của Dockerfile) | `startCommand: uvicorn app:app --host 0.0.0.0 --port $PORT` (với `runtime: docker` thì dùng `CMD`) |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | Khai báo rõ: `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries = 3` | Không có tuỳ chọn; Render tự restart khi health check fail |
| Biến môi trường và secret | **Không nằm trong file**: đặt bằng `railway variables` hoặc dashboard. Tham chiếu chéo service bằng `${{Redis.REDIS_URL}}` | Khai báo **trong file** (`envVars`). Giá trị thường ghi thẳng (`value:`); secret thì `generateValue: true` (Render tự sinh) hoặc `sync: false` (điền tay trên dashboard), không bao giờ ghi giá trị thật |
| Redis | Không khai báo trong file, thêm bằng `railway add --database redis` | Khai báo ngay trong file (`type: redis` ở bản mẫu, `type: keyvalue` ở bản Part 6) và nối vào web service bằng `fromService ... property: connectionString` |
| Region, gói | Không có trong file | `region: singapore`, `plan: free` |
| Auto deploy | `railway up` đẩy code từ máy lên (hoặc nối repo GitHub) | `autoDeploy: true`: tự deploy mỗi khi push lên GitHub |
| Vị trí file | Nằm trong thư mục được `railway up` | Blueprint đọc file từ **gốc repo**, hoặc khai báo `rootDir` cho service nằm trong thư mục con (bản Part 6 dùng `rootDir: 06-lab-complete`) |

**Vì sao khác nhau:** Railway tách **cấu hình build/deploy** (trong file) khỏi **hạ tầng và secret** (CLI, dashboard), nên file ngắn và chỉ lo một service. Render đi theo hướng Infrastructure as Code đầy đủ: một file Blueprint dựng lại được cả hệ thống (web + Redis + biến môi trường), tiện để tái tạo môi trường từ đầu. Cái giá là phải cẩn thận để secret không lọt vào file, vì vậy mới có `generateValue` và `sync: false`.

### Exercise 3.3: Cloud Run CI/CD pipeline

`cloudbuild.yaml` là pipeline Cloud Build gồm 4 bước, bước sau chờ bước trước xong (`waitFor`):

1. **test:** trong image `python:3.11-slim`, cài requirements + pytest rồi chạy `pytest tests/`. Test fail thì pipeline dừng, không build.
2. **build:** `docker build` image và gắn 2 tag: `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` (mỗi commit một bản, dễ rollback) và `:latest`; `--cache-from :latest` để dùng lại layer cũ cho nhanh.
3. **push:** đẩy cả hai tag lên Container Registry.
4. **deploy:** `gcloud run deploy` bằng image đúng `$COMMIT_SHA` lên region `asia-southeast1`: public (`--allow-unauthenticated`), từ 1 đến 10 instance, 512Mi RAM / 1 CPU, timeout 60s. `OPENAI_API_KEY` lấy từ **Secret Manager** (`--set-secrets`) chứ không ghi trong file.

`service.yaml` mô tả cùng service đó dưới dạng khai báo (Knative), dùng với `gcloud run services replace`:
- `minScale: 1` giữ sẵn một instance để tránh cold start; `maxScale: 10`.
- `containerConcurrency: 80`: mỗi instance xử lý tối đa 80 request đồng thời, vượt thì Cloud Run tự thêm instance.
- Giới hạn tài nguyên (1 CPU / 512Mi).
- Secret `OPENAI_API_KEY`, `AGENT_API_KEY` lấy từ Secret Manager.
- `livenessProbe` gọi `/health` mỗi 30 giây; `startupProbe` gọi `/ready` để chỉ nhận traffic khi app đã sẵn sàng.

Tóm lại: **push lên main → test → build image → push lên registry → deploy lên Cloud Run**, secret nằm trong Secret Manager.

Hai chỗ trong file mẫu sẽ lỗi nếu chạy thật:
- Thư mục `03-cloud-deployment/production-cloud-run/` **không có `tests/`** (cũng không có Dockerfile hay requirements), nên bước test sẽ fail ngay.
- `service.yaml` tự khai báo biến `PORT`, nhưng `PORT` là biến dành riêng mà Cloud Run tự đặt theo `containerPort`; tự khai báo sẽ bị Cloud Run từ chối.

## Part 4: API Security

### Exercise 4.1: API Key authentication

File: `04-api-gateway/develop/app.py`. Chạy: `AGENT_API_KEY=secret-key-123 python app.py`

**API key được check ở đâu?**
- `api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36) đọc header `X-API-Key`.
- Hàm `verify_api_key` (dòng 39–54) kiểm tra key.
- Hàm này được gắn vào endpoint bằng `Depends(verify_api_key)` (dòng 70). FastAPI chạy dependency **trước** khi vào thân hàm `/ask`, nên request sai key không bao giờ chạm tới LLM. `/` và `/health` không gắn dependency nên vẫn public.

**Sai key thì sao?** Thiếu header thì trả **401** `Missing API key`; có header nhưng sai key thì trả **403** `Invalid API key`. Lưu ý: Part 6 yêu cầu **cả hai trường hợp đều 401**, nên không được copy nguyên logic này.

**Rotate key thế nào?** Key đọc từ biến môi trường `AGENT_API_KEY` (dòng 35), nên chỉ cần đặt giá trị mới trên platform rồi restart hoặc redeploy, không phải sửa code. Bản này chỉ so với **một** key, nên lúc đổi key mọi client cũ bị 401 ngay. Muốn rotate không gián đoạn thì cho phép nhiều key cùng lúc (vd `AGENT_API_KEYS=new,old`), chuyển client sang key mới, rồi mới bỏ key cũ.

**Vấn đề còn lại:** có key mặc định `"demo-key-change-in-production"` (dòng 35). Quên đặt env thì app vẫn chạy với key ai cũng biết. Ngoài ra dòng 91 **in key ra stdout** lúc khởi động, lặp lại lỗi lộ secret ra log của Part 1.

```text
$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

$ curl -i http://localhost:8000/ask -X POST -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT authentication

File: `04-api-gateway/production/auth.py`. Endpoint lấy token là `POST /auth/token`, tài khoản `student` / `demo123`.

**JWT flow:**

1. Client gửi username/password tới `POST /auth/token`. `authenticate_user` (dòng 70–75) so với `DEMO_USERS`; sai thì trả 401.
2. `create_token` (dòng 35–43) tạo payload `{sub, role, iat, exp = now + 60 phút}` rồi **ký** bằng HS256 với `JWT_SECRET`. Token gồm 3 phần `header.payload.signature`.
3. Client gửi token ở mỗi request: `Authorization: Bearer <token>`.
4. `verify_token` (dòng 46–67) gọi `jwt.decode`, kiểm tra chữ ký và hạn dùng: không có token thì 401, hết hạn thì 401, chữ ký sai hoặc token giả thì 403. Hợp lệ thì lấy ra `username` và `role` để dùng tiếp (rate limit theo role).

Server **không cần tra database** ở mỗi request: thông tin user nằm sẵn trong token, và chữ ký chứng minh token do server phát hành, không bị sửa. Đổi lại, token đã phát thì không thu hồi được trước khi hết hạn (trừ khi có blacklist), và payload chỉ được **mã hoá base64 chứ không bị giấu**, nên không được bỏ thông tin nhạy cảm vào đó. `JWT_SECRET` cũng có giá trị mặc định trong code (dòng 22); production phải đặt bằng env.

```text
$ curl -i http://localhost:8000/auth/token -X POST -H "Content-Type: application/json" -d '{"username": "student", "password": "demo123"}'
HTTP/1.1 200 OK
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY

{"access_token":"eyJ...<masked>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer eyJ...<masked>"}

$ curl -i http://localhost:8000/auth/token -X POST -H "Content-Type: application/json" -d '{"username": "student", "password": "nope"}'
HTTP/1.1 401 Unauthorized

{"detail":"Invalid credentials"}

$ curl -i http://localhost:8000/ask -X POST -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i http://localhost:8000/ask -X POST -H "Authorization: Bearer abc.def.ghi" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 403 Forbidden

{"detail":"Invalid token."}

$ curl -i http://localhost:8000/ask -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK

{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

### Exercise 4.3: Rate limiting

File: `04-api-gateway/production/rate_limiter.py`

- **Algorithm:** **sliding window**. Mỗi user có một `deque` chứa timestamp các request trong 60 giây gần nhất. Mỗi lần check, các timestamp cũ hơn `now - 60s` bị bỏ khỏi đầu deque (dòng 39–40); nếu số còn lại đã đạt `max_requests` thì trả 429, ngược lại thêm `now` vào deque. Cửa sổ trượt theo từng request nên không bị lỗi "dồn request ở ranh giới phút" như fixed window. (Docstring gọi là *Sliding Window Counter*, nhưng vì lưu từng timestamp nên đúng ra là *sliding window log*.)
- **Limit:** user thường **10 request/phút** (`rate_limiter_user`, dòng 86); admin **100 request/phút** (`rate_limiter_admin`, dòng 87).
- **Bypass cho admin:** `app.py` dòng 141 chọn limiter theo `role` lấy từ JWT: `rate_limiter_admin if role == "admin" else rate_limiter_user`. Admin **không được bỏ qua hoàn toàn**, mà dùng một giới hạn cao hơn (100/phút). Thử với `teacher` (role admin): 12 request liên tiếp đều 200. Vì `role` nằm trong token có chữ ký, user thường không tự sửa thành admin được.
- **Hạn chế:** state nằm trong RAM của process. Restart là mất, và chạy nhiều instance hoặc worker thì mỗi cái đếm riêng (giới hạn thực tế thành 10 × số instance). Part 6 phải chuyển sang Redis.

Vòng lặp 20 request với token `student`:

```text
Request 1 -> 200 ... "requests_remaining":8
Request 2 -> 200
...
Request 9 -> 200 ... "requests_remaining":0
Request 10 -> 429 {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 11 -> 429
...
Request 20 -> 429
```

Request thứ 10 của vòng lặp đã bị 429 vì request `Explain JWT` ở bài 4.2 cũng được tính: tổng cộng đúng 10 request thành công trong 60 giây, request thứ 11 bị chặn.

```text
$ curl -i ... (request tiếp theo)
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795597325
retry-after: 59
content-type: application/json

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}

--- teacher (role admin), 12 request liên tiếp
200 200 200 200 200 200 200 200 200 200 200 200
```

**Quan sát thêm khi chạy:**
- Field `budget_remaining_usd` trong response `/ask` thực ra trả về **số tiền đã dùng** (`usage.total_cost_usd`, `app.py` dòng 160), không phải số còn lại. `/me/usage` mới trả đúng `budget_remaining_usd: 0.999812`.
- Middleware `security_headers` cố xoá header `server` (dòng 84–85) nhưng response vẫn có `server: uvicorn`, vì uvicorn thêm header này ở tầng giao thức, sau khi middleware đã chạy. Muốn ẩn thì chạy uvicorn với `server_header=False` (hoặc `--no-server-header`).

### Exercise 4.4: Cost guard implementation

**Yêu cầu:** mỗi user $10/tháng, theo dõi trong Redis, reset đầu tháng.

```python
import os
from datetime import datetime, timezone
import redis

r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "10"))

def check_budget(user_id: str, estimated_cost: float) -> bool:
    """True nếu còn budget (và đã trừ estimated_cost), False nếu vượt."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"budget:{user_id}:{month}"               # key mới mỗi tháng => tự "reset đầu tháng"
    new_total = r.incrbyfloat(key, estimated_cost)  # cộng nguyên tử, an toàn khi nhiều instance
    if new_total == estimated_cost:
        r.expire(key, 32 * 24 * 3600)               # key mới tạo: tự xoá sau 32 ngày
    if new_total > MONTHLY_BUDGET_USD:
        r.incrbyfloat(key, -estimated_cost)         # hoàn lại phần vừa cộng
        return False
    return True
```

**Cách làm:**

1. **Key theo user và tháng:** `budget:<user_id>:<YYYY-MM>`. Sang tháng mới thì tên key đổi, tổng chi tự bắt đầu lại từ 0, không cần cron job reset. Dùng giờ UTC để mọi instance thống nhất ranh giới tháng.
2. **`INCRBYFLOAT` trước rồi mới kiểm tra.** Lời giải mẫu trong CODE_LAB làm `GET` → so sánh → `INCRBYFLOAT`. Khi nhiều instance cùng xử lý request của một user, hai request có thể cùng `GET` thấy còn budget rồi cùng cộng, dẫn tới vượt ngân sách (race condition). `INCRBYFLOAT` là thao tác nguyên tử của Redis: cộng và trả về tổng mới trong một bước, nên mỗi request thấy một tổng khác nhau. Nếu vượt thì trừ lại phần vừa cộng.
3. **`EXPIRE` 32 ngày** khi key vừa được tạo, để key của các tháng cũ tự bị xoá, Redis không phình mãi.
4. **Lưu trong Redis chứ không trong RAM**, nên state được chia sẻ giữa mọi instance và không mất khi restart (khác với `CostGuard` in-memory của `cost_guard.py`).
5. Ở endpoint: gọi `check_budget(user, estimated_cost)` **trước** khi gọi LLM; nếu `False` thì `raise HTTPException(402, "Monthly budget exceeded")`.

**Test với Redis thật** (`docker run -d --rm -p 6379:6379 redis:7-alpine`):

```text
call 1: +$4.0  -> ALLOW         spent=4.00
call 2: +$4.0  -> ALLOW         spent=8.00
call 3: +$3.0  -> BLOCK (402)   spent=8.00     # 8 + 3 > 10, đã hoàn lại
call 4: +$1.5  -> ALLOW         spent=9.50
call 5: +$0.5  -> ALLOW         spent=10.00    # đúng bằng 10 vẫn cho phép
key: budget:alice:2026-11 | TTL (days): 32.0
bob (user khác): True                           # budget tách riêng từng user
```

**Vì sao cần cả rate limit lẫn cost guard:** rate limit bảo vệ **tốc độ** (chống spam, chống một user làm nghẽn server), còn cost guard bảo vệ **tiền**. Chỉ có rate limit thì user vẫn có thể gửi đều 10 request/phút suốt cả tháng, mỗi request là một câu hỏi dài tốn nhiều token, và hoá đơn vẫn tăng không giới hạn. Chỉ có cost guard thì một user có thể bắn hàng nghìn request rẻ trong một giây làm sập server. Hai lớp chặn hai rủi ro khác nhau.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

File: `05-scaling-reliability/develop/app.py`

**Hai endpoint:**

- **`GET /health` (liveness, dòng 104–144):** trả 200 khi process còn chạy và phản hồi được, kèm `uptime_seconds`, `version` và một check bộ nhớ đơn giản (`psutil`, trên 90% thì báo `degraded`). Câu hỏi nó trả lời là *"process có còn sống không?"*. Không trả 200 hoặc timeout thì platform **restart container**.
- **`GET /ready` (readiness, dòng 147–168):** trả 200 khi `_is_ready=True`, trả **503** khi đang khởi động (chưa chạy xong lifespan startup) hoặc đang tắt (lifespan shutdown đặt lại `_is_ready=False`). Câu hỏi nó trả lời là *"có nên gửi traffic vào instance này không?"*. Không trả 200 thì load balancer **ngừng gửi request** vào instance đó, nhưng **không restart** nó.

**Khác nhau ở đâu và vì sao phải tách:** liveness không được phụ thuộc vào dịch vụ bên ngoài. Nếu `/health` cũng kiểm tra Redis, thì khi Redis chết **mọi** instance sẽ báo không sống, platform restart hết tất cả, mà restart cũng không làm Redis sống lại, nên thành một vòng restart vô ích. Readiness mới là chỗ để kiểm tra dependency: Redis chết thì instance tạm rút khỏi load balancer, Redis sống lại thì tự quay lại nhận traffic. Đây cũng là lý do Part 6 yêu cầu `/health` trả 200 khi mất Redis còn `/ready` trả 503.

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok","uptime_seconds":0.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:06:17.445912+00:00","checks":{"memory":{"status":"ok","used_percent":11.6}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
content-type: application/json

{"ready":true,"in_flight_requests":1}
```

`in_flight_requests` là 1 chứ không phải 0, vì middleware `track_requests` (dòng 72–81) đếm luôn chính request `/ready` đang được xử lý.

### Exercise 5.2: Graceful shutdown

**Signal handler** (theo đúng cách ở Part 6 Step 7, có gọi lại handler cũ):

```python
import signal, logging
logger = logging.getLogger(__name__)
_previous = signal.getsignal(signal.SIGTERM)

def shutdown_handler(signum, frame):
    """SIGTERM từ orchestrator: chỉ ghi log, việc tắt để uvicorn làm."""
    logger.info("Received SIGTERM, starting graceful shutdown")
    if callable(_previous):
        _previous(signum, frame)

signal.signal(signal.SIGTERM, shutdown_handler)
```

Bốn bước của graceful shutdown, và ai làm bước nào trong app này:

1. **Ngừng nhận request mới:** uvicorn đóng socket đang nghe ngay khi nhận SIGTERM (log `Shutting down`). Gọi `curl` ngay sau đó thì bị `connection refused`.
2. **Xử lý xong request đang chạy:** uvicorn chờ các kết nối đang mở hoàn thành, tối đa `timeout_graceful_shutdown=30` giây (dòng 198).
3. **Đóng kết nối và dọn tài nguyên:** phần sau `yield` trong `lifespan` (dòng 54–66): đặt `_is_ready=False` để `/ready` trả 503, rồi đóng DB/Redis nếu có.
4. **Thoát:** process kết thúc với exit code 0.

**Test** (mock LLM mất khoảng 3 giây, gửi SIGTERM ở giây thứ 0.7 khi request còn đang chạy):

```bash
python app.py & PID=$!
curl -X POST "http://localhost:8000/ask?question=Long%20task" &
sleep 0.7; kill -TERM $PID
```

```text
--- curl result
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
[curl] HTTP 200 after 3.031817s
--- python exit code: 0
--- curl ngay sau khi tắt: connection refused

--- server log
INFO:     Shutting down                                              <- nhận SIGTERM, ngừng nhận request mới
INFO:     127.0.0.1:39224 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK   <- request đang chạy vẫn hoàn thành
INFO:     Waiting for application shutdown.
2026-11-25 16:06:20,608 INFO 🔄 Graceful shutdown initiated...
2026-11-25 16:06:20,608 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [2121]
2026-11-25 16:06:20,608 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

**Kết luận:** request có hoàn thành. Nó trả 200 sau đủ 3 giây dù SIGTERM đến ở giây thứ 0.7, và process thoát với exit code 0.

**Quan sát thêm:**

- Dòng `Received signal 15` của `handle_sigterm` (dòng 175–186) được in **cuối cùng**, sau `Finished server process`. Lý do là uvicorn tạm **thay** handler SIGTERM của app trong lúc chạy; khi nhận tín hiệu, nó tự xử lý graceful shutdown trước, rồi mới khôi phục handler cũ và phát lại tín hiệu cho handler đó. Điều này cho thấy: nếu tự đăng ký handler SIGTERM *sau* khi uvicorn đã chạy (vd trong `lifespan`) mà không gọi lại handler trước đó, thì uvicorn không bao giờ nhận được tín hiệu tắt, và container chỉ chết khi bị SIGKILL sau thời gian chờ.
- Vòng chờ `while _in_flight_requests > 0` trong lifespan (dòng 61–64) **không chạy lần nào**: khi tới bước lifespan shutdown thì uvicorn đã chờ xong mọi request rồi. Hơn nữa vòng này dùng `time.sleep` trong hàm async, sẽ chặn event loop nếu thật sự phải chờ.

### Exercise 5.3: Stateless design

File: `05-scaling-reliability/production/app.py`

- **Anti-pattern:** lưu `conversation_history = {}` trong RAM. Mỗi instance (và mỗi worker của uvicorn) là một process riêng có RAM riêng. User gửi tin 1 vào instance A, tin 2 bị load balancer chuyển sang instance B, và B không biết gì về tin 1. Restart hay deploy bản mới cũng làm mất toàn bộ state.
- **Cách bản production làm:** mọi state nằm trong Redis. `save_session` dùng `SETEX session:<id>` với TTL 1 giờ (dòng 59–65); `load_session` dùng `GET` (dòng 68–73); `append_to_history` đọc, thêm tin, giữ tối đa 20 tin rồi lưu lại (dòng 76–90). Client gửi kèm `session_id`, nên **bất kỳ instance nào** cũng đọc được đúng cuộc hội thoại. Bản thân instance không giữ gì, nên có thể thêm, bớt hay giết instance tuỳ ý.
- **Kiểm chứng:** trong Redis có các key `session:<uuid>`:

```text
$ docker exec k5-day14-scaling-redis-1 redis-cli --scan --pattern 'session:*'
session:8ee43235-cd41-4338-b148-e001e94f6659
session:5b21dbd6-ac39-4144-a8d0-35f1e5e4c09f
session:a0bec139-4ae8-4334-a586-28205ecd585b
...
```

**Điểm yếu của bản mẫu:**

- Nếu lúc khởi động không kết nối được Redis (dòng 35–45), app **lặng lẽ chuyển sang dict trong RAM**, chỉ in ra một dòng cảnh báo. `/ready` vẫn trả 200 vì `USE_REDIS=False` thì không kiểm tra gì. Kết quả là chạy nhiều instance mà mỗi cái giữ state riêng, bị lỗi ngầm, không ai biết. Production nên trả 503 ở `/ready` (hoặc dừng app) khi không có Redis.
- `append_to_history` đọc, sửa rồi ghi cả session. Hai request cùng một session chạy song song trên hai instance có thể ghi đè lên nhau và mất một tin (lost update). Dùng `RPUSH` + `LTRIM` trên một Redis list sẽ an toàn hơn.
- Field `turn` trong response bị lệch 1: nó đếm history *sau khi* đã thêm câu hỏi hiện tại rồi còn `+1`, nên tin thứ 2 báo `turn 3`.

### Exercise 5.4: Load balancing

```bash
cd 05-scaling-reliability/production
touch .env.local
docker compose -p k5-day14-scaling up -d --build --scale agent=3
```

```text
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 7 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-2   Up 6 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-3   Up 6 seconds (healthy)    8000/tcp
k5-day14-scaling-nginx-1   Up 6 seconds              0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 17 seconds (healthy)   6379/tcp
```

10 request `POST /chat` qua Nginx (cổng 8080), in `served_by` trong body và header `X-Served-By` do Nginx thêm:

```text
instance-d6dfec  | X-Served-By: 172.19.0.3:8000      (agent-1)
instance-6ed1ce  | X-Served-By: 172.19.0.4:8000      (agent-2)
instance-7f8d77  | X-Served-By: 172.19.0.5:8000      (agent-3)
instance-d6dfec  | X-Served-By: 172.19.0.3:8000
instance-6ed1ce  | X-Served-By: 172.19.0.4:8000
instance-7f8d77  | X-Served-By: 172.19.0.5:8000
instance-d6dfec  | X-Served-By: 172.19.0.3:8000
instance-6ed1ce  | X-Served-By: 172.19.0.4:8000
instance-7f8d77  | X-Served-By: 172.19.0.5:8000
instance-d6dfec  | X-Served-By: 172.19.0.3:8000
```

**Nhận xét:**

- **Phân tán:** Nginx chia đều theo **round-robin** (1 → 2 → 3 → 1 ...). Tên `agent` trong `upstream { server agent:8000; }` được DNS nội bộ của Docker phân giải ra cả 3 IP của 3 container.
- **Một instance chết:** thử dừng `agent-2` khi đang chat (xem 5.5). Log Nginx ghi `connect() failed (113: Host is unreachable) ... upstream: "http://172.19.0.4:8000/chat"`, rồi nhờ `proxy_next_upstream error timeout http_503` Nginx tự gửi lại request sang instance khác. Client vẫn nhận 200 và không biết có instance vừa chết.
- **Hạn chế:** Nginx chỉ phân giải tên `agent` **một lần lúc khởi động**. Nếu scale lên thêm instance sau khi Nginx đã chạy, Nginx không thấy instance mới cho tới khi reload. Dòng `resolver 127.0.0.11 valid=10s` không có tác dụng với `upstream` khai báo tĩnh như thế này.

### Exercise 5.5: Test stateless

```text
$ python test_stateless.py
Session ID: d41481e9-7f86-418a-8226-a945dab04bcb

Request 1: [instance-d6dfec]   Q: What is Docker?
Request 2: [instance-6ed1ce]   Q: Why do we need containers?
Request 3: [instance-7f8d77]   Q: What is Kubernetes?
Request 4: [instance-d6dfec]   Q: How does load balancing work?
Request 5: [instance-6ed1ce]   Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-7f8d77', 'instance-d6dfec', 'instance-6ed1ce'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  ...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu của **cùng một session** được 3 instance khác nhau trả lời luân phiên, nhưng `GET /chat/<id>/history` vẫn có đủ 10 tin (5 câu hỏi + 5 trả lời) theo đúng thứ tự. Mỗi instance đọc history từ Redis trước khi trả lời và ghi lại sau khi trả lời, nên không instance nào cần "nhớ" gì.

Script này không tự tắt instance nào (README, lưu ý số 7). Để kiểm tra đúng yêu cầu ban đầu của bài ("kill random instance, conversation vẫn còn không?"), mình tự dừng `agent-2` giữa cuộc hội thoại:

```text
msg 1: 200 served_by instance-7f8d77        ("My name is Cuong")
$ docker stop k5-day14-scaling-agent-2       (agent-2 = instance-6ed1ce)
msg 2: 200 served_by instance-d6dfec | session 7150ddc7
msg 3: 200 served_by instance-7f8d77 | session 7150ddc7
msg 4: 200 served_by instance-7f8d77 | session 7150ddc7
msg 5: 200 served_by instance-d6dfec | session 7150ddc7
msg 6: 200 served_by instance-7f8d77 | session 7150ddc7
msg 7: 200 served_by instance-d6dfec | session 7150ddc7
history count: 14 | first msg: My name is Cuong
```

Sau khi `agent-2` chết, chỉ còn 2 instance phục vụ, **không request nào lỗi**, và history vẫn đủ 14 tin, bắt đầu bằng đúng câu "My name is Cuong" đã gửi trước khi kill. Msg 3 và 4 cùng do `instance-7f8d77` trả lời: đó là lúc Nginx thử gửi tới IP của `agent-2`, thất bại, và chuyển sang instance kế tiếp. Nếu history lưu trong RAM của `agent-2` thì cuộc hội thoại đã mất cùng container đó.

Ghi chú khi chạy: lệnh `docker compose stop agent-2` không dừng được container (`agent-2` không phải tên service; service tên là `agent`), nên phải dùng `docker stop k5-day14-scaling-agent-2`. Xong thì tắt stack bằng `docker compose -p k5-day14-scaling down`.

## Part 6: Final Project

Chạy `python check_production_ready.py` (bản đầy đủ, có Docker) trong `06-lab-complete/`, trên WSL2 Ubuntu với Python 3.11:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số dòng chi tiết đáng chú ý trong output: image **273 MB**; `429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)`; restart agent vẫn bị 429; `402 ở request thứ 1`; `15 dòng JSON`; SIGTERM khi đang có request thì request vẫn 200, exit code 0; `docker stop` xong trong 0.9s với exit code 0.

### Cách làm từng phần

| File | Làm gì | Vì sao |
|------|--------|--------|
| `app/config.py` | `Settings` đọc mọi giá trị bằng `os.getenv` (PORT, ENVIRONMENT, LOG_LEVEL, AGENT_API_KEY, REDIS_URL, RATE_LIMIT_PER_MINUTE, DAILY_BUDGET_USD, giá token) | 12-Factor: một image chạy mọi môi trường. `AGENT_API_KEY` **không có default**, nên quên đặt key thì app từ chối tất cả request, không chạy với một key ai cũng biết |
| `app/redis_client.py` | `redis.Redis.from_url(..., socket_connect_timeout=1, socket_timeout=1)`; `redis_healthy()` ping và bắt `RedisError` | `from_url` không kết nối ngay, nên container khởi động được khi chưa có Redis. Timeout ngắn để Redis chết thì lỗi nhanh thay vì treo request |
| `app/auth.py` | `APIKeyHeader("X-API-Key", auto_error=False)`, thiếu hoặc sai đều trả **401**; so sánh bằng `hmac.compare_digest` | `auto_error=False` để FastAPI không tự trả 403/422. `compare_digest` so sánh trong thời gian không đổi, chống dò key bằng cách đo thời gian phản hồi |
| `app/rate_limiter.py` | Sliding window 60s bằng sorted set `ratelimit:<sha256(key)>`: trong một `MULTI/EXEC` chạy `ZREMRANGEBYSCORE` → `ZADD` → `ZCARD` → `EXPIRE`; vượt thì `ZREM` request vừa thêm và trả 429 kèm `Retry-After` tính từ request cũ nhất | State trong Redis nên 2 worker và nhiều instance đếm chung, restart không mất. Transaction để worker khác không chen giữa lúc đếm. Request bị chặn không tính vào quota. Redis chỉ lưu hash của key, không lưu key gốc |
| `app/cost_guard.py` | Key `cost:YYYY-MM-DD` (UTC). `check_budget()`: tổng hôm nay >= `DAILY_BUDGET_USD` thì 402. `record_cost()`: `INCRBYFLOAT` + `EXPIRE` 2 ngày | Sang ngày mới key đổi, tổng tự về 0 mà không cần cron. `INCRBYFLOAT` là thao tác nguyên tử nên không mất số khi nhiều worker cùng ghi |
| `app/main.py` | `JsonFormatter` dùng `json.dumps` cho cả bản ghi, gắn vào logger `agent` riêng; middleware log mỗi request (method, path, status, ms, `X-Request-ID`); `/health` không đụng Redis; `/ready` trả 503 khi Redis lỗi hoặc đang tắt; `/ask` = `Depends(verify_api_key)` → rate limit → budget → LLM → `record_cost`; handler `RedisError` → 503, `Exception` → 500 chung chung | Log JSON hợp lệ, khác Part 1 vốn ghép chuỗi làm JSON lồng không escape. Logger riêng không đụng logger của uvicorn. Không log nội dung câu hỏi hay API key. Lỗi trả mã rõ ràng, không lộ stack trace |
| Graceful shutdown | Dùng `lifespan`: sau `yield` thì đặt `shutting_down=True` (để `/ready` trả 503), log `shutdown`, đóng kết nối Redis. **Không** tự đăng ký handler SIGTERM | Thí nghiệm ở Part 5 cho thấy uvicorn đã tự xử lý SIGTERM (ngừng nhận request mới, chờ request đang chạy xong). Tự ghi đè handler mà không gọi lại handler cũ thì process không bao giờ tắt |
| `Dockerfile` | Builder `python:3.11-slim` cài requirements vào `/opt/venv`; runtime `python:3.11-slim` chỉ copy venv + `app/` + `utils/`, user `app` (non-root), `HEALTHCHECK` gọi `/health` theo `$PORT`, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000} --workers 2"]` | Venv ở đường dẫn cố định nên không gặp lỗi `PYTHONUSERBASE` như khi dùng `pip --user`. `exec` để uvicorn là PID 1 và nhận SIGTERM trực tiếp, nên `docker stop` xong trong 0.9s thay vì bị SIGKILL sau 10s |
| `docker-compose.yml` | `agent` (build, `REDIS_URL=redis://redis:6379/0`, `env_file .env` với `required: false`, `depends_on: redis: condition: service_healthy`) + `redis:7-alpine` (healthcheck `redis-cli ping`, AOF + volume) | Agent chỉ start khi Redis đã healthy; volume giữ rate limit và chi phí khi Redis restart |
| `.dockerignore` | Loại `.env*` (giữ `.env.example`), `__pycache__`, `venv`, `.git`, `benchmark-observability/`, tài liệu, script chấm | Không đưa secret vào image, build context nhỏ |
| `railway.toml` / `render.yaml` | Railway: `builder = "DOCKERFILE"`, `healthcheckPath = "/health"`. Render: `type: web`, `runtime: docker`, `healthCheckPath: /health`, `AGENT_API_KEY` dùng `generateValue: true`, `REDIS_URL` lấy từ service Key Value | Không ghi secret trong file config; port do platform cấp qua `$PORT` |

### Test thêm bằng `docker compose` (ngoài script chấm)

Chạy `docker compose up -d --build` với một API key ngẫu nhiên truyền qua biến môi trường (không ghi vào file):

```text
$ GET /health                       → 200 {"status":"ok","version":"1.0.0","environment":"development","uptime_seconds":0.9}
$ GET /ready                        → 200 {"status":"ready","redis":"ok"}
$ POST /ask (no key)                → 401 {"detail":"Invalid or missing API key. Include header: X-API-Key: <key>"}
$ POST /ask (wrong key)             → 401 {"detail":"Invalid or missing API key. Include header: X-API-Key: <key>"}
$ POST /ask (correct key)           → 200 {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":5,"output_tokens":20,"cost_usd":1.275e-05}}
$ POST /ask {"invalid":"data"}      → 422 {"detail":[{"type":"missing","loc":["body","question"],"msg":"Field required",...}]}
$ POST /ask (JSON hỏng)             → 422 {"detail":[{"type":"json_invalid",...,"msg":"JSON decode error",...}]}
$ POST /ask {"question":""}         → 422 {"detail":[{"type":"string_too_short",...,"msg":"String should have at least 1 character",...}]}

Rate limit (RATE_LIMIT_PER_MINUTE=10), 12 request liên tiếp:
200 200 200 200 200 200 200 200 200 429 429 429      (+1 request "correct key" ở trên = 10 request thành công)

$ docker compose stop redis
$ GET /health (redis down)          → 200    liveness không phụ thuộc Redis
$ GET /ready  (redis down)          → 503 {"detail":"Redis not reachable"}
$ POST /ask   (redis down)          → 503 {"detail":"Dependency unavailable, try again later"}  + Retry-After: 5
$ docker compose start redis
$ GET /ready  (redis back)          → 200    tự phục hồi, không cần restart agent

Key trong Redis: ratelimit:0dc366587e947675 (hash, không phải API key gốc), cost:2026-11-25
Số lần API key xuất hiện trong log agent: 0
```

Log của app (mỗi dòng là một JSON object):

```text
{"ts": "2026-11-25T09:21:58.490+00:00", "lvl": "INFO", "logger": "agent", "event": "llm_call", "question_chars": 6, "input_tokens": 2, "output_tokens": 17, "cost_usd": 1.05e-05}
{"ts": "2026-11-25T09:21:58.500+00:00", "lvl": "INFO", "logger": "agent", "event": "request", "request_id": "d996a11df627", "method": "POST", "path": "/ask", "status": 429, "ms": 1.8}
{"ts": "2026-11-25T09:22:10.781+00:00", "lvl": "ERROR", "logger": "agent", "event": "redis_unavailable", "path": "/ask", "error": "ConnectionError"}
```

**Ghi chú:**

- **Môi trường:** `requirements.txt` ghim `pydantic==2.9.0`, bản này không có wheel dựng sẵn cho Python 3.14 (bản mặc định của Ubuntu 26.04) nên pip phải build từ Rust và thất bại. Mình không đổi `requirements.txt` mà tạo lại venv bằng **Python 3.11** (cài qua `uv`), trùng với `python:3.11-slim` trong Dockerfile để local và container giống nhau.
- **`/ask` khi Redis chết mất khoảng 4 giây** mới trả 503 (client Redis thử lại và phân giải tên `redis` thất bại), dù `/ready` báo 503 gần như ngay. Chấp nhận được vì load balancer đã dựa vào `/ready` để ngừng gửi traffic.
- **Cost guard tính chung cho cả service** (một ngân sách mỗi ngày), đúng yêu cầu của bài: bảo vệ tổng hoá đơn LLM. Muốn giới hạn riêng từng user thì đổi key thành `cost:<user>:<ngày>` như cách làm ở Exercise 4.4.

## AI log

| CP | Hỏi AI gì | Nhận được gì | Tự sửa / tự kiểm tra thế nào |
|----|-----------|--------------|------------------------------|
| CP0 | Kiểm tra môi trường | Phát hiện Docker Desktop chưa bật, WSL chưa có Ubuntu, thiếu pip/venv, chưa bật WSL integration | Tự cài Ubuntu, bật WSL integration, chạy `docker run --rm hello-world` và `os.name == posix` trong Ubuntu |
| CP1 | Nhờ Claude hướng dẫn chạy Part 1, giải thích vì sao log JSON không hiện, và soạn câu trả lời Exercise 1.1–1.3 | Danh sách anti-pattern kèm số dòng; giải thích `logging.warning` trong `config.py` chạy trước `basicConfig`; phát hiện log JSON lồng không hợp lệ; Claude soạn bảng anti-pattern, bảng so sánh và phần quan sát dựa trên output tôi chạy | Tự chạy cả hai bản và chụp output (`/health` 404 ở develop, 200 ở production); kiểm chứng giả thuyết logging bằng `OPENAI_API_KEY=dummy python app.py`; đọc lại từng dòng code được trích để đối chiếu |
| CP2 | Nhờ Claude chạy Part 2 (build 2 image, chạy container, chạy stack Compose) và soạn câu trả lời | Claude chạy các lệnh `docker build/run/compose` trên máy tôi, đo kích thước bằng `docker images`, xử lý lỗi cổng 80 bằng file override sang 8081, soạn câu trả lời 2.1–2.4 và sơ đồ | Số MB lấy từ output `docker images` trên máy tôi; đối chiếu câu trả lời với từng dòng trong 2 Dockerfile và `docker-compose.yml`; kiểm tra IP trong log agent là IP của Nginx |
| CP3 | Nhờ Claude chạy test Part 4 (API key, JWT, vòng lặp rate limit), viết hàm cost guard bằng Redis và soạn câu trả lời | Script chạy cả hai bản trong WSL, output curl đã che token; hàm `check_budget` dùng `INCRBYFLOAT` + key theo tháng, test với Redis container; phát hiện field `budget_remaining_usd` trả sai và header `server` không bị xoá | Đối chiếu mã 401/403/200/429 với code `auth.py`, `rate_limiter.py`; kiểm tra kết quả test cost guard (lần gọi 8+3 bị chặn, TTL 32 ngày); đọc lại lý do dùng `INCRBYFLOAT` thay vì GET rồi SET |
| CP4 | Nhờ Claude chạy Part 5 (health/ready, thử SIGTERM khi đang có request, stack 3 instance, `test_stateless.py`, kill 1 instance) và soạn câu trả lời | Output thật của các test; giải thích vì sao log `Received signal 15` in cuối cùng; phát hiện app lặng lẽ chuyển sang lưu RAM khi không có Redis, field `turn` lệch 1, Nginx chỉ phân giải DNS lúc khởi động. Lần kill đầu bị sai (dùng nhầm `docker compose stop agent-2`), Claude tự phát hiện vì vẫn thấy đủ 3 instance và làm lại bằng `docker stop` | Đối chiếu IP trong `X-Served-By` với lỗi `Host is unreachable` trong log Nginx; kiểm tra request dài vẫn trả 200 sau SIGTERM và exit code 0; kiểm tra history còn đủ 14 tin sau khi kill instance |
| CP5 | Nhờ Claude **viết toàn bộ code Part 6** (`app/*.py`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) và soạn phần giải thích | Claude đọc README "hợp đồng" và toàn bộ `check_production_ready.py` trước khi viết; phát hiện `pydantic==2.9.0` không cài được trên Python 3.14, nên tạo lại venv Python 3.11 bằng `uv`; code đạt `PASS 12/12` ở lần chạy đầy đủ đầu tiên. Không sửa `check_production_ready.py` | Chạy `check_production_ready.py` bản đầy đủ có Docker; tự test thêm bằng `docker compose`: 401/200/422, 429 sau 10 request, tắt Redis thì `/health` 200 còn `/ready` 503, bật lại thì phục hồi; kiểm tra API key không xuất hiện trong log; đọc lại từng file để giải thích được với Lab Coach |
| CP6 | Nhờ Claude deploy agent Part 6 lên Railway, viết `DEPLOYMENT.md`, so sánh `railway.toml`/`render.yaml` và mô tả pipeline Cloud Run | Claude cài Railway CLI, tạo project, Redis, service `agent`, đặt biến (key sinh ngẫu nhiên, lưu ngoài repo, không in ra), `railway up`, tạo domain; chạy 4 lệnh tự kiểm và `--public-url`. Tôi tự đăng nhập Railway | Kiểm tra 4 mã 200/200/401/200 trên URL public; xem log Railway thấy `PORT=8080` và `api_key_configured=true`; đối chiếu bảng so sánh với 2 file config; tự chụp 3 ảnh deploy |
| CP7 | Nhờ Claude chạy Part 7 Bước 1 (metrics, load test 4 mức concurrency, so sánh `MOCK_SLOW_RATE`, eval v1/v2), thêm metric `agent_question_length_chars`, sửa `KNOWLEDGE_BASE`, viết job CI và điền mục 1–3 + phụ lục của `BENCHMARK_REPORT.md` | Toàn bộ file `reports/*.json` do lệnh thật sinh ra; v2 sau khi sửa KB đạt 23/23, không regression. Claude phát hiện ở concurrency 100 nút thắt là công cụ tạo tải (CPU của `load_test.py` khoảng 92 %), không phải agent, bằng cách so latency client với histogram `/metrics` của agent | Rà từng con số trong report với file JSON (sửa một tỉ lệ tính sai 7.8 → 7.6); chạy lại c=100 thêm 3 lần để chắc hiện tượng ổn định; kiểm tra eval cuối in `Quality gate ... ✅ PASS`; không sửa `golden_dataset.jsonl` |
