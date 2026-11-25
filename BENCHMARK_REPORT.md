# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON trong [`reports/`](reports/) (bản gốc ở `06-lab-complete/benchmark-observability/develop/reports/`), CSV và screenshot thật, không ước lượng.

**Họ tên:** Nguyễn Thế Cường
**Ngày chạy:** 2026-11-25
**Môi trường:** Laptop Intel Core i7-10750H (6 nhân / 12 luồng), RAM 16 GB, Windows 11 + WSL2 Ubuntu 26.04 (WSL được cấp 12 vCPU / 7 GB RAM), Python 3.11.18, Docker Desktop (Docker 29.9.3). Agent và công cụ tạo tải chạy **trên cùng một máy**.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Đo ở tải thường, một request mất khoảng 190 ms (p50 ≈ 188–198 ms ở concurrency 1–50) vì có thời gian gọi LLM và bước retrieval. 500 ms chừa khoảng 2.5 lần cho dao động mà vẫn đủ nhanh cho chat. Đặt theo **p95** chứ không theo average để bắt được nhóm user bị chậm (mục 2.2) |
| Error rate `/ask` | < 2 % | Mock LLM có lỗi upstream nền khoảng 1 % (`MOCK_ERROR_RATE=0.01`), giống provider thật thỉnh thoảng trả 503. Ngưỡng 2 % gấp đôi mức nền: vượt là có sự cố thật, không phải nhiễu |
| Accuracy trên golden dataset | ≥ 85 % (quality gate CI), mục tiêu 100 % | 85 % là ngưỡng chặn merge trong CI (`.github/workflows/eval.yml`). Sau khi sửa knowledge base, v2 đạt 100 %, nên mọi thay đổi làm rơi một câu đang đúng sẽ bị bắt bằng `--baseline` (regression) dù accuracy còn trên 85 % |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

Agent v2 (`AGENT_VERSION=v2 PORT=8002 python app.py`, cấu hình mock mặc định: `MOCK_SLOW_RATE=0.03`, `MOCK_ERROR_RATE=0.01`). Mỗi mức 300 request. SLO kiểm tra: p95 ≤ 500 ms, error rate ≤ 2 %.

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.67 | 187.6 | 217.6 | 1701.5 | 1.00 % | ✅ PASS |
| 10 | 37.4 | 190.6 | 221.2 | 1698.6 | 2.33 % | ❌ FAIL (error rate) |
| 50 | 103.5 | 197.8 | 275.3 | 1710.9 | 0.00 % | ✅ PASS |
| 100 | 62.76 | 384.6 | 3479.2 | 3807.6 | 1.00 % | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

- **Từ 1 lên 10: gần tuyến tính** (4.67 → 37.4 req/s, gấp 8 lần) và p50 gần như không đổi (188 → 191 ms). Mock LLM chờ bằng `asyncio.sleep`, nên agent xử lý nhiều request song song mà gần như không tốn CPU. Theo định luật Little, throughput ≈ concurrency / latency ≈ 10 / 0.24 s ≈ 42 req/s, khớp với số đo.
- **Từ 10 lên 50: dưới tuyến tính** (37.4 → 103.5, chỉ gấp 2.8 lần thay vì 5). Một phần vì lần chạy quá ngắn: 300 request ở concurrency 50 chỉ mất 2.9 s, trong khi một request "slow" kéo dài khoảng 1.7 s. Thời gian chạy bị chặn dưới bởi request chậm nhất, nên RPS bị đánh giá thấp. Muốn đo throughput chuẩn cần chạy lâu hơn (`--duration`).
- **Lên 100: RPS giảm** (103.5 → 62.76) và p95 vọt lên 3479 ms. **Nút thắt không nằm ở agent mà ở công cụ tạo tải.** Mình kiểm chứng bằng cách so latency client đo với histogram `http_request_duration_seconds` mà chính agent ghi trong `/metrics` (chạy lại, ghi ra `/tmp` để không đè report):

  | | Client đo (`load_test.py`) | Agent tự đo (`/metrics`) |
  |---|---|---|
  | concurrency 50 | avg 243 ms, p95 298 ms | avg 229 ms, p95 ≤ 300 ms |
  | concurrency 100 | avg 1287 ms, p95 3945 ms | **avg 233 ms, p95 ≤ 300 ms** (97.7 % request ≤ 500 ms) |

  Ở concurrency 100, thời gian agent xử lý mỗi request **không đổi**, nhưng client thấy chậm thêm khoảng 3.6 giây. Theo dõi CPU cho thấy process `load_test.py` (Python + httpx, một event loop) tăng dần lên khoảng 92 % một nhân, còn agent chỉ khoảng 20–50 %. Request phải xếp hàng ngay trong client trước khi được gửi đi. Chạy lại c=100 ba lần đều cho kết quả tương tự (RPS 43–54, p95 3.7–5.2 s), nên đây là hiện tượng ổn định chứ không phải nhiễu.
  
  **Bài học:** khi benchmark phải đối chiếu số đo phía client với metric phía server, và chạy công cụ tạo tải trên máy riêng hoặc dùng công cụ nhẹ hơn (Locust phân tán, k6, wrk). Nếu chỉ nhìn bảng trên mà kết luận "agent chịu được tối đa khoảng 100 req/s" là sai.
