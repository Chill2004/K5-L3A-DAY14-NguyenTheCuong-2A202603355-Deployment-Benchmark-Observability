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

### Exercise 3.1 / 3.2: Deployment
- URL:
- Screenshot:

### So sánh railway.toml và render.yaml

### Exercise 3.3: Cloud Run pipeline

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

### Exercise 5.1-5.5: Implementation notes

## Part 6: Final Project

```text
(dán phần "📋 Checklist Deliverable" của check_production_ready.py)
```

## AI log

| CP | Hỏi AI gì | Nhận được gì | Tự sửa / tự kiểm tra thế nào |
|----|-----------|--------------|------------------------------|
| CP0 | Kiểm tra môi trường | Phát hiện Docker Desktop chưa bật, WSL chưa có Ubuntu, thiếu pip/venv, chưa bật WSL integration | Tự cài Ubuntu, bật WSL integration, chạy `docker run --rm hello-world` và `os.name == posix` trong Ubuntu |
| CP1 | Nhờ Claude hướng dẫn chạy Part 1, giải thích vì sao log JSON không hiện, và soạn câu trả lời Exercise 1.1–1.3 | Danh sách anti-pattern kèm số dòng; giải thích `logging.warning` trong `config.py` chạy trước `basicConfig`; phát hiện log JSON lồng không hợp lệ; Claude soạn bảng anti-pattern, bảng so sánh và phần quan sát dựa trên output tôi chạy | Tự chạy cả hai bản và chụp output (`/health` 404 ở develop, 200 ở production); kiểm chứng giả thuyết logging bằng `OPENAI_API_KEY=dummy python app.py`; đọc lại từng dòng code được trích để đối chiếu |
| CP2 | Nhờ Claude chạy Part 2 (build 2 image, chạy container, chạy stack Compose) và soạn câu trả lời | Claude chạy các lệnh `docker build/run/compose` trên máy tôi, đo kích thước bằng `docker images`, xử lý lỗi cổng 80 bằng file override sang 8081, soạn câu trả lời 2.1–2.4 và sơ đồ | Số MB lấy từ output `docker images` trên máy tôi; đối chiếu câu trả lời với từng dòng trong 2 Dockerfile và `docker-compose.yml`; kiểm tra IP trong log agent là IP của Nginx |
| CP3 | Nhờ Claude chạy test Part 4 (API key, JWT, vòng lặp rate limit), viết hàm cost guard bằng Redis và soạn câu trả lời | Script chạy cả hai bản trong WSL, output curl đã che token; hàm `check_budget` dùng `INCRBYFLOAT` + key theo tháng, test với Redis container; phát hiện field `budget_remaining_usd` trả sai và header `server` không bị xoá | Đối chiếu mã 401/403/200/429 với code `auth.py`, `rate_limiter.py`; kiểm tra kết quả test cost guard (lần gọi 8+3 bị chặn, TTL 32 ngày); đọc lại lý do dùng `INCRBYFLOAT` thay vì GET rồi SET |
