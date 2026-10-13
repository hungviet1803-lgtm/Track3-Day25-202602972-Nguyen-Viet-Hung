# Lab 25B — Report

**Họ tên / nhóm:** Nguyen Viet Hung — MSV 202602972  **Commit:** _(điền hash sau khi push)_  **Điểm tự động (`make grade`):** 84 / 88 (4 điểm còn lại là dữ liệu SLO ẩn do giảng viên chấm)

> Số liệu lấy từ `reports/gameday/*.json`, `reports/cache/*.json`, `reports/workflows.json`, `reports/slo.json`
> (seed 25 trừ khi ghi khác). `make grade --seeds 25,26,27`: 6/6 băng + C1 PASS trên cả 3 seed.

## 1. Kết quả Game Day (naive vs của bạn)

| Băng | Client | availability | p95 (s) | amplification | retry_ratio | cost/turn | recovery (s) | PASS? |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| G1 | naive | 0.7194 | 7.157 | 7.738 | 6.738 | 2.163 | 4.0 | FAIL |
| G1 | yours | 1.0 | 4.525 | 1.06 | 0.001 | 1.954 | 0.0 | PASS |
| G2 | naive | 0.456 | 15.034 | 9.904 | 8.904 | 4.627 | 155.0 | FAIL |
| G2 | yours | 1.0 | 6.559 | 1.023 | 0.003 | 1.993 | 0.0 | PASS |
| G3 | naive | 1.0 | 4.768 | 1.164 | 0.164 | 2.328 | 0.0 | FAIL |
| G3 | yours | 1.0 | 4.657 | 1.027 | 0.011 | 2.021 | 0.0 | PASS |
| G4 | naive | 1.0 | 13.764 | 1.004 | 0.004 | 2.008 | 0.0 | FAIL |
| G4 | yours | 1.0 | 5.325 | 1.015 | 0.002 | 1.967 | 0.0 | PASS |
| G5 | naive | 0.3699 | 5.359 | 17.03 | 16.03 | 2.124 | – | FAIL |
| G5 | yours | 0.8179 | 4.088 | 1.002 | 0.002 | 1.851 | – | PASS |
| G6 | naive | 0.517 | 4.836 | 12.344 | 11.344 | 2.009 | 0.0 | FAIL |
| G6 | yours | 1.0 | 4.472 | 1.027 | 0.004 | 1.803 | 0.0 | PASS |

Các check phụ của client: G1 `retry_after_violations` = 0; G2 `primary_share_after_restore` = 1.0; G5
`client_error_retries` = 0, `unneeded_failovers` = 0, toàn bộ 413 lượt hỏng là `client_error` (request malformed — không
client nào cứu được) và chỉ tốn **2** lỗi `insufficient_quota` để phát hiện hết quota; G6 `incompatible_routes` = 0.

**Độ bền trước băng ẩn.** Vì grader dùng băng lệch thời điểm / đổi cường độ, tôi viết `scripts/stress_gameday.py`:
dời mọi sự cố −40 / 0 / +35 s, nhân cường độ 0,8 / 1,0 / 1,2 (capacity, extra latency, error rate, rate limit, traffic,
malformed), 8 seed → 72 lần chạy mỗi băng. G1, G2, G3, G4, G6: **72/72 PASS** (xấu nhất: G1 availability 0,9996, ampl
1,081; G3 retry_ratio 0,035; G4 p95 6,98 s; G2 primary share 0,989). G5: 68/72 — 4 lần trượt đều ở k=1,2 (72% request
malformed), nơi trần lý thuyết < 78% và client vẫn không làm mất thêm lượt nào ngoài `client_error`. Ở 2× cường độ, G6
đạt 0,9735 — giới hạn là năng lực vật lý: beta chỉ còn 4 rps trong khi riêng tool call đã tới ~4/s (mục 7).

## 2. Cấu hình client và lý do

Mọi số trong bảng: seed 25, cấu hình cuối, chỉ đổi đúng tham số đang xét.

