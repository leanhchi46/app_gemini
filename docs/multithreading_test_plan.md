# Kế hoạch kiểm thử và cập nhật tài liệu cho kiến trúc đa luồng mới

Tài liệu này mô tả chiến lược kiểm thử tổng thể, kế hoạch đo lường hiệu năng, các bước kiểm thử hồi quy, quy tắc logging/monitoring và checklist cập nhật tài liệu trước khi phát hành kiến trúc đa luồng mới (Giai đoạn 3 trong kế hoạch refactor). Nội dung bám sát kiến trúc và chính sách điều phối được mô tả tại `docs/multithreading_refactor_plan.md`.

## 1. Ma trận kiểm thử end-to-end

| ID | Kịch bản | Điều kiện đầu vào | Hành động | Kết quả mong đợi | Ghi chú instrumentation |
| --- | --- | --- | --- | --- | --- |
| E2E-01 | Chạy phân tích thủ công lần đầu | App mở, không có phiên phân tích | Người dùng bấm **Bắt đầu phân tích** với 4 ảnh | `AnalysisController` tạo `analysis.session`; tất cả stage hoàn tất, UI cập nhật tiến độ realtime, báo cáo lưu thành công | Ghi nhận timeline stage, log `INFO` start/complete |
| E2E-02 | Hủy bằng nút **Dừng** trong khi upload | Phiên phân tích đang ở Stage 3 (upload ảnh) | Bấm **Dừng** | `cancel_group("analysis.session")` phát huy, mọi upload bị hủy, UI hiển thị trạng thái "Đã hủy bởi người dùng", không ảnh nào tiếp tục upload | Đo thời gian từ bấm Dừng đến khi UI xác nhận |
| E2E-03 | Autorun ưu tiên thao tác tay | Autorun bật, lịch tick tới hạn, user bấm **Bắt đầu phân tích** đồng thời | Giữ phím để trùng thời điểm | Phiên do người dùng khởi tạo chạy, Autorun ghi log bỏ qua lượt (`reason=user_priority`), không có hai phiên song song | Capture metric `autorun_skipped_total` |
| E2E-04 | Autorun chạy khi rảnh | Autorun bật, không phiên nào đang chạy | Đợi đến chu kỳ Autorun | Autorun tạo phiên phân tích, UI thể hiện nguồn = Autorun, tiến độ realtime | Kiểm tra `metadata["trigger"]` = `autorun` |
| E2E-05 | Refresh ChartTab realtime | Tab Chart mở, kết nối MT5 ổn định | Bật chế độ realtime, quan sát 30s | `chart.refresh` task chạy 1s/lần, không backlog UI, đồ thị cập nhật liên tục | Thu thập latency cập nhật UI vs tick |
| E2E-06 | Đóng ChartTab | ChartTab đang stream realtime | Người dùng đóng tab | `ChartController.stop_stream` hủy task group, không còn worker chart chạy, không leak thread | Kiểm tra `ThreadingManager.await_idle("chart.refresh")` thành công |
| E2E-07 | NewsService refresh thủ công | Polling chạy 5 phút/chu kỳ | Người dùng bấm **Làm mới tin tức** | Task ưu tiên chạy ngay, cập nhật UI trước lần polling tiếp theo | Log `INFO` với `trigger=user_refresh` |
| E2E-08 | App shutdown trong khi có tác vụ nền | Đang chạy phân tích + news polling | Người dùng đóng app | App hiển thị dialog chờ, `ThreadingManager.shutdown` chờ task cleanly, không mất báo cáo | Đảm bảo log shutdown summary |
| E2E-09 | Tải lại workspace lớn | Workspace chứa nhiều cấu hình + file | Load workspace qua UI | Tác vụ `ui.short` hoàn thành, UI cập nhật, không backlog UI queue > ngưỡng | Monitor backlog metrics |
| E2E-10 | Mở nhiều tab song song | ChartTab + NewsPanel + Analysis view cùng mở | Thực hiện thao tác xen kẽ (chạy phân tích, refresh chart, refresh news) | ThreadingManager phân bổ đúng group, không deadlock, UI phản hồi kịp | Capture task concurrency metrics |

