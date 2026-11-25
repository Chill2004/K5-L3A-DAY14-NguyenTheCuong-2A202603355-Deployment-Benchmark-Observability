# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON trong [`reports/`](reports/) (bản gốc ở `06-lab-complete/benchmark-observability/develop/reports/`), CSV và screenshot thật, không ước lượng.

**Họ tên:** Nguyen The Cuong
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

> Làm ở CP8 (Part 7 Bước 2, Docker stack). Phần dưới sẽ được điền sau khi chạy.

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...

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