| Tham số | Giá trị | Vì sao (dựa trên băng nào, số liệu nào) |
|---|---:|---|
| attempt_timeout_s | 8.0 | Lớn hơn p99 lúc bình thường của provider chậm nhất (beta: 1,8·e^(0,35·2,33) ≈ 4,1 s, cộng hàng đợi khi beta gánh tải) nên không cắt nhầm call lành; đủ nhỏ để sau 1 lần treo vẫn còn ≥ 2 lần fail over trong 30 s. G6: timeout 30 s → availability 1,0 → **0,954 (FAIL)**, 107 lượt `deadline`. |
| max_attempts_per_provider | 2 | 1 retry cùng provider cho 529/503/500 (G3: 500 ngẫu nhiên 30% — lần 2 thường thành công), sau đó fail over. G3 retry_ratio = 0,011. Đặt 5 + tắt breaker + tắt budget → G3 retry_ratio 0,160 (FAIL). |
| retry_on_timeout (thêm) | false | Timeout đã đốt 8 s của user; retry vào đúng hàng đợi vừa treo là cược tệ nhất. Thí nghiệm: bật lại (breaker & budget tắt) → G2 availability 1,0 → 0,983, recovery 0 → 11 s, 41 lượt `deadline`. |
| backoff_base_s / cap_s | 0,25 / 4,0 | Full jitter: retry đầu rơi đều trong [0; 0,25] s — đủ phân tán, không tốn deadline. cap 4 s < 1/7 deadline. Với `retry_after`: chờ đúng retry_after + U(0; 0,25) → 0 vi phạm ở G1 trên 72 biến thể. |
| rate_limit_jitter_s (thêm) | 0,5 | Khi mọi provider đều đang cooldown 429, các call chờ được rải trong 0,5 s đầu cửa sổ mới thay vì cùng bắn ở mili-giây đầu (thundering herd vào đúng provider vừa hết rate limit). |
| reserve_tool_capacity (thêm) | true | Khi chỉ còn **một** provider gọi được tool (G6: A sập, còn beta), chat nhường nó cho tool call và sang gamma-mini nếu gamma đang dùng được. G6: 429 trên beta 183 → **8**, p95 6,39 → 4,47 s, cost/turn 2,18 → 1,80. G5 (A hết quota): cost/turn 2,50 → 1,85. Đánh đổi: chat do model nhỏ trả lời nhiều hơn khi chỉ còn 1 provider có tool (G6: 25% call, G5: 24%; G1–G4: 3–6%). Xem mục 9. |
| slow_fallback (thêm) | true | Breaker mở vì *chậm* nghĩa là "có chỗ nhanh hơn thì đi"; khi **mọi** provider đều chỉ bị từ chối vì chậm thì câu trả lời chậm vẫn hơn không có gì. Mỗi call dùng tối đa 1 lần. Băng tự dựng "cả 4 provider +4 s": 0,708 → **1,0**. Không đổi gì trên 6 băng (luôn còn provider nhanh hơn). |
| retry_budget_ratio | 0,1 (+0,5 token/s, tối đa 20) | Lớp phòng thủ cuối khi breaker không trip (G3: 30% lỗi < ngưỡng 50%). Thí nghiệm 1: breaker hỏng, budget còn → G3 retry_ratio 0,067 (PASS), tắt budget → 0,160 (FAIL). |
| quota_cooldown_s | 300 | Hết quota là chuyện billing, cần người nạp tiền — không tự hết trong vài giây. Thử 30 s: G5 `insufficient_quota` 2 → 23 mà availability không đổi (0,8179). |
| breaker.window_size / min_calls | 10 / 5 | 8 call/s → 10 kết quả ≈ 1,3 s traffic: trip nhanh khi alpha nghẽn. 20/10 → G2 p95 6,56 → **11,06 s**. 5/3 → G2 p95 6,58 s (không lợi gì thêm) nhưng xác suất trip nhầm mỗi lần đánh giá khi provider có 10% lỗi nền là 0,86% (≥3/5) so với 0,16% (≥5/10) — với 8 call/s là trip nhầm vài lần mỗi phút. min_calls 5 tránh trip vì 1–2 lỗi nền (0,2%). |
| breaker.failure_rate_threshold | 0,5 | Lỗi nền 0,2% không bao giờ chạm; G2/G6 (≈100% lỗi/timeout) trip ngay sau 5 kết quả. |
| breaker.slow_call_s | 5,0 | p99 bình thường ≤ 4,1 s (beta) nên call lành không bị coi là chậm; G4 thêm +5 s (≈ 6,2 s) → 100% call chậm → trip theo `slow_call_rate`. Đặt 8 s: G4 p95 13,78 s (**FAIL**) vì breaker không bao giờ trip. |
| unhealthy_rate_threshold (thêm) | mặc định 0,6 | Trip khi (lỗi + chậm) ≥ 60%, vá lỗ hổng "40% timeout + 40% chậm không trip" (mục 9). Mặc định = max(hai ngưỡng trên) để không bao giờ trip sớm hơn chúng với một loại lỗi thuần. |
| breaker.open_duration_s | 10 | Ngắn để quay lại alpha sớm: primary share sau restore = 1,0 (G2, G4, G6). Dài hơn (vd. 60 s) giảm số probe vào alpha đang ốm, nhưng nếu probe hỏng ngay trước restore thì alpha bị bỏ trống tới restore+60 s — đúng cửa sổ đo `primary_share_after_restore`. |
| breaker.half_open_max_probes | 2 (cần 2 thành công) | Chỉ 2 request thử vào provider đang hồi phục — không thundering herd; 2 lần thành công liên tiếp (không chậm) mới đóng, tránh đóng nhầm do 1 call may mắn. |

Sơ đồ quyết định của `on_error`:

```
classify(err)
 ├─ CLIENT_ERROR (400…)      breaker.release   → GiveUp("client_error")        (không retry, không failover)
 ├─ QUOTA_EXHAUSTED (429 iq) breaker.release   → cooldown provider 300 s        → failover ngay
 ├─ RATE_LIMITED (429 rl)    breaker.release   → cooldown = now + retry_after   → failover ngay
 │                                              (cooldown dùng chung cho mọi call)
 └─ OVERLOADED / SERVER_ERROR / TIMEOUT        breaker.on_failure
        ├─ TIMEOUT                                                              → failover ngay
        └─ 529/503/500: tries < 2 AND còn deadline AND budget.try_acquire()     → retry cùng provider sau full-jitter
                        ngược lại                                               → failover
failover = đi tiếp ladder (đã lọc theo tool calling), bỏ qua provider đang cooldown / breaker từ chối;
           chat bỏ qua provider có tool CUỐI CÙNG nếu gamma-mini đang dùng được
hết ladder → chờ cooldown 429 ngắn nhất (≤ 5 s, breaker không OPEN, vừa deadline, + jitter)
           → không thì provider mà breaker mở chỉ vì CHẬM (1 lần / call) → không thì GiveUp
```

## 3. Ba thí nghiệm

1. **Retry budget là lớp phòng thủ cuối** (breaker `min_calls: 1e9`, `max_attempts_per_provider: 5`, seed 25):

   | | G2 ampl | G2 retry_ratio | G2 errors | G3 ampl | G3 retry_ratio |
   |---|---:|---:|---|---:|---:|
   | (a) breaker hỏng, **có** budget | 1,381 | 0,053 | 529: 1043, 429: 60 | 1,135 | 0,067 PASS |
   | (b) breaker hỏng, **không** budget | 1,534 | 0,284 | 529: 1498, 429: 320 | 1,162 | **0,160 FAIL** |
   | (b) + `retry_on_timeout: true` | 1,591 | 0,376 | 529: 1567, 429: 479; availability 0,983, recovery 11 s, 41 `deadline` | – | – |
   | breaker đúng, không budget | 1,022 | 0,003 | | 1,032 | 0,014 |

   Khi breaker hỏng, budget là thứ duy nhất chặn retry: nó giới hạn retry ≈ 10% traffic + 0,5/s bất kể sự cố tệ
   đến đâu, nên G3 vẫn PASS. Khi breaker đúng, G2 gần như không cần budget (breaker trip sau 5 kết quả, traffic đi
   alpha-eu/beta) — nhưng ở G3 brown-out 30% lỗi dưới ngưỡng breaker 50%, budget vẫn là thứ giữ retry_ratio thấp.
   Hai cơ chế bảo vệ khác nhau: breaker bảo vệ **một provider** (theo sức khỏe của nó), budget bảo vệ **toàn hệ thống**
   (theo tỷ lệ retry/traffic) — và nó không phụ thuộc cấu hình breaker đúng hay sai, nên nên có cả hai.

2. **`attempt_timeout_s: 30`** (seed 25): G6 availability 1,0 → **0,954** (FAIL, cả 3 seed), `give_up_reasons`
   = {`deadline`: 107, `no_provider_available`: 2}, trong khi p95 lại *giảm* 4,48 → 4,12 s — survivorship bias: lượt
   nào kẹt 30 s ở alpha-eu (treo, không bao giờ trả lời) thì hết hạn và biến khỏi thống kê latency, chỉ còn các lượt may
   mắn. G4 gần như không đổi (p95 5,33 → 5,39 s, availability 1,0) vì G4 không có call nào treo: alpha chậm 6,2 s
   (< 8 s, < 30 s) và breaker bắt nó qua **slow-call**, không phải qua timeout. Timeout "đúng" phải thỏa cả hai: > p99
   lúc bình thường (≈ 4 s, cộng hàng đợi), và đủ nhỏ để `timeout + thời gian 1–2 lần fail over` < deadline của user
   (30 s, chia cho 2 call của 1 lượt). 8 s thỏa cả hai — nhưng một timeout *cố định* vẫn có giới hạn (mục 7).

3. **Bỏ lọc tool calling khỏi `ladder()`** (G6): `incompatible_routes` 0 → **25** với client cuối, và 0 → **272**
   (availability 0,886, cost/turn 2,28) nếu tắt thêm `reserve_tool_capacity`. Con số nhỏ đi vì khi chat nhường beta,
   beta ít bị 429 nên tool call hiếm khi trượt xuống gamma-mini — nhưng 25 > 0: bộ lọc là một **bất biến an toàn**,
   không thể thay bằng "thường thì không xảy ra". Nói với PM: *"Khi provider A sập, hàng trăm khách nhờ hoàn tiền nhận
   được câu trả lời từ một model không biết gọi công cụ — nó trả lời bằng văn bản như thể đã tra đơn hàng nhưng thực ra
   chưa làm gì. Tệ hơn báo lỗi, vì khách tưởng yêu cầu đã được xử lý, và ta vẫn trả tiền cho những câu trả lời đó."*

## 4. Workflow hoàn tiền