## 2. Kiểm thử hiệu năng & backlog UI

### 2.1 Kịch bản đo lường

1. **Phân tích với 10 ảnh** (ngưỡng tối đa): đo tổng thời gian phiên, thời gian upload trung bình, độ trễ cập nhật UI.
2. **Tick MT5 realtime 1s**: đo tỉ lệ tick thành công, độ lệch thời gian hiển thị chart so với tick (<200ms mục tiêu).
3. **Tin tức 3 nguồn song song**: mô phỏng độ trễ 15s/nguồn; xác nhận timeout 20s hoạt động, UI không bị block.
4. **Backlog stress**: tạo script bắn 200 cập nhật UI/phút; xác định ngưỡng cảnh báo backlog (ví dụ >50 item trong 3 chu kỳ).

### 2.2 Chỉ số cần thu thập

| Nhóm | Metric | Cách đo | Ngưỡng/Target |
| --- | --- | --- | --- |
| UI Queue | `ui_queue_length_max`, `ui_queue_wait_p95` | UIQueueMonitor export log/CSV | `length_max < 50`, `wait_p95 < 150ms` |
| Analysis | `analysis_duration`, `stage3_upload_duration`, `cancel_latency` | Log metadata từ AnalysisController | Phiên tiêu chuẩn ≤ 180s, cancel ≤ 2s |
| Chart | `mt5_query_duration`, `render_latency` | Log trong ChartController + instrumentation UI | `mt5_query_duration_p95 < 2s` |
| News | `news_fetch_duration`, `news_timeout_count` | NewsController log + counter | Timeout count = 0 trong đường dây chuẩn |

### 2.3 So sánh trước & sau refactor

* Chạy lại các kịch bản tương tự trên nhánh trước refactor (hoặc bản release gần nhất) để thu thập baseline.
* Lưu kết quả vào bảng `performance_comparison.xlsx` với cột `Before`, `After`, `Δ%`.
* Đánh giá chênh lệch; nếu độ trễ tăng >15% phải điều tra và cập nhật biện pháp giảm backlog (tinh chỉnh timeout, concurrency).

## 3. Kiểm thử hồi quy

| Thành phần | Trường hợp cần kiểm tra | Phương pháp |
| --- | --- | --- |
| Logging | Task schedule/start/finish/cancel log đúng định dạng, có metadata | Unit test mock logger + review log thực tế |
| Báo cáo phân tích | Tệp Markdown/JSON vẫn được tạo đúng vị trí, không bị hủy khi cancel muộn | End-to-end + kiểm tra filesystem |
| Lưu/Load workspace | Chạy `save_workspace` và `load_workspace` | Automation + manual QA |
| NewsService | Bộ lọc nguồn, xử lý lỗi mạng, cache TTL | Unit test có mock HTTP + QA manual |
| ChartTab | Chuyển symbol, bật/tắt realtime, fallback legacy refresh | UI manual test |
| Autorun | Bật/tắt Autorun, thay đổi chu kỳ, skip khi user chạy | Integration test |
| Shutdown | `ThreadingManager.shutdown` khi không có task và khi có task | Unit test & manual |
| UI Queue | Poll 100ms, xử lý exception trong callback | Unit + instrumentation |

Mọi test hồi quy bắt buộc phải thực thi lại khi thay đổi cấu hình timeout hoặc khi sửa logic cancel.

## 4. Mẫu log & quy tắc monitoring

### 4.1 Định dạng log chuẩn

```
{timestamp} [{level}] {component}/{task} session={session_id} group={task_group} state={state} duration={ms} msg="{detail}"
```

* `component`: `analysis`, `chart`, `news`, `ui`...
* `state`: `scheduled|started|completed|cancelled|failed|timeout`
* `duration`: thời gian tính bằng ms cho trạng thái kết thúc.
* Khi retry: thêm `attempt=x/limit`.