- **Error rate ở concurrency 10 là 2.33 %** (7 lỗi 503 trên 300 request) do lỗi ngẫu nhiên 1 % của mock, không liên quan tới tải: mức 50 có 0 lỗi, mức 100 có 1 %. Với chỉ 300 request, kỳ vọng 3 lỗi nhưng ra 7 là dao động thống kê bình thường. SLO về error rate cần đánh giá trên cửa sổ đủ lớn (vd 5–30 phút ở production) thì mới có ý nghĩa.
- **p99 khoảng 1.7 s ở mọi mức** là do khoảng 3 % request "slow" (cộng thêm 1500 ms). Với 300 request, p99 rơi đúng vào nhóm này. Xem mục 2.2.

### 2.2 Tail latency

Agent v2 khởi động lại với từng giá trị `MOCK_SLOW_RATE`, mỗi lần `--requests 300 --concurrency 20`.

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.5 | 215.4 | 225.2 |
| 0.03 (mặc định) | 224.5 | 221.9 | 1689.3 |
| 0.1 | 364.0 | 1689.9 | 1707.1 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **Từ 0 lên 0.03:** avg chỉ tăng **35 ms** (+18 %) và p95 gần như đứng yên (+6.5 ms), nhưng **p99 nhảy từ 225 lên 1689 ms (gấp 7.5 lần)**. 3 % request chậm nằm hoàn toàn trong 5 % cao nhất, nên p95 chưa thấy, chỉ p99 thấy.
- **Từ 0.03 lên 0.1:** khi hơn 5 % request bị chậm, **p95 cũng vọt lên 1690 ms (gấp 7.6 lần)**, trong khi avg mới tăng thành 364 ms. Nhìn avg 364 ms vẫn tưởng "dưới 500 ms, ổn", nhưng thực tế cứ 10 user thì 1 người chờ gần 1.7 giây.
- **Chỉ số nhạy nhất là percentile cao (p99, rồi p95)**, còn average nhạy kém nhất. Average cộng chung một ít request rất chậm với rất nhiều request nhanh, nên nhóm user bị chậm bị "pha loãng" và biến mất trong con số trung bình. SLO phải bảo vệ trải nghiệm của **từng user**, nên đặt theo percentile: "95 % request nhanh hơn 500 ms" là một cam kết đo được. Ở đây SLO p95 ≤ 500 ms báo FAIL đúng ở trường hợp 0.1, đúng lúc nhiều user thật sự bị ảnh hưởng.
- Mỗi request chậm cũng làm RPS giảm (100.9 → 69.0 → 46.4 req/s ở concurrency cố định 20), vì một "slot" song song bị giữ lâu hơn khoảng 8 lần.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Golden dataset 23 câu (`eval/golden_dataset.jsonl`, không sửa). Một câu được tính đúng khi score ≥ 0.6 (tỉ lệ keyword mong đợi xuất hiện trong câu trả lời).

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35 % (1/23) | 91.3 % (21/23) | **100 % (23/23)** |
| Avg tokens / câu | 57.5 | 108.7 | 116.5 |
| Tổng cost (USD) | 0.000410 | 0.000756 | 0.000815 |
| Cost / câu đúng (USD) | 0.00040995 | 0.00003599 | 0.00003543 |
| Latency p50 / p95 (ms) | 155.1 / 189.3 | 176.7 / 212.4 | 194.2 / 213.0 |
| Quality gate | ❌ FAIL (≥ 80 %) | ✅ PASS (≥ 80 %, 0 regression so với v1) | ✅ PASS (≥ 100 %, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02`: "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | Không có tài liệu nào chứa từ khoá của câu hỏi, nên retrieval trả rỗng và v2 rơi về câu trả lời chung chung. Thêm vào `KNOWLEDGE_BASE` tài liệu kích hoạt bởi `["jwt", "json web token"]`: API key là chuỗi bí mật cố định; JWT là **token** có **chữ ký** số, chứa user và thời điểm **hết hạn**, server kiểm chữ ký mà không cần tra database |
| `scaling-03`: "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | Tương tự, knowledge base không có gì về Kubernetes. Thêm tài liệu kích hoạt bởi `["hpa", "horizontal pod autoscaler", "kubernetes", "autoscal"]`: HPA tăng giảm số pod dựa trên **CPU**, **memory** hoặc **custom metrics** (RPS, độ dài hàng đợi) |

Từ khoá kích hoạt được chọn sao cho **không trùng** với câu hỏi nào khác trong dataset. Retrieval chỉ lấy 1 tài liệu có nhiều từ khoá khớp nhất, nên nếu dùng từ khoá chung như `token` hay `scale` thì tài liệu mới có thể "cướp" câu khác (vd `cost-01` đang khớp tài liệu về token) và gây regression. Lần eval cuối với `--baseline reports/eval_v2.json` báo `Câu được cải thiện: 2, Câu bị regression: 0`. Cùng thay đổi được chép sang `production/utils/mock_llm.py` để stack Docker của mục 4 cũng đạt 100 %.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Chất lượng:** v2 có bước retrieval (RAG) nên trả lời đúng 91.3 % so với 4.35 % của v1, tức tăng 87 điểm phần trăm và cải thiện 20 câu, không câu nào bị regression. v1 chỉ đúng câu `basic-01` vì có câu trả lời "deploy" soạn sẵn.
- **Chi phí mỗi câu:** v2 tốn **gấp khoảng 1.9 lần token** mỗi câu (108.7 so với 57.5), vì tài liệu được nhét vào prompt nên input dài hơn và câu trả lời cũng dài hơn. Tổng cost cho 23 câu tăng từ $0.000410 lên $0.000756 (+84 %).
- **Chi phí mỗi câu đúng:** v2 lại **rẻ hơn khoảng 11.4 lần** ($0.000036 so với $0.00041). v1 trả tiền cho 23 câu nhưng chỉ nhận về 1 câu dùng được. Vì vậy "cost / câu đúng" là chỉ số đúng để so hai phiên bản. Nhìn "cost / câu" thì tưởng v1 tiết kiệm, nhưng thực chất v1 là phương án đắt nhất tính trên mỗi kết quả có giá trị.
- **Latency:** v2 chậm hơn khoảng 20 ms ở p50 (155 → 177 ms) và 23 ms ở p95, do bước retrieval (khoảng 20 ms) và prompt dài hơn (latency mock tăng 0.2 ms mỗi token input). Mức này vẫn nằm xa dưới SLO 500 ms.
- **Sau khi sửa KB:** thêm 2 tài liệu làm token trung bình tăng nhẹ (108.7 → 116.5) vì 2 câu trước đó trả lời ngắn chung chung nay có tài liệu dài hơn. Nhưng cost / câu đúng còn giảm thêm chút ít ($0.00003599 → $0.00003543) vì có thêm 2 câu đúng.
- **Kết luận:** chọn v2. Đánh đổi gần 2 lần token và khoảng 20 ms latency để có câu trả lời đúng là xứng đáng.

---

## 4. Observability stack (production)

Stack trong `06-lab-complete/benchmark-observability/production/`, chạy với `-p k5-day14-observability`: agent ×3 sau Nginx, Prometheus, Grafana, Jaeger, Locust. Tải nền suốt các thí nghiệm: Locust headless 30 user (`-u 30 -r 5`), chạy song song với stack.

**Ghi chú khi dựng stack:**

- **Sửa lỗi sẵn có trong `production/Dockerfile`:** agent crash liên tục với `ModuleNotFoundError: No module named 'uvicorn'`. Dockerfile cài package bằng `pip install --user` rồi copy vào `/home/agent/.local`, nhưng user `agent` được tạo với HOME là `/app` (`useradd -d /app`), nên Python tìm package ở `/app/.local`. Đây đúng là lỗi CODE_LAB đã cảnh báo ở Part 6 Step 8. Đã thêm `ENV PYTHONUSERBASE=/home/agent/.local`.
- **Cổng 8080 và 8089 bị Windows giữ.** Sau khi khởi động lại máy, WinNAT/Hyper-V giữ dải `8024–8123` (xem bằng `netsh interface ipv4 show excludedportrange protocol=tcp`). Mình không sửa `docker-compose.yml` mà dùng một file override (`ports: !override`) để đổi Nginx sang `18080` và Locust UI sang `18089`. Locust gọi agent qua `http://nginx` bên trong network nên không bị ảnh hưởng.
- **Unit test alert rules:** `promtool test rules /p/alert_rules_test.yml` báo `SUCCESS`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có event `exception`): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với **2 alert cùng firing** (`AgentHighErrorRate` + `AgentHighLatencyP95`): [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Đọc dashboard khi có tải** (30 user, 3 instance; số lấy từ PromQL cùng lúc chụp ảnh): Traffic khoảng 18.9 req/s, error rate 0.58–1.2 %, p95 khoảng 291–293 ms, avg khoảng 226 ms, 3 instance up, mỗi instance khoảng 6.2 req/s. Input khoảng 1440 token/s, output khoảng 762 token/s. Chi phí khoảng $2.2–4.2/giờ. Trả lời chi tiết 4 câu hỏi của Exercise 7.4 ở phụ lục.

### 4.2 Thí nghiệm "phá hệ thống"

Thời gian đo bằng script: ghi mốc `t0` lúc chạy `docker compose up -d --no-deps --scale agent=3 agent` với biến môi trường mới, rồi gọi `/api/v1/alerts` của Prometheus mỗi 5 giây cho tới khi alert chuyển sang `firing`. Trước mỗi thí nghiệm, cấu hình được đưa về mặc định và chờ các alert về `inactive`.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | pending sau **28 s**, firing sau **88 s** | **Error rate**: 0.6 % → 20.9 %; **LLM calls theo kết quả** (đường `error` tăng). p95 gần như không đổi (290 ms), avg còn **giảm** (238 → 207 ms) vì request lỗi trả về sớm |
| B | `MOCK_SLOW_RATE=0.3` (giữ A) | `AgentHighLatencyP95` | pending sau **32 s**, firing sau **152 s** | **Latency /ask p50/p95/p99**: p95 294 → **1895 ms** (gấp 6.4 lần), avg chỉ 238 → 570 ms (gấp 2.4 lần). Lúc này 2 alert cùng firing (ảnh `prometheus-alert-firing.png`) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (nhưng **đã firing từ trước** ở tải thường) | Không đo được thời gian thật: alert đang firing sẵn từ baseline ($2.43/giờ > ngưỡng $2) | **Cost burn rate**: $2.43 → **$14.52/giờ** chỉ sau 2 phút (cửa sổ `rate[5m]` mới đầy khoảng 40 %, nên khi đầy sẽ tiến tới mức khoảng 16 lần); **LLM latency p95 theo model**: 197 → 497 ms (2.5 lần); p95 `/ask` 291 → 706 ms |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` | pending sau **10 s**, firing sau **40 s** | **Instances up**: `up{instance="172.19.0.4:8000"}` = 0. Trong khoảng 60 s bị pause, Nginx ghi **24 lỗi 504** (`upstream timed out ... upstream: "http://172.19.0.4:8000/ask"`), nhưng panel **Error rate của agent vẫn xanh (0.8 %)** và agent không có series `status="504"` nào |
| E | `AGENT_VERSION=v1` | **Không có** (theo dõi 3 phút) | — | **Retrieval hit ratio**: 100 % → không còn dữ liệu (v1 không gọi retrieval); **Tokens/s**: 2147 → 1075 (input 1404 → 697); bảng **Phiên bản đang chạy**: `v1`. Mọi chỉ số hạ tầng trông **tốt hơn**: p95 291 → 198 ms, cost $2.43 → $1.47/giờ, và alert cost còn **tự tắt** |

**Vì sao không firing ngay lúc đổi cấu hình?** Có 2 lớp chờ cộng lại: (1) cửa sổ `rate(...[1m])` cần khoảng 30 s để chứa đủ dữ liệu mới thì biểu thức mới vượt ngưỡng (giai đoạn *pending*); (2) điều kiện phải đúng liên tục suốt `for` (1 phút với error rate, 2 phút với latency, 30 s với instance down) thì mới *firing*. Vì vậy 28 + 60 ≈ 88 s, 32 + 120 ≈ 152 s, 10 + 30 = 40 s. `for` là cái giá cố ý trả để không báo động giả khi chỉ có một spike ngắn.

**Hai phát hiện ngoài dự kiến:**

1. **`LLMCostBurnRateHigh` đặt ngưỡng sai.** Ở tải thường (30 user, model nhỏ) chi phí đã là $2.2–4.2/giờ, vượt ngưỡng $2, nên alert **firing gần như liên tục**. Khi bật lỗi 20 % (A) hoặc chuyển sang v1 (E), chi phí giảm và alert **lại tự tắt**, tức là sự cố làm hệ thống trông "rẻ hơn". Một alert luôn đỏ sẽ khiến người trực quen tay bỏ qua (alert fatigue), và tới lúc C xảy ra thật thì không ai nhận ra. Ngưỡng nên dựa trên baseline đo được (vd 2–3 lần mức chi phí thường ngày, khoảng $8–10/giờ ở tải này) hoặc gắn với ngân sách ngày.
2. **Thí nghiệm D:** dùng `docker pause` chứ không dùng `docker stop`, vì container bị stop biến mất khỏi Docker DNS, Prometheus (`dns_sd_configs`) coi như target không còn tồn tại chứ không phải "down", nên sẽ không có alert. Lỗi 504 xảy ra ở **Nginx** (chờ quá `proxy_read_timeout 10s`): request chưa bao giờ được agent xử lý xong nên **metric của agent không đếm nó**. Metric chỉ phản ánh những gì chính service đó thấy, nên production cần thêm giám sát ở tầng load balancer (metric/log của Nginx) và synthetic check gọi từ bên ngoài như user thật.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đây là **lỗi chất lượng**, không phải lỗi hạ tầng: agent vẫn trả 200 nhanh và rẻ, chỉ là trả lời sai (eval ở mục 3: v1 đúng 4.35 % so với 91–100 % của v2). Phải đo **đúng/sai** chứ không chỉ đo nhanh/chậm:

1. **Chặn trước khi deploy:** quality gate trong CI (`.github/workflows/eval.yml`) chạy golden dataset với `--baseline`. Đổi sang v1 sẽ làm accuracy rơi từ 100 % xuống khoảng 4 % và 20+ câu regression, nên PR bị chặn ngay.
2. **Eval liên tục trên production:** định kỳ (vd mỗi 15 phút) chạy golden dataset vào chính endpoint đang chạy thật như một synthetic check, export `agent_eval_accuracy` thành metric và đặt alert khi thấp hơn 85 %. Lấy mẫu một phần nhỏ traffic thật để chấm bằng LLM-as-judge hoặc so với đáp án.
3. **Alert trên metric đại diện (proxy) cho chất lượng** mà dashboard đã có: retrieval hit ratio giảm hoặc mất dữ liệu, token/request giảm đột ngột, `agent_info` báo version khác version mong đợi. Mỗi tín hiệu này đều đã thay đổi rõ trong E.
4. **Tín hiệu từ người dùng:** nút 👍/👎, tỉ lệ hỏi lại hoặc bỏ dở, export thành metric để alert khi tỉ lệ 👎 tăng.
5. **Canary:** deploy bản mới cho khoảng 5 % traffic, so sánh accuracy (eval online) và feedback giữa canary với bản đang chạy trước khi tăng lên 100 %.

### 4.3 Debug bằng trace

Lấy qua Jaeger API v3 (`/api/v3/traces?query.service_name=observable-agent`; Jaeger v2 không còn `/api/traces` cũ), xếp theo thời gian giảm dần:

- `trace_id`: `5b5b213a73e05a40b4c971ded5c32733`
- Tổng thời gian: **1724.6 ms** (span gốc `POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1697.0 ms, 98.4 %**). Các span khác: `agent.run` 1722.4 ms (span bọc), `agent.retrieve_context` 25.2 ms (1.5 %)
- Attributes của span LLM: `gen_ai.request.model=mock-llm-small`, `gen_ai.usage.input_tokens=95`, `gen_ai.usage.output_tokens=55`, `llm.cost_usd=4.725e-05`. Câu hỏi dài 54 ký tự, `agent.version=v2`
- **Kết luận:** chậm hoàn toàn nằm ở phía LLM provider (đây là một request rơi vào nhóm "slow" khoảng 3 %, bị cộng thêm 1500 ms), không phải code của agent hay bước retrieval. Cách xử lý đúng là đặt timeout/retry hoặc fallback cho LLM call, hay đổi provider/model, chứ không phải tối ưu code agent.
- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T13:39:46.753039+00:00", "level": "INFO", "service": "observable-agent", "instance": "d0d0aa6bc5ae", "event": "llm_call", "trace_id": "5b5b213a73e05a40b4c971ded5c32733", "span_id": "58b6bfbde828fd5d", "request_id": "ee4c4163142a", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1697.0}
{"ts": "2026-11-25T13:39:46.753400+00:00", "level": "INFO", "service": "observable-agent", "instance": "d0d0aa6bc5ae", "event": "http_request", "trace_id": "5b5b213a73e05a40b4c971ded5c32733", "span_id": "58b6bfbde828fd5d", "request_id": "ee4c4163142a", "method": "POST", "route": "/ask", "status": 200, "ms": 1723.6}
```

**Trace lỗi** `9c3925f2594bf95c0f528142a6eb89e9` (90.3 ms, trả **503**): cả 3 span `POST /ask`, `agent.run`, `chat mock-llm-small` có status ERROR (`code: 2`). Span `chat mock-llm-small` (73.5 ms) có event **`exception`**: `exception.message = "Upstream LLM error: 503 Service Unavailable (mock)"`, kèm stacktrace tới `app/main.py` line 153 (`mock_llm.generate`). Log tương ứng:

```json
{"ts": "2026-11-25T13:40:57.997587+00:00", "level": "INFO", "service": "observable-agent", "instance": "3477cb30af32", "event": "llm_error", "trace_id": "9c3925f2594bf95c0f528142a6eb89e9", "span_id": "c173d18649dd0519", "request_id": "31f426608e66", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-25T13:40:57.997816+00:00", "level": "INFO", "service": "observable-agent", "instance": "3477cb30af32", "event": "http_request", "trace_id": "9c3925f2594bf95c0f528142a6eb89e9", "span_id": "c173d18649dd0519", "request_id": "31f426608e66", "method": "POST", "route": "/ask", "status": 503, "ms": 89.9}
```

Request lỗi chỉ mất 90 ms so với khoảng 190 ms của request thành công, vì mock trả lỗi sau khoảng nửa thời gian. Điều này giải thích vì sao avg **giảm** trong thí nghiệm A.

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Nguồn: `benchmark-results/scale_1_stats.csv`, `benchmark-results/scale_3_stats.csv` (dòng `Aggregated`, gồm `POST /ask` và `GET /health`; dòng riêng `POST /ask` ở cột cuối).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.34 | 190 | 300 (`/ask`: 320) | 1700 | 72 / 7813 (0.92 %) |
| 3 | 66.12 | 190 | 220 (`/ask`: 230) | 1700 | 76 / 7903 (0.96 %) |

Số request `/ask` mỗi instance nhận được trong lần chạy (Prometheus `increase(http_requests_total[2m])`): scale 1 thì 1 instance nhận 7297; scale 3 thì 2403 / 2448 / 2414, **chia đều** theo round-robin.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **RPS gần như không đổi (65.3 → 66.1)** vì đây là **tải vòng kín**: mỗi user Locust gửi request, chờ trả lời, rồi nghỉ `wait_time = between(0.5, 2)` (trung bình 1.25 s). Throughput tối đa ≈ 100 user / (1.25 s + 0.24 s) ≈ **67 req/s** bất kể có bao nhiêu instance. Số user và thời gian nghỉ quyết định RPS, không phải năng lực server. Muốn đo năng lực tối đa phải tăng số user hoặc bỏ thời gian nghỉ.
- **Ngay với 1 instance, agent chưa bị quá tải:** nó dùng 0.21 nhân CPU trên giới hạn 0.5 (`process_cpu_seconds_total`). Lên 3 instance, mỗi cái chỉ còn 0.07 nhân.
- **p95 cải thiện nhẹ (300 → 220 ms, `/ask` 320 → 230 ms)** nhờ mỗi instance gánh ít request đồng thời hơn (bớt chờ trong event loop và bớt tranh CPU ở giới hạn 0.5 nhân). **p50 (190 ms) và p99 (1700 ms) không đổi.**
- **Nút thắt là LLM:** p95 của bước LLM khoảng **198 ms** trên tổng p95 khoảng 290–300 ms ở cả hai cấu hình (panel *LLM latency p95 theo model*), và p99 khoảng 1.7 s chính là các request "slow" của provider. Thêm instance không làm LLM nhanh hơn. Muốn giảm latency phải tác động vào LLM: model nhanh hơn, cache câu trả lời, streaming, timeout + retry cho tail latency.

**Bẫy trong lệnh của đề:** lệnh `docker compose run --rm locust ...` trong CHECKPOINTS tự khởi động lại các service mà Locust phụ thuộc (`depends_on` → nginx → agent), và đưa agent về `deploy.replicas: 2` của file compose. Lần đo đầu tiên của mình vì thế chạy **2 instance cho cả "scale 1" lẫn "scale 3"** (phát hiện ra khi `agent-3` biến mất và Prometheus chỉ còn 2 target). Đã đo lại bằng `docker compose run --rm --no-deps locust ...`, kiểm tra số container và số target Prometheus **trước và sau** mỗi lần chạy (1/1 và 3/3). Số liệu trên là của lần đo lại.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Không tin một con số nếu chưa đối chiếu từ hai phía.** Ở develop, concurrency 100 cho p95 3.5 s, nhưng histogram của chính agent cho thấy agent vẫn xử lý trong khoảng 233 ms; nút thắt là công cụ tạo tải (`load_test.py` dùng khoảng 92 % một nhân). Ở production, "scale 1" và "scale 3" lúc đầu ra giống hệt nhau vì `compose run` âm thầm đổi số instance. Benchmark cần kiểm tra điều kiện thí nghiệm (số instance, CPU của máy tạo tải, metric phía server) trước khi kết luận.
  2. **Average che giấu tail latency, và metric hạ tầng che giấu lỗi chất lượng.** Khi 10 % request chậm, avg vẫn trông ổn (364 ms) trong khi p95 đã 1.7 s; khi lỗi 20 %, avg thậm chí giảm. Khi chuyển sang v1, mọi panel đều "đẹp hơn" trong khi accuracy rơi từ 100 % xuống 4 %. Cần SLO theo percentile **và** eval chất lượng.
  3. **Alert là code, cần được test và hiệu chỉnh theo baseline thật.** `promtool test rules` bắt lỗi cú pháp và logic; `for` đánh đổi tốc độ phát hiện (40–152 s) để không báo động giả. Nhưng ngưỡng chi phí $2/giờ đặt dưới mức thường ngày nên alert luôn đỏ, và một sự cố lại làm nó tự tắt. Metric cũng chỉ thấy những gì service đó thấy: 504 ở Nginx không hiện trên metric của agent.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?
  - **Chất lượng:** `agent_eval_accuracy` từ eval định kỳ trên golden dataset, alert khi < 85 %; alert khi retrieval hit ratio < 80 %; tỉ lệ feedback 👎 theo version.
  - **Tầng ngoài agent:** metric Nginx (tỉ lệ 5xx gồm 502/504, upstream response time) qua nginx-prometheus-exporter, cộng synthetic check từ bên ngoài (gọi `/ask` thật mỗi phút) để đo đúng trải nghiệm người dùng.
  - **SLO kiểu error budget:** alert theo *burn rate* nhiều cửa sổ (vd 5 phút và 1 giờ) thay vì ngưỡng tức thời, để vừa bắt nhanh sự cố lớn vừa không báo động giả vì spike.
  - **Chi phí:** ngưỡng `LLMCostBurnRateHigh` tính theo baseline (2–3 lần mức thường ngày) hoặc theo % ngân sách ngày; thêm cost/request và cost theo user hoặc API key (ở log, không đưa user vào label để tránh cardinality cao).
  - **Saturation:** `agent_in_flight_requests` gần giới hạn, CPU/RAM so với limit của container, độ dài hàng đợi; alert trước khi latency tăng.
  - **LLM provider:** tỉ lệ lỗi và p99 latency theo provider/model, và số lần retry hoặc fallback.

---

## Phụ lục: trả lời câu hỏi Exercise 7.1–7.3

### Exercise 7.1: Đọc metrics của agent

Chạy v1 (cổng 8001) và v2 (cổng 8002), gọi một câu `/ask` vào v2 rồi `curl -s http://localhost:8002/metrics | grep -v "^#"`.

**1. Ví dụ cho mỗi loại metric** (trích từ output thật):

| Loại | Ví dụ | Ý nghĩa |
|------|-------|---------|
| **Counter** (chỉ tăng) | `http_requests_total{method="POST",route="/ask",status="200"} 1.0`<br>`llm_tokens_total{model="mock-llm-small",type="input"} 91.0`<br>`llm_cost_usd_total{model="mock-llm-small"} 4.665e-05` | Đếm dồn từ lúc khởi động; muốn ra "mỗi giây" thì dùng `rate()` |
| **Gauge** (lên xuống) | `agent_in_flight_requests 0.0`<br>`agent_info{model="mock-llm-small",version="v2"} 1.0` | Giá trị tức thời: số request đang xử lý; `agent_info` là gauge luôn bằng 1, dùng để mang thông tin version/model qua label |
| **Histogram** (phân bố vào bucket) | `http_request_duration_seconds_bucket{le="0.2",method="POST",route="/ask"} 1.0`<br>`http_request_duration_seconds_sum{...} 0.1699`<br>`http_request_duration_seconds_count{...} 1.0` | Mỗi bucket `le` đếm số request có latency ≤ ngưỡng đó; kèm `_sum` và `_count`. Từ bucket tính được percentile bằng `histogram_quantile` |

**2. Nếu dùng URL thật (`request.url.path`) làm label `route`:** mỗi URL lạ mà bot quét (`/wp-admin`, `/.env`, `/a1b2c3`...) thành một giá trị label mới, tức **một time series mới**. Nhân lên theo các label khác (`method`, `status`), và với histogram còn nhân với 12 bucket + `_sum` + `_count`, vậy là khoảng 14 series cho **mỗi** URL. Bot quét hàng nghìn URL thì sinh ra hàng chục nghìn series: bộ nhớ của app tăng mãi (prometheus_client giữ mọi series), `/metrics` phình to, và Prometheus tốn RAM, chậm, có thể sập (bùng nổ cardinality). Dùng route **template** thì số series có giới hạn. Kiểm chứng: mình gọi thử `/wp-admin` và `/.env`, cả hai đều gộp chung vào một series:

```text
http_requests_total{method="GET",route="unmatched",status="404"} 2.0
```

**Nhiệm vụ: thêm metric `agent_question_length_chars`** (đã thêm vào `develop/app.py`):

```python
QUESTION_LENGTH = Histogram(
    "agent_question_length_chars", "Độ dài câu hỏi (ký tự)",
    buckets=(20, 50, 100, 200, 500, 1000, 2000),
)
# trong ask(), trước khi gọi LLM:
QUESTION_LENGTH.observe(len(body.question))
```

Output sau một câu hỏi 40 ký tự:

```text
agent_question_length_chars_bucket{le="20.0"} 0.0
agent_question_length_chars_bucket{le="50.0"} 1.0
...
agent_question_length_chars_bucket{le="+Inf"} 1.0
agent_question_length_chars_count 1.0
agent_question_length_chars_sum 40.0
```

Dùng Histogram với bucket cố định chứ không dùng label `length="40"`: độ dài có vô số giá trị, làm label sẽ gây đúng vấn đề cardinality vừa nêu. Bucket dừng ở 2000 vì `AskRequest` giới hạn `max_length=2000`.

### Exercise 7.2: Vì sao avg chỉ tăng nhẹ trong khi p99 tăng vọt? SLO nên đặt theo chỉ số nào?

Avg là trung bình cộng của tất cả request. Với `MOCK_SLOW_RATE=0.03`, 97 % request vẫn khoảng 190 ms và chỉ 3 % chậm thêm 1500 ms. Phần cộng thêm vào avg xấp xỉ 0.03 × 1500 = 45 ms (đo được +35 ms), nên avg chỉ tăng nhẹ. p99 thì chỉ nhìn vào 1 % chậm nhất: khi tỉ lệ request chậm (3 %) lớn hơn 1 %, p99 **rơi đúng vào nhóm chậm** và nhảy từ 225 lên 1689 ms. SLO nên đặt theo **percentile (p95, p99)**, vì đó là trải nghiệm thật của nhóm user tệ nhất. Average che giấu nhóm này (chi tiết ở mục 2.2).

### Exercise 7.3: Job CI chạy eval và fail nếu accuracy < 85 %

File [`.github/workflows/eval.yml`](.github/workflows/eval.yml), chạy trên mỗi pull request:

1. Checkout, cài Python 3.11 và `requirements.txt` của `develop/`.
2. Bật agent v2 với `MOCK_ERROR_RATE=0`, để lỗi ngẫu nhiên không làm eval dao động; chờ `/health` trả 200.
3. `python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json`.
4. Upload report JSON làm artifact để xem lại.

**Vì sao chặn được merge:** `run_eval.py` gọi `sys.exit(1)` khi accuracy < `--min-accuracy` **hoặc** có câu bị regression so với `--baseline`. Exit code khác 0 làm step fail, job fail, check `quality-gate` trên PR chuyển đỏ. Bật branch protection "Require status checks to pass" cho `main` với check này thì PR không merge được cho tới khi sửa xong. Dùng baseline là bản đã đạt 100 % nên kể cả khi accuracy còn trên 85 %, chỉ cần làm sai một câu đang đúng là đã bị chặn.

### Exercise 7.4: Observability stack

Đo khi Locust chạy 30 user trên 3 instance (ảnh `grafana-dashboard.png`, số lấy bằng PromQL cùng thời điểm):

1. **p95 và avg đang là bao nhiêu, khoảng cách nói lên điều gì?** p95 khoảng **291 ms** (dashboard 293 ms), avg khoảng **226 ms**, p99 khoảng 1.7 s (panel Latency). Khoảng cách avg–p95 nhỏ (khoảng 65 ms) cho thấy phần lớn request nằm gọn trong một dải hẹp quanh 190–290 ms. Nhưng p99 cao gấp khoảng 6 lần p95: có một nhóm nhỏ (khoảng 3 %, `MOCK_SLOW_RATE=0.03`) chậm hơn hẳn, kéo avg lên một chút nhưng không chạm tới p95. Phân phối latency **lệch phải (đuôi dài)**, nên avg không mô tả được trải nghiệm của nhóm chậm nhất; phải nhìn percentile. Ở thí nghiệm B (slow 30 %), khoảng cách nới ra rất xa: avg 570 ms, p95 1895 ms.
2. **Nginx có chia đều traffic không?** Có. Panel "Requests/s theo instance" thấy 3 đường gần như trùng nhau: **6.25 / 6.16 / 6.16 req/s**. Trong benchmark scale 3, mỗi instance nhận 2403 / 2448 / 2414 request. Nginx dùng round-robin trên upstream `server agent:8000 resolve;` (hỏi lại Docker DNS mỗi 10 s nên tự thấy instance mới khi scale).
3. **Vì sao input tokens/s lớn hơn output tokens/s?** Input khoảng **1440 token/s**, output khoảng **762 token/s** (gấp khoảng 1.9 lần). Mỗi lần gọi LLM, prompt gồm **system prompt + tài liệu retrieve được (RAG) + câu hỏi**, trong khi output chỉ là câu trả lời. v2 nhét cả tài liệu vào prompt nên input luôn dài hơn. Chuyển sang v1 (thí nghiệm E, không có retrieval) thì input token/s giảm một nửa (1404 → 697).
4. **`curl http://localhost:8080/metrics` trả về gì? Vì sao?** Trả **404** (stack này chạy ở cổng 18080, xem ghi chú mục 4; `curl -i http://localhost:18080/metrics` cho `HTTP/1.1 404 Not Found`). `nginx.conf` có `location = /metrics { return 404; }`: Nginx là cổng duy nhất mở ra ngoài, nên chặn `/metrics` để người ngoài không đọc được thông tin nội bộ (route, số request, chi phí, version), và không thể gọi liên tục làm tốn tài nguyên. Prometheus vẫn scrape được vì nó gọi thẳng từng agent `http://<ip>:8000/metrics` **bên trong** Docker network qua `dns_sd_configs`, không đi qua Nginx.

### Exercise 7.5: Tracing

Chi tiết ở mục 4.3. Tóm tắt: trace chậm nhất 1724.6 ms có span **`chat mock-llm-small` chiếm 1697 ms (98.4 %)**, nên chậm là do LLM, không phải retrieval (25 ms) hay code agent. Trace lỗi có event `exception` "Upstream LLM error: 503" trên span `chat`. Lấy `trace_id` từ log JSON (`docker compose -p k5-day14-observability logs agent | grep <trace_id>`) là tìm lại đúng trace đó trong Jaeger; mọi dòng log đều có `trace_id` và `span_id` để nối log với trace.

### Exercise 7.6: Alerts

- `promtool test rules`: **SUCCESS**.
- Đã làm **5 thí nghiệm** (A–E, mục 4.2). Alert firing: `AgentHighErrorRate` (88 s), `AgentHighLatencyP95` (152 s), `AgentInstanceDown` (40 s). `LLMCostBurnRateHigh` firing ngay ở tải thường vì ngưỡng đặt thấp hơn baseline.
- **Câu hỏi: đổi `AGENT_VERSION=v1` không alert nào firing, vậy phát hiện bằng cách nào?** Bằng eval chất lượng: quality gate trong CI trước khi deploy, eval định kỳ hoặc lấy mẫu trên production với alert theo accuracy, alert trên các metric đại diện (retrieval hit ratio, token/request, version) và feedback người dùng. Chi tiết ở mục 4.2.