| Executor | completion | crashes | duplicate refunds | duplicate emails | lost refunds | overpaid | wasted LLM / crash |
|---|---:|---:|---:|---:|---:|---:|---:|
| naive | 1.0 | 81 | 128 | 81 | 0 | 1 496 700 ¢ | 1.123 |
| yours | 1.0 | 66 | 0 | 0 | 0 | 0 | 0.303 |

(seed 25; seed 26, 27, 1, 2, 99 cũng 0/0/0, completion 1,0, wasted/crash 0,24–0,34.)

- **Chỉ idempotency key — chưa đủ:** payment không trùng, nhưng worker mới không biết gì nên chạy lại từ đầu: gọi lại
  LLM classify (tốn tiền), và nếu bước nào không có idempotency (LLM, orders) thì lặp lại mỗi lần crash → wasted LLM
  cao như naive (1,12/crash). Workflow cũng phải đọc lại kết quả các bước trước (refund_id) — chỉ có từ checkpoint hoặc
  từ việc gọi lại.
- **Chỉ checkpoint — chưa đủ:** crash xảy ra *sau* khi payment đã chạy nhưng *trước* khi checkpoint được ghi
  (`WorkerCrash` / `ServiceTimeout` sau commit). Worker mới thấy chưa có checkpoint → gọi refund lần nữa → nếu không có
  key cố định thì hoàn tiền 2 lần (naive: 128 lần trùng, trả thừa 14 967 $).
- **Ghi checkpoint *trước* khi gọi payment:** nếu crash/timeout ngay sau khi ghi, worker mới thấy "đã xong" và bỏ qua
  bước → tiền **không bao giờ được hoàn** (lost refund) — lỗi im lặng, tệ hơn trùng. Thứ tự đúng: chạy step (với key
  ổn định `session:step`) → thành công → checkpoint. Crash ở giữa chỉ làm step chạy lại, và key biến lần chạy lại thành
  no-op. 20 LLM call "phí" còn lại là các lần worker chết ngay trong bước LLM, trước checkpoint — không tránh được.
- Ablation từng lựa chọn (mục 9): `uuid4()` làm key → 14 hoàn tiền trùng; checkpoint trước step → 11 hoàn tiền mất;
  bỏ checkpoint → wasted LLM/crash 1,132. `_retry` có backoff full jitter (không retry dồn dập vào payment API đang lỗi).

## 5. Alerting & error budget

| Sự cố | Mong đợi | Naive alerter (5 phút > 5%) | Burn-rate alerter | Độ trễ phát hiện (burn-rate) |
|---|---|---|---|---:|
| checkout_bug | page | page (1 phút) | page | 27 phút (hạn 35) |
| provider_outage | page | page (0 phút) | page | 4 phút (hạn 8) |
| deploy_blip | none | **page sai** | không page | – |
| slow_leak | ticket | **bỏ sót** | ticket | 1337 phút (hạn 1800) |
| degraded_evening | page | page (214 phút) | page | 291 phút (hạn 330) |
| night_spike | none | **page sai** | không page | – |
| small_bump | none | **page sai** | không page | – |

Naive: 7 page, 3 false page, bỏ sót rò rỉ chậm → FAIL. Burn-rate: 3 page, 1 ticket, 0 false page → PASS; ổn định trên
9 seed sinh dữ liệu khác (`slo.data.generate`), độ trễ checkout_bug luôn 27–28 phút. Độ trễ đó do toán học của luật,
không phải lỗi cài đặt: 15% lỗi = burn 30×, cửa sổ 1 h cần ≥ 14,4/30·60 ≈ 29 phút lỗi mới vượt ngưỡng.

Error budget 30 ngày: 25 901 755 request, cho phép 129 508,8 lỗi, thực tế 55 618 → **đã tiêu 42,95%, còn 57,05%**
(availability 99,785%). **Không** đóng băng release (budget còn > 0), nhưng đã tiêu gần nửa — nên ưu tiên các action
item reliability trước khi tung tính năng rủi ro.

`small_bump` (20 phút ở 12%) chỉ tiêu ≈ 1% budget tháng: burn 24× nhưng chỉ 20 phút → cửa sổ 1 h burn 24·20/60 = 8×
< 14,4, cửa sổ 6 h burn 1,3× < 6 → không luật page nào chạm. Nó đã tự hết; đánh thức người vì 1% budget là alert
fatigue — lần sau page thật sẽ bị phớt lờ. Nếu nó kéo dài, burn-rate sẽ tự leo lên luật page/ticket.

## 6. Postmortem — Băng G2 với client naive (blameless)

*Hình: `reports/gameday/G2_overload_storm.png` (naive trái, resilient phải). Số từ
`reports/gameday/naive_G2_overload_storm_timeseries.csv` (cửa sổ 10 s) và đếm lỗi theo cửa sổ 20 s (bọc NaiveClient,
chỉ quan sát).*