### 4.2 Alert rule đề xuất

| Alert | Điều kiện | Hành động |
| --- | --- | --- |
| `ui_queue_backlog_high` | `ui_queue_length_max > 80` trong 3 phút | Gửi Slack cảnh báo, bật chế độ giảm tần suất chart |
| `analysis_cancel_latency_high` | `cancel_latency > 5s` | Tạo ticket điều tra executor | 
| `news_timeout_excessive` | `news_timeout_count > 5`/giờ | Xem xét giảm số nguồn hoặc tăng timeout |
| `shutdown_force_used` | `shutdown(force=True)` được kích hoạt | Log ERROR + gửi email QA |

### 4.3 Báo cáo monitoring phiên mẫu

```
== Analysis Session Summary ==
Session ID : 2024-05-15T09:12:33Z-user
Trigger    : autorun
Duration   : 128s
Cancelled  : False
Images     : total=4 success=4 failed=0
UI Latency : avg=95ms p95=140ms
Warnings   : none
```

## 5. Checklist cập nhật tài liệu

| Mục tiêu | Nội dung cần cập nhật | Trách nhiệm |
| --- | --- | --- |
| README | Thêm mô tả kiến trúc đa luồng mới, hướng dẫn bật realtime chart, yêu cầu shutdown sạch | Dev lead |
| Hướng dẫn vận hành | Quy trình monitoring, cách đọc log, xử lý alert | DevOps |
| Hướng dẫn QA | Bảng test case E2E + performance script | QA lead |
| Docs kiến trúc (`docs/multithreading_refactor_plan.md`) | Link sang test plan, cập nhật khi kiến trúc đổi | System architect |
| Changelog | Ghi chú tính năng mới, thay đổi hành vi nút Dừng, autorun | Release manager |

## 6. Tiêu chí chấp nhận cuối cùng

1. Tất cả test E2E từ mục 1 phải có kết quả PASS được lưu trữ (screencast/log).
2. Performance benchmark mục 2 đạt hoặc vượt ngưỡng; mọi chênh lệch >15% có RCA và plan.
3. Regression suite mục 3 hoàn thành, không còn bug hở; issue phát hiện phải có ticket và fix/waiver.
4. Logging/Monitoring chạy đúng định dạng; dashboard/alert được cấu hình và demo cho QA.
5. Checklist tài liệu ở mục 5 hoàn thành, có PR/commit minh chứng.
6. Bảng kiểm review code/PR cho 4 module (ChartTab → NewsService → AnalysisWorker → AppUI) được tick đầy đủ.
7. Product/QA ký duyệt test report + chấp nhận tiêu chí shutdown sạch và hành vi nút Dừng.

## 7. Deliverable cuối cùng

* Bộ script kiểm thử (automation/perf) + hướng dẫn chạy.
* Test report tổng hợp (PDF hoặc wiki) chứa kết quả đo và log minh chứng.
* Gói tài liệu cập nhật (README, runbook, QA guide).
* Báo cáo lesson learned sau rollout.
## 8. Ghi chú kiểm tra ngày 2025-10-09

- Đã chạy `python APP/main.py` bằng `.venv\Scripts\python` (tự đóng sau 15s) và ghi nhận `ThreadingManager` xử lý `chart.refresh`/`news.polling` ổn định trong `Log/app_debug.log` (mốc 12:36).
- Rà soát `APP/services/te_service.py` và `APP/services/fmp_service.py` để chắc chắn fallback SSL trả về danh sách rỗng thay vì ném lỗi, giúp UI không hiển thị alert khi môi trường thiếu chứng chỉ.
- Kiểm tra `Log/app_debug.log` đảm bảo không xuất hiện dòng `ERROR` mới sau lần chạy trên; các task `chart.draw` hoàn tất trong ~0.00s, phù hợp mục tiêu latency.
- Đối chiếu checklist NewsService (mục 3) với cập nhật mã để đảm bảo scenario offline đã được bao phủ trong regression.