**Tóm tắt:** Lúc t=120 alpha mất 75% GPU trong 3 phút. Client v1 retry mọi lỗi qua 3 tầng không jitter, không budget,
không breaker, không fallback, nên tải lên alpha tăng ~24× (8,9 → 214 attempt/s) và giữ cho alpha bão hòa bởi chính các request đã bị bỏ.
Provider hồi phục ở t=300 nhưng hệ thống chỉ trả lời lại được ở t≈455 (recovery 155 s): 54,4% lượt user thất bại.

**Ảnh hưởng:** 1 285 / 2 362 lượt user thất bại (availability 45,6%), 0 call thành công trong ~310 s (t≈145 → ≈455),
p95 lượt thành công 15,0 s. Chi phí/lượt tốt 4,63 (×2,3 bình thường) vì trả tiền cho công việc bị bỏ. Trong 10 phút
đó burn rate = 54,4% / 0,5% ≈ **109×**. Nếu tháng chỉ có sự cố này: tháng có 4 lượt/s × 30 ngày = 10 368 000 lượt,
budget 0,5% = 51 840 lượt lỗi → sự cố 10 phút tiêu **2,5% budget tháng**.

**Timeline** (giây ảo):

| t | Sự kiện | Bằng chứng (số) |
|---:|---|---|
| 0–120 | Bình thường | ~8,9 attempt/s, success 84/84 mỗi 10 s, latency TB 1,3 s |
| 120 | alpha mất 75% năng lực (3,75 rps < tải 8 rps) | Hàng đợi bắt đầu dài; call vẫn thành công nhưng latency TB 5,1 s |
| 130–140 | Timeout + 529 bắt đầu, retry 3 tầng nhân tải | 51,9 attempt/s; vẫn 19/19 thành công (call cũ) |
| 140–150 | **Sụp đổ**: retry storm chạm rate limit 20 rps | 214 attempt/s; 3 392 lỗi 429 / 20 s; **0/47** call thành công |
| 150–300 | Bão hòa ổn định | 110–154 attempt/s; ~2 400 lỗi 429 + ~330 lỗi 529 + ~70 timeout mỗi 20 s; 0 thành công |
| 300 | alpha hồi phục hoàn toàn | capacity_factor về 1,0 |
| 300–360 | **Vẫn sập** dù provider khỏe | ~15 attempt/s (≈ đúng năng lực 15 rps của alpha); ~290 `client_timeout` / 20 s; **0** thành công |
| 360–420 | Làn sóng retry thứ hai | 78–111 attempt/s; 2 004 lỗi 429 (t=360–380) và 529 quay lại (120 / 20 s); 0 thành công |
| 440–455 | Cohort retry cạn (36 attempt / deadline 30 s), tải mới < năng lực | 45 thành công / 20 s, latency TB 7,7 s (hàng đợi đang rút) |
| 455–480 | Hồi phục | success 0,86 → 0,93 → 1,00 / 10 s; recovery_s = 155 |

**Trigger vs root cause:** *Trigger* là sự cố hạ tầng: alpha mất 75% GPU trong 3 phút. *Root cause* là thiết kế lớp
gọi LLM: 3 tầng retry chồng nhau (app 4 × gateway 3 × SDK 3 = tối đa 36 attempt/call), delay cố định không jitter, không
retry budget, không breaker, không fallback, không phân loại lỗi (retry cả 429 mà bỏ qua `retry-after`). Một sự cố
năng lực bị khuếch đại thành tải gấp ~10× trung bình, ~24× lúc đỉnh (amplification 9,9; 34 475 attempt cho
3 481 call).

**Vì sao không tự hồi phục sau t=300 (metastable failure):** Provider là hàng đợi FIFO; khi client timeout (8 s),
**server vẫn xử lý tiếp** request đó. Sau t=300 client vẫn đẩy ~15 request/s vào — bằng đúng năng lực 18 slot / 1,2 s
= 15 rps — nên hàng đợi không bao giờ rút: mỗi request mới phải chờ ≈ 8–10 s, vượt timeout 8 s → client bỏ → retry →
thêm 1 request nữa vào hàng đợi. Server bận 100% làm việc cho những người đã bỏ đi, goodput = 0 (≈ 290 timeout và
0 thành công mỗi 20 s). Vòng lặp tự duy trì: *chậm → timeout → retry → hàng đợi dài → chậm*. Nó chỉ gãy khi tải thực
giảm dưới năng lực — ở đây là khi các cohort call chạm giới hạn 36 attempt / deadline 30 s và bị bỏ hẳn (t≈440).

**Điều gì giúp / điều gì làm tệ hơn:**
- Giúp: rate limit 20 rps của tenant chặn bớt (26 298 lỗi 429 trả về nhanh, không tốn GPU); deadline 30 s và giới hạn
  36 attempt cuối cùng cũng cắt được vòng lặp.
- Làm tệ hơn: retry 429 mà không đọc `retry-after`; delay cố định 0,2 s đồng bộ hóa mọi client (bùng nổ 214 attempt/s);
  timeout 8 s < thời gian chờ hàng đợi khi đầy (10 s) nên mọi công việc đều phí; không có provider dự phòng dù alpha-eu
  và beta khỏe suốt sự cố. Client v2 trên cùng băng: availability 1,0, amplification 1,023, recovery 0 s.

**Action items:**

| # | Hành động | Loại | Owner | Cách kiểm chứng |
|---|---|---|---|---|
| 1 | Gom retry về **1 tầng** (client), tắt retry ở gateway/SDK; full jitter + retry budget 10% | prevent | Platform/LLM-gateway team | CI chạy G2: amplification ≤ 1,2 và retry_ratio ≤ 0,05 trên 3 seed |
| 2 | Circuit breaker sliding-window (tỷ lệ lỗi + slow call) và fallback ladder alpha → alpha-eu → beta → gamma-mini (lọc tool calling) | mitigate | Agent-runtime team | CI: G2 recovery_s ≤ 30, availability ≥ 0,95; G6 incompatible_routes = 0 |
| 3 | Dashboard + alert burn-rate trên **amplification** (attempt/logical call) và tỷ lệ goodput, page khi amplification > 2 trong 5 phút | detect | SRE on-call | Replay G2 naive: alert phải bắn trước t=150 (≤ 30 s sau khi storm bắt đầu) |
| 4 | Honour `retry-after`, cooldown dùng chung theo provider; timeout dựa trên p99 + deadline | prevent | Agent-runtime team | CI G1: retry_after_violations = 0; G6 với timeout cấu hình: availability ≥ 0,95 |
| 5 | Game day định kỳ hằng quý với băng ẩn (lệch thời điểm, cường độ) — `scripts/stress_gameday.py` | detect | SRE lead | 72/72 biến thể PASS trước mỗi release lớn |

## 7. Một điểm yếu còn lại

**Timeout cố định không co giãn khi cả hệ thống cùng chậm.** Tôi dựng một băng thử "cả 4 provider chậm thêm X giây
trong 3 phút" (`Effect` không gắn provider). Với X = 4 s, client đạt 1,0 nhờ `slow_fallback` (mục 9). Nhưng với
X = 8 s, mọi câu trả lời mất ≈ 8,6–9,8 s > `attempt_timeout_s` 8 s: mọi attempt đều thành `client_timeout`, breaker mở vì
**lỗi** (không phải vì chậm) nên nhánh slow fallback đúng là không can thiệp, và availability chỉ còn **0,628**
(727 `no_provider_available`). Naive còn tệ hơn (0,251, amplification 9,99), nhưng điều đáng nói là: user có 30 s mà
câu trả lời chỉ cần ~9 s — ta bỏ cuộc dù còn đủ thời gian.

Ngoài ra, ở 2× cường độ G6 đạt 0,9735: beta chỉ còn 4 rps trong khi riêng tool call đã tới ~4/s. Chat đã được dồn hết
sang gamma-mini (1 125 attempt), nên phần còn thiếu là **trần năng lực** chứ không còn là lỗi routing — chỉ thêm
năng lực tool-capable (hợp đồng rate limit cao hơn, provider thứ 4 có tool) mới sửa được.

**Cách sửa timeout:** timeout thích nghi theo latency quan sát được của *cả fleet* thay vì hằng số:
`timeout = clamp(k × p95_gần_đây_của_các_call_thành_công, 8 s, deadline_còn_lại − thời_gian_cho_1_lần_failover)`.
Khi chỉ một provider chậm, p95 của fleet vẫn thấp → timeout ngắn → fail over nhanh (giữ nguyên G4/G6). Khi tất cả cùng
chậm, p95 của fleet tăng → timeout giãn theo → câu trả lời 9 s được nhận. Kiểm chứng: băng "cả 4 provider +8 s" ≥ 0,95
mà G6 vẫn ≥ 0,95 và không có lượt nào treo quá 30 s.

## 8. Cache (Part G)

Số từ `reports/cache/*.json` (`make cache`, seed 25):

| Client | availability | faq_availability | cache_hit_ratio | stale_served | wrong_answers | outdated_answers | cost/turn | PASS? |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| resilient (không cache) | 0.838 | 0.843 | 0.0 | 0 | 0 | 0 | 1.386 | FAIL |
| cached — cấu hình starter (0,80 / 600 / 0) | 0.8469 | 0.8587 | 0.742 | 0 | 181 (`other_question`) | 80 | 0.921 | FAIL |
| cached (của tôi: 0,92 / 60 / 600) | 0.9127 | 0.9645 | 0.653 | 157 | 0 | 3 | 0.916 | PASS |

Stress C1 (lệch −40/0/+35 s, 8 seed): 72/72 PASS, wrong_answers = 0 mọi lần, outdated tối đa 12, faq_availability
tối thiểu 0,945, hit tối thiểu 0,616.

| Tham số `cache:` | Giá trị | Vì sao (số liệu nào) |
|---|---:|---|
| similarity_threshold | 0,92 | Đo trên catalog embedding: các cách hỏi cùng ý có cosine **≥ 0,951**, các cặp "gần mà khác" (refund_policy/refund_time, cod/payment_methods, ship nội thành/ngoại tỉnh) **≤ 0,862**. 0,92 nằm giữa khe, nghiêng về phía chặt (cách cụm khác ý 0,058) vì trả lời sai đắt hơn một lần miss. 0,80 → 175 `other_question`; 0,97 → hit 0,653 → 0,58, cost 0,916 → 0,965. |
| ttl_s | 60 | Chỉ TTL giới hạn được thay đổi không báo trước (bảng phí ship t=480). Trên 5 seed: TTL 30 → outdated ≤ 7 nhưng hit 0,567; TTL 60 → outdated ≤ 5, hit ≥ 0,629; TTL 90 → outdated tới 15 (sát ngưỡng); TTL 300 → outdated 95–101 (FAIL). |
| max_stale_s | 600 | Stale-if-error phải sống qua cả sự cố (C1: 120 s) cộng TTL: entry lưu lúc t≈240−60 vẫn phải dùng được ở t=360. Trên 5 seed (TTL 60): 0 → faq_availability tối thiểu 0,847 (FAIL); 120 → 0,950 (vừa sát ngưỡng 0,93 + nhiễu); 300/600 → 0,954. Chọn 600 để có biên cho sự cố dài hơn ở băng ẩn; stale chỉ phục vụ khi **không** provider nào trả lời được. |
| max_entries | 500 | Mỗi intent chỉ giữ 1 entry nhờ "same question → replace", nên thực tế < 40 entry; LRU chỉ là chốt an toàn bộ nhớ. |

Thí nghiệm (seed 25):

1. **Ngưỡng.** 0,80: hit 0,659, wrong 175 (toàn bộ `other_question`), cost 0,979 · 0,92: hit 0,653, wrong 0, cost
   0,916 · 0,97: hit 0,58, wrong 0, cost 0,965. Ở 0,80, câu "Bao lâu thì nhận được tiền hoàn?" (refund_time) được trả
   bằng câu trả lời của "Chính sách hoàn tiền thế nào?" (refund_policy) — cosine 0,86; tương tự COD ↔ hình thức thanh
   toán, ship nội thành ↔ ship đi tỉnh, đổi size ↔ đổi màu. Ngưỡng lỏng gần như không tăng hit (0,659 vs 0,653) mà
   đổi lấy 175 câu sai.
2. **TTL.** 30 / 60 / 300 s → outdated 2 / 3 / 95, hit 0,589 / 0,653 / 0,731. Webhook chỉ giúp khi có người *báo*
   (chính sách hoàn tiền t=150 → invalidate, 0 `ignored_invalidation`); bảng phí ship đổi **im lặng** ở t=480 nên cache
   không có tín hiệu nào — entry cũ cứ được phục vụ cho tới khi hết tươi. Số câu trả lời cũ ≈ lưu lượng câu hỏi ship ×
   tuổi còn lại của entry, nên TTL là thứ duy nhất giới hạn nó.
3. **Stale-if-error.** `max_stale_s: 0` → faq_availability 0,9645 → **0,8733**, stale_served 157 → 0, availability
   0,913 → 0,857: trong 120 s mọi provider sập, câu hỏi FAQ đã từng được trả lời không còn được phục vụ nữa.

Trả lời:

- **Vì sao câu hỏi cá nhân không được cache, kể cả theo từng user?** Câu trả lời phụ thuộc dữ liệu *đang thay đổi*
  của user (trạng thái đơn, tiền hoàn đã về chưa) — nó cũ đi trong vài phút, nên cache theo user sẽ trả lời sai một
  cách tự tin ("đang giao" khi đã giao xong). Hit ratio cũng gần 0 (mỗi user hỏi về đơn của mình một vài lần). Và rủi ro
  bảo mật rất lớn: embedding của "Đơn #48213 của tôi đang ở đâu?" và "Đơn #48214…" giống nhau ~0,997 — chỉ một lỗi
  scope (quên user_id trong key, sai tenant) là lộ đơn hàng / tiền hoàn của người khác (`other_user`). Lợi ích nhỏ,
  thiệt hại không đảo ngược được → không nằm trong allowlist.
- **Dashboard xanh nhờ cache — alert dựa trên số nào?** Đo SLI **trước** cache: tỷ lệ lỗi / GiveUp của provider
  (inner client), số breaker OPEN, và `stale_served` / phút (stale chỉ xảy ra khi không provider nào trả lời → đó chính
  là tín hiệu sự cố). Ở C1: stale_served = 157 trong khi availability tổng tụt 0,913 (tool call không thể cache) dù
  faq_availability còn 0,965. Page theo burn-rate trên availability *provider-side* (hoặc trên lượt không phải FAQ), và
  thêm alert "stale ratio > 5% trong 5 phút" — cache là cách giảm thiệt hại cho user, không phải lý do để on-call không
  biết.

## 9. Tự rà soát: những gì tôi đã sửa sau khi các băng đã PASS

Sau khi 6/6 băng PASS, tôi tự rà lại bài theo các mục tiêu học tập thay vì theo checklist. Bốn điểm dưới đây đều đã PASS
trước khi sửa — chúng được sửa vì là lỗi thật, không phải để lấy điểm.

| # | Vấn đề | Bằng chứng trước khi sửa | Sửa | Sau khi sửa |
|---|---|---|---|---|
| 1 | Breaker theo đặc tả chỉ đếm call "chậm mà không lỗi" cho tỷ lệ chậm → 40% timeout + 40% chậm không trip | Chuỗi 50 kết quả xen kẽ (80% tệ): breaker vẫn **CLOSED** | Thêm điều kiện `unhealthy_rate` = (lỗi + chậm) / n ≥ max(hai ngưỡng) — timeout chỉ là một call chậm mà ta thôi chờ | Trip sau 5 kết quả; 13/13 test breaker + 11/11 test client vẫn pass; 6 băng vẫn PASS, metric gần như không đổi |
| 2 | Chat tranh rate limit của provider có tool cuối cùng | G6: 183 lỗi 429 trên beta, p95 6,39 s; G5 cost/turn 2,50 | `reserve_tool_capacity` (mục 2) | G6: 429 → 8, p95 → 4,47 s, cost 2,18 → 1,80; G5 cost → 1,85 |
| 3 | Breaker slow-call mở **mọi** provider khi tất cả cùng chậm → từ chối câu trả lời dùng được | Băng "cả 4 provider +4 s": **0,708** (naive: 1,0) | `slow_fallback`: hết ladder thì gửi tới provider mà breaker mở chỉ vì chậm, 1 lần / call, không permit | 0,708 → **1,0** |
| 4 | `_retry` của workflow retry ngay lập tức, không backoff — trái với chính mục tiêu "retry đúng cách" | (Simulator không có đồng hồ nên metric không lộ ra) | Full jitter (0,2 s, cap 5 s) dùng lại `FullJitterBackoff`; `sleep` tiêm vào được (production: `time.sleep`) | Kết quả workflow không đổi (0/0/0, 0,303) |

**Đánh đổi của #2 phải nói rõ:** gamma-mini là model nhỏ hơn. Chat chỉ bị đẩy sang đó khi *chỉ còn một* provider
gọi được tool, nên trên băng bình thường gần như không xảy ra, nhưng trong sự cố tỷ lệ này đáng kể: G6 25% call,
G5 24% (khi A hết quota), G1–G4 3–6%. Nếu chất lượng chat của gamma-mini không chấp nhận được, đặt
`reserve_tool_capacity: false` — client vẫn PASS 6/6 (đã chạy), chỉ mất phần cải thiện cost/latency.

**Ablation — mỗi cơ chế phòng vệ có thật sự cần không?** (subclass trong script riêng, seed 25, không sửa code nộp)

| Bỏ cơ chế | Hậu quả đo được |
|---|---|
| Lọc tool calling trong `ladder()` | G6: 25 `incompatible_routes` (272 nếu tắt thêm #2) |
| Ngưỡng cache 0,92 → 0,80 | C1: 175 `other_question` |
| Không cache câu cá nhân | C1: **368** `other_user` (lộ dữ liệu người khác), faq_availability 0,786 |
| Scope cache theo `prompt_version` | C1: 31 `old_prompt` sau deploy v2 |
| Webhook `on_content_update` | C1: 22 `ignored_invalidation` |
| TTL 60 → 600 | C1: 95 `outdated_answers` |
| `max_stale_s` 600 → 60 (ngắn hơn sự cố) | C1: faq_availability 0,923 (FAIL) |
| Idempotency key ổn định (thay bằng `uuid4()`) | Workflow: 14 hoàn tiền trùng, 22 email trùng, trả thừa 1 964 $ |
| Checkpoint *sau* step (ghi trước) | Workflow: **11 hoàn tiền bị mất**, completion 0,914 |
| Checkpoint (chỉ còn idempotency key) | Workflow: wasted LLM/crash 1,132 (FAIL ngưỡng 0,6) |

Một ablation cho số "đẹp" mà vẫn sai: bắt `WorkerCrash` trong executor làm metric trông ổn (completion 1,0, 0 trùng)
chỉ vì trong mô phỏng crash là một exception bắt được. Ngoài đời `WorkerCrash` là process bị OOM-kill / instance bị thu
hồi — không còn code nào chạy để mà bắt; "bắt" nó chỉ che mất tín hiệu sự cố (`worker_crashes` = 0). Metric pass chưa
chắc là làm đúng.

**Giới hạn còn lại tôi biết nhưng chưa làm:** ngưỡng cache 0,92 đúng với catalog *mô phỏng* — ngoài đời cần tập câu
hỏi có gán nhãn để đo lại; TTL đang dùng chung cho mọi tài liệu, trong khi tài liệu đổi thường xuyên (bảng phí ship)
nên có TTL ngắn hơn tài liệu ổn định (bảo hành) — làm được bằng TTL học từ tần suất invalidate của từng nguồn, không
hard-code tên tài liệu.
