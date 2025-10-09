# Kế hoạch rà soát đa luồng hiện trạng

## 1. Tác vụ nền hiện có
| Nhóm chức năng | Module/Hàm | Được kích hoạt từ | Mô hình thực thi | Ghi chú |
| --- | --- | --- | --- | --- |
| Phân tích chính | `AnalysisWorker.run` (`core/analysis_worker.py`) | `AppUI.start_analysis` tạo `Thread` nền | Luồng riêng + gọi `run_in_parallel` cho Giai đoạn 2 & 3 | Dựa trên `stop_event`; cập nhật UI qua `ui_queue`; thất bại một giai đoạn dừng toàn bộ.【F:APP/ui/app_ui.py†L914-L940】【F:APP/core/analysis_worker.py†L120-L166】
| Upload ảnh song song | `_execute_stage_3_logic` | Bên trong `AnalysisWorker` | `ThreadPoolExecutor` với `upload_workers`; hủy futures nếu `stop_event` set | Hủy bỏ thô nếu một ảnh lỗi; phụ thuộc cấu hình số worker.【F:APP/core/analysis_worker.py†L284-L341】
| Lưu báo cáo/song song hậu kỳ | `_stage_6_finalize_and_cleanup` | Sau khi phân tích | `run_in_parallel` để lưu MD/JSON; `ThreadPoolExecutor` xóa file đã upload | Không kiểm soát timeout; vẫn chạy khi `stop_flag` true.【F:APP/core/analysis_worker.py†L430-L475】
| Dịch vụ tin tức | `NewsService._background_worker` | `NewsService.start` khi AppUI khởi tạo | Luồng daemon riêng chờ `stop_event` | Lặp vô hạn với sleep `cache_ttl_sec`; callback chạy trên luồng dịch vụ.【F:APP/ui/app_ui.py†L229-L239】【F:APP/services/news_service.py†L82-L133】
| Làm mới tin tức đa nguồn | `NewsService._fetch_and_process_events` | Luồng tin tức | `ThreadPoolExecutor(max_workers=2)` | Timeout 15s mỗi nguồn; gọi callback ngoài lock.【F:APP/services/news_service.py†L216-L280】
| Tab biểu đồ: tải danh sách symbol | `ChartTab._populate_symbol_list` | Khi khởi tạo tab | `threading.Thread` daemon | Kết quả đẩy về UI qua `ui_queue`.|【F:APP/ui/components/chart_tab.py†L264-L279】
| Tab biểu đồ: tick định kỳ | `ChartTab._tick` | `ChartTab.start` gọi `root.after` | 2 luồng nền riêng `_info_worker_thread`, `_chart_worker_thread`; lịch `after` | Không join khi stop; `refresh_secs_var` điều khiển chu kỳ.【F:APP/ui/components/chart_tab.py†L281-L343】
| Tab biểu đồ: vẽ chart | `_redraw_chart_safe` | `_tick` hoặc người dùng đổi cấu hình | Gửi worker lên `ThreadingManager`; Future callback | Cần đảm bảo executor còn sống; không timeout khi lấy dữ liệu.【F:APP/ui/components/chart_tab.py†L522-L547】
| Tab biểu đồ: worker dữ liệu | `_update_info_worker`, `_chart_drawing_worker` | Bên trong `ChartTab` | Truy xuất MT5 đồng bộ + `run_in_parallel` | Nếu MT5 treo có thể chặn; kết quả đẩy về UI queue.【F:APP/ui/components/chart_tab.py†L305-L466】
| Autorun | `_autorun_tick` + `_autorun_tick_worker` | `root.after` theo `autorun_seconds_var` | Worker chạy trong `ThreadingManager`; requeue trên UI | Dừng khi `is_running` true; phụ thuộc trạng thái MT5.【F:APP/ui/app_ui.py†L1264-L1332】
| Quét thư mục ảnh | `_scan_folder_worker` | `_load_files` → `ThreadingManager.submit_task` | Executor chung | Cập nhật UI qua `ui_builder.enqueue`; có thể đọc nhiều file lớn.【F:APP/ui/app_ui.py†L963-L1016】
| Xuất báo cáo, cập nhật model, tải workspace,… | `_export_markdown_worker`, `_update_model_list_worker`, `_load_workspace_worker`, `_save_workspace_worker`, v.v. | Các hành động UI tương ứng | Executor chung `ThreadingManager` | Mỗi worker enqueue cập nhật UI; không quản lý backlog/đếm task.【F:APP/ui/app_ui.py†L871-L1168】
| MT5 nền | `_mt5_connect_worker`, `_mt5_check_connection_worker`, `_mt5_snapshot_worker` | Sự kiện UI / lịch 15s | Executor chung + `root.after` | `_mt5_snapshot_worker` tạo executor tạm thời với timeout 20s; check 15s cố định.【F:APP/ui/app_ui.py†L1360-L1464】
| API/.env & workspace | `_load_env_worker`, `_save_api_safe_worker`, `_delete_api_safe_worker`, `_delete_workspace_worker` | Hành động UI | Executor chung | Tác động file hệ thống; cập nhật UI qua queue/enqueue.【F:APP/ui/app_ui.py†L1480-L1629】
| Hàng đợi UI | `ui_builder.poll_ui_queue` | Khi AppUI khởi tạo | `root.after` 100ms | Xử lý callback nối tiếp trên luồng UI; không giới hạn kích thước hàng đợi.【F:APP/ui/utils/ui_builder.py†L650-L665】

## 2. Đồng bộ hóa UI và hành vi chặn
| Luồng nền | Cơ chế đồng bộ | Hành vi khi tác vụ dài | Nhận xét |
| --- | --- | --- | --- |
| Hầu hết worker AppUI/ChartTab | `app.ui_queue.put` + `poll_ui_queue` mỗi 100ms | UI không bị block nhưng queue có thể phình nếu worker đẩy quá nhanh | Không có backpressure hoặc log lỗi khi callback fail (bị nuốt).【F:APP/ui/utils/ui_builder.py†L650-L665】
| AnalysisWorker | Đẩy lambda lên `ui_queue` ở mọi giai đoạn | Nếu queue backlog, cập nhật progress/tree trễ; streaming AI phụ thuộc tốc độ UI | `stop_event` kiểm tra trước/giữa mỗi giai đoạn, nhưng stop thủ công không set event.【F:APP/core/analysis_worker.py†L120-L166】【F:APP/ui/app_ui.py†L942-L950】
| ChartTab redraw | Future callback → `ui_queue` | Nếu executor đầy hoặc worker treo, UI không refresh; không timeout khi gọi MT5 | Cần watchdog cho `_info_worker_thread` & future callback lỗi.【F:APP/ui/components/chart_tab.py†L305-L547】
| NewsService callback | Gọi trực tiếp callback (AppUI chuyển tiếp vào `ui_queue`) | Nếu callback chậm sẽ chặn vòng lặp nền; stop_event chỉ kiểm soát vòng `wait` | Cần đảm bảo callback luôn non-blocking.【F:APP/services/news_service.py†L216-L280】

## 3. Cơ chế dừng/hủy hiện tại
| Thành phần | Cơ chế hiện có | Khoảng trống / rủi ro |
| --- | --- | --- |
| Phân tích | `AppUI.stop_event` truyền vào `AnalysisWorker`; `shutdown` set event và join thread | `stop_analysis` chỉ set `stop_flag`, **không** set `stop_event`, nên luồng phân tích tiếp tục chạy tới khi xong; không join khi stop thường.【F:APP/ui/app_ui.py†L927-L951】【F:APP/ui/app_ui.py†L304-L320】
| Upload ảnh | Khi `stop_event` set trong lúc upload sẽ `cancel()` các future còn lại | Nếu stop không set event thì không hủy; cancel không check kết quả đã submit xong.【F:APP/core/analysis_worker.py†L296-L332】
| NewsService | `stop()` set `_stop_event` và join 5s | Nếu thread không dừng trong 5s chỉ log lỗi, không cưỡng bức dừng.【F:APP/services/news_service.py†L93-L104】
| ChartTab | `stop()` đặt `_running=False`, hủy `after` | Worker threads có thể vẫn chạy, không join; `_info_worker_thread`/`_chart_worker_thread` không kiểm tra cờ dừng riêng.【F:APP/ui/components/chart_tab.py†L256-L304】
| ThreadingManager | `shutdown(wait=True)` khi App đóng | Không có cancel cụ thể theo tác vụ; không giới hạn thời gian chờ trong `submit_task` (caller phải tự xử lý).【F:APP/utils/threading_utils.py†L32-L63】
| Autorun | Dừng bằng `root.after_cancel` khi tắt | Worker đang chạy không có cancel; rely on `is_running` checks tránh chạy song song.【F:APP/ui/app_ui.py†L1264-L1332】

## 4. Rủi ro chính
* **Không thể dừng phân tích thủ công** – thiếu `stop_event.set()` khiến thao tác "Dừng" không hiệu quả, worker vẫn chạy tới hết, dễ gây backlog UI và thao tác người dùng sai kỳ vọng.【F:APP/ui/app_ui.py†L942-L950】【F:APP/core/analysis_worker.py†L120-L166】
* **Rò rỉ luồng ChartTab** – các luồng daemon không được join; nếu MT5 treo, `_info_worker_thread` có thể nằm chờ vô hạn, tích tụ luồng mới mỗi tick sau khi stop/start lại.【F:APP/ui/components/chart_tab.py†L281-L347】
* **Executor chung bị nghẽn** – `ThreadingManager` giới hạn 10 worker; tác vụ dài (ví dụ MT5 snapshot 20s, quét thư mục lớn) có thể chặn các nhiệm vụ UI khác, gây hàng chờ dài trong `ui_queue` vì callback tới muộn.【F:APP/utils/threading_utils.py†L32-L63】【F:APP/ui/app_ui.py†L963-L1062】
* **`run_in_parallel` không hủy sau lỗi** – trả về `None` nhưng không propagate; callsite thường kỳ vọng dữ liệu hợp lệ, dễ gây lỗi ngầm hoặc race nếu một tác vụ thất bại (ví dụ context builder).【F:APP/utils/threading_utils.py†L65-L95】【F:APP/core/analysis_worker.py†L193-L341】
* **Race điều kiện Autorun** – Worker kiểm tra `is_running` nhưng giữa lúc enqueue `start_analysis` và UI xử lý có thể bật stop_event sai trạng thái; cần hàng đợi ưu tiên hoặc khóa để đảm bảo chỉ một phân tích chạy.【F:APP/ui/app_ui.py†L1298-L1332】
* **Backlog UI queue** – Không có logging khi callback ném exception; `poll_ui_queue` nuốt lỗi, khó phát hiện dead callback; queue không giới hạn kích thước nên có thể tăng memory nếu worker spam update (ví dụ streaming).【F:APP/ui/utils/ui_builder.py†L650-L665】

## 5. Chu kỳ & thông số cấu hình
| Hạng mục | Chu kỳ/Timeout | Nguồn cấu hình |
| --- | --- | --- |
| Autorun phân tích | `autorun_seconds_var` (mặc định 60s) qua `root.after` | Cài đặt UI, lưu trong workspace.【F:APP/ui/app_ui.py†L395-L396】【F:APP/ui/app_ui.py†L1285-L1291】
| Làm mới ChartTab | `refresh_secs_var` (mặc định 5s) | UI ChartTab; user có thể chỉnh spinner.【F:APP/ui/components/chart_tab.py†L68-L120】【F:APP/ui/components/chart_tab.py†L302-L304】
| Kiểm tra MT5 | `root.after(15000, ...)` (~15s) | Không cấu hình được qua UI hiện tại.【F:APP/ui/app_ui.py†L1379-L1404】
| Làm mới tin tức | `news_config.cache_ttl_sec` (mặc định 300s nếu chưa cấu hình) | `NewsService` đọc từ cấu hình RunConfig.【F:APP/services/news_service.py†L126-L131】
| Poll UI queue | 100ms | Hard-code trong `ui_builder.poll_ui_queue`.【F:APP/ui/utils/ui_builder.py†L650-L665】
| Upload ảnh song song | `upload_workers` (mặc định 4) | Biến UI `upload_workers_var`.【F:APP/ui/app_ui.py†L435-L436】【F:APP/core/analysis_worker.py†L302-L332】
| MT5 snapshot timeout | 20s | Executor tạm thời trong `_mt5_snapshot_worker`.【F:APP/ui/app_ui.py†L1449-L1464】
| News fetch timeout | 15s mỗi provider | `ThreadPoolExecutor` trong `NewsService`.|【F:APP/services/news_service.py†L240-L255】

## 6. Thông tin cần Product/QA làm rõ (cập nhật phản hồi)
| Chủ đề | Phản hồi từ Product/QA | Kế hoạch hành động / Lưu ý thêm |
| --- | --- | --- |
| Hành vi nút "Dừng" trong phân tích | Bấm "Dừng" phải hủy toàn bộ upload và AI streaming ngay lập tức. | Cần thiết kế lại `stop_analysis` để luôn `set()` `stop_event`, hủy Future đang chờ và ngắt luồng streaming thay vì để chạy tới hết vòng hiện tại.【F:APP/ui/app_ui.py†L942-L950】【F:APP/core/analysis_worker.py†L284-L341】 |
| Xung đột Autorun vs thao tác tay | Ưu tiên thao tác của người dùng; Autorun phải nhường và không được chạy song song. | Thiết kế hàng đợi ưu tiên hoặc khóa trạng thái để worker Autorun kiểm tra lại trước khi enqueue, bảo đảm chỉ một phiên phân tích chạy tại một thời điểm.【F:APP/ui/app_ui.py†L1298-L1332】 |
| Timeout cho dịch vụ MT5 & tin tức | Product chưa có ngưỡng cụ thể và mong muốn lấy đủ dữ liệu; đề nghị đặt timeout mặc định 10s cho truy vấn MT5 (đủ dài cho tick chậm nhưng không làm treo UI) và 20s cho từng nguồn tin tức, kèm retry giới hạn để tránh backlog vô hạn. | Cần xác nhận lại với Product/QA; khi triển khai, cấu hình timeout nên có thể thay đổi (config/UI) và log cảnh báo khi bị cắt ngắn để theo dõi SLA thực tế.【F:APP/ui/components/chart_tab.py†L305-L466】【F:APP/services/news_service.py†L216-L255】 |
| Quy mô dữ liệu ảnh tối đa | Tối đa hiện tại 4 ảnh, tương lai không quá 10 ảnh. | Có thể giữ `upload_workers` mặc định 4 nhưng thêm guard để giới hạn queue và cân nhắc batch upload ≤10 ảnh; tài nguyên bộ nhớ có thể được tính toán dựa trên giới hạn này.【F:APP/core/analysis_worker.py†L284-L341】 |
| Tần suất làm mới UI | Muốn đồng bộ theo tick thời gian thực của MT5. | Cần nghiên cứu điều chỉnh `refresh_secs_var` xuống theo tick (ví dụ 1s hoặc hook realtime API) và giảm `ui_queue` poll 100ms nếu cần; bổ sung cơ chế skip frame khi backlog để tránh nghẽn UI.【F:APP/ui/components/chart_tab.py†L302-L304】【F:APP/ui/utils/ui_builder.py†L650-L665】 |
| Đóng ứng dụng | Phải đảm bảo tất cả tác vụ nền hoàn tất trước khi thoát. | `ThreadingManager.shutdown` cần `join` sạch mọi luồng/future, có timeout và hiển thị tiến trình đóng; cân nhắc modal cảnh báo nếu có tác vụ lâu (ví dụ lưu báo cáo).【F:APP/ui/app_ui.py†L304-L338】【F:APP/core/analysis_worker.py†L430-L475】 |

## 7. Kiến trúc đa luồng đề xuất

### 7.1 Sơ đồ khối cấp cao

```
+-----------------+       +-------------------+       +------------------+
|      AppUI      | <---> |  ThreadingManager | <---> |  Worker Pools    |
+-----------------+       +-------------------+       +------------------+
        |                          |                           |
        | UI Queue / Facade APIs   | TaskGroup APIs            | Specialized
        v                          v                           v
  +-------------+        +-------------------+        +----------------------+
  |  ChartTab   |<------>|  AnalysisWorker   |<------>| External Services    |
  +-------------+        +-------------------+        +----------------------+
        |                           |                          |
        v                           v                          v
  NewsService Facade        MT5 Data Facade             Storage/AI Clients
```

* **AppUI**: vẫn giữ luồng chính, chỉ tương tác qua Facade bất đồng bộ và nhận cập nhật qua `ui_queue` với cơ chế giám sát mới.
* **ThreadingManager 2.0**: chịu trách nhiệm quản lý `TaskGroup`, timeout, retry, cancel, metrics.
* **Worker Pools**: tách thành các nhóm chuyên biệt (CPU-bound cho AI, I/O-bound cho MT5/news, short-lived UI tasks) để tránh nghẽn.
* **Facade chuyên biệt**: `AnalysisController`, `NewsController`, `ChartController` cung cấp API tương tác với ThreadingManager.

### 7.2 Chiến lược TaskGroup & điều khiển vòng đời

| TaskGroup | Thành phần | Loại tác vụ | Chính sách timeout | Chính sách retry | Cơ chế dừng |
| --- | --- | --- | --- | --- | --- |
| `analysis.session` | `AnalysisWorker` (các stage 1-6) | CPU/I/O hỗn hợp | Timeout tổng `analysis_timeout` (mặc định 5 phút), sub-timeout cho Stage 2 (AI streaming, 60s không có token) | Retry toàn phiên = 0 (ngừng ngay, báo lỗi); từng ảnh upload retry 2 lần backoff tuyến tính | `cancel_group` khi `stop_event` hoặc Autorun bị huỷ; join cưỡng bức sau 10s với log cảnh báo |
| `analysis.upload` | Upload ảnh song song | I/O | Timeout 30s/ảnh | Retry 2 lần, delay 1s/2s | Kế thừa `cancel_group` từ session, dừng ngay khi session cancel |
| `ui.short` | Các worker UI nhẹ (quét thư mục, export nhỏ) | I/O nhanh | Timeout 10s mặc định, caller có thể override | Retry 1 lần nếu lỗi I/O tạm thời | `cancel_task` riêng lẻ khi đóng ứng dụng hoặc người dùng hủy |
| `chart.refresh` | `_info_worker`, `_chart_drawing_worker` | MT5 I/O | Timeout 10s cho MT5 query; hủy nếu quá 2 lần liên tiếp timeout | Retry vô hạn nhưng theo chính sách degrade (giảm tần suất khi MT5 lỗi) | Stop khi tab đóng hoặc ứng dụng tắt; join với grace 5s |
| `news.polling` | `NewsService` fetch | I/O | Timeout 20s mỗi provider | Retry 3 lần với exponential backoff; fallback cache | Stop khi app shutdown; join 5s, log nếu vượt |

`ThreadingManager` mới hỗ trợ:

* `create_task_group(name, *, max_concurrency, queue_limit, on_state_change)` trả về context quản lý tác vụ.
* `submit(group, callable, *, cancel_token, timeout, retry_policy, metadata)` đăng ký tác vụ với metadata phục vụ logging.
* `cancel_group(name, reason)` hủy mọi tác vụ đang chạy/chờ trong nhóm; đảm bảo propagate `cancel_token`.
* `await_idle(group, deadline)` dùng khi đóng ứng dụng để chờ nhóm rỗng.

### 7.3 Luồng đời tác vụ mẫu

1. **Khởi tạo**
   * UI gọi Facade (ví dụ `AnalysisController.start_session(request)`).
   * Facade chuẩn hóa input, tạo `cancel_token`, đăng ký `TaskGroupContext` và phát sự kiện telemetry "scheduled".
   * `ThreadingManager` push task vào hàng chờ nhóm tương ứng.
2. **Thực thi**
   * Worker lấy task từ nhóm, bọc trong `with cancel_scope, timeout_scope`.
   * Task báo tiến độ định kỳ qua `ui_queue.enqueue(UpdatePayload)`; hệ thống đo độ trễ và log warning nếu backlog > ngưỡng.
   * Khi gặp lỗi recoverable, `RetryPolicy` quyết định có retry hay không; mọi retry đều ghi log `warning` với attempt.
3. **Hủy bỏ**
   * Người dùng bấm "Dừng" → Facade gọi `cancel_group("analysis.session", reason="user_stop")` + set `cancel_token`.
   * Từng worker phát hiện `cancel_token.is_cancelled()` hoặc nhận `CancelledError` (từ timeout scope) và chuyển sang giai đoạn cleanup.
4. **Cleanup**
   * Task chạy khối `finally`: đóng file, rollback upload dang dở, ghi log "cancelled".
   * Facade gửi cập nhật UI "stopped" với timestamp, metrics (thời gian chạy, số ảnh thành công/thất bại).

### 7.4 Facade/API mới

| Facade | API chính | Mô tả | Ghi chú triển khai |
| --- | --- | --- | --- |
| `AnalysisController` | `start_session(request)`, `stop_session(session_id)`, `get_status(session_id)` | Quản lý vòng đời phân tích; map sang TaskGroup `analysis.session`. | `start_session` trả về `session_id`; `stop_session` gọi cancel + cập nhật UI. |
| `ChartController` | `start_stream(symbol)`, `stop_stream(symbol)`, `request_snapshot(symbol, options)` | Điều phối tick realtime và snapshot MT5. | `start_stream` đăng ký listener, worker push data qua Facade để UI nhận. |
| `NewsController` | `start_polling()`, `stop_polling()`, `refresh_now()` | Điều phối NewsService, cho phép refresh thủ công ưu tiên người dùng. | `refresh_now` enqueue task ưu tiên cao bỏ qua lịch TTL. |
| `ThreadingManager` (mới) | `create_task_group`, `submit`, `cancel_group`, `cancel_task`, `await_idle`, `shutdown(force=False)` | Lõi điều phối đa luồng. | Hỗ trợ hook telemetry & logging tiêu chuẩn. |
| `UIQueueMonitor` | `start()`, `stop()`, `get_metrics()` | Đo backlog UI, log cảnh báo >N mục hoặc callback lỗi. | Chạy trên luồng UI, flush metrics sang logger/telemetry. |

### 7.5 Logging & Monitoring

* **Chuẩn metadata**: mọi task đăng ký `metadata={"component": ..., "task": ..., "session_id": ...}` để logger format `%{component}/%{task}`.
* **Level**:
  * `INFO`: Task scheduled, started, completed, cancelled (với duration, retry_count).
  * `WARNING`: Timeout, retry, backlog UI > ngưỡng, cancel cưỡng bức khi shutdown.
  * `ERROR`: Lỗi không recoverable, task fail sau retry cuối.
* **Telemetry hooks**: ThreadingManager phát sự kiện `task_scheduled`, `task_started`, `task_completed` để tích hợp Grafana/Prometheus (khi có).
* **UI queue monitor**: đo `len(queue)` mỗi 100ms; nếu >50, log warning và phát tín hiệu backpressure (ChartController có thể giảm tần suất refresh tạm thời).
* **Audit trail**: ghi file JSON (rolling) chứa lịch sử task quan trọng (analysis session, autorun) phục vụ QA.

### 7.6 Ảnh hưởng cấu hình & tương thích

| Mục | Ảnh hưởng | Backward compatibility | Biện pháp giảm thiểu |
| --- | --- | --- | --- |
| Timeout mới (MT5 10s, News 20s, upload 30s) | Cần expose cấu hình (UI/`config.json`) | Mặc định đặt theo đề xuất, cho phép override để không phá workflow cũ | Hiển thị cảnh báo khi hit timeout để người dùng điều chỉnh |
| Realtime chart (tick-based) | Tăng tần suất worker chart | UI cũ vẫn hoạt động nếu chọn chế độ "legacy" refresh 5s | Cho phép toggle "Realtime" vs "Interval" trong UI |
| TaskGroup queue limit | Có thể từ chối task nếu backlog quá lớn | Facade trả về thông báo lỗi thân thiện, hướng dẫn thử lại | Log metrics để tinh chỉnh limit |
| Shutdown strict join | App đóng chậm hơn nếu còn tác vụ dài | Giữ option "Force quit" để vẫn cho phép thoát nhanh | Hiển thị dialog tiến trình khi đóng |

### 7.7 Rủi ro & kiểm soát

* **Deadlock giữa Facade và UI**: đảm bảo mọi callback UI chạy trên luồng chính và không gọi ngược lại Facade đồng bộ; thêm tài liệu hướng dẫn dev.
* **Starvation khi ưu tiên người dùng**: Autorun bị trì hoãn vô hạn nếu người dùng thao tác liên tục; cần logic reschedule sau X phút để nhắc nhở.
* **Chi phí refactor cao**: phân tách Facade & TaskGroup đòi hỏi chỉnh sửa rộng; lên kế hoạch rollout từng module (Analysis → Chart → News).
* **Telemetry overload**: log quá nhiều khi poll realtime; thêm sampling/tần suất báo cáo.

### 7.8 Checklist triển khai

- [ ] Thiết kế và implement `ThreadingManager` mới với hỗ trợ TaskGroup, cancel token, timeout, retry.
- [ ] Xây dựng Facade `AnalysisController`, `ChartController`, `NewsController` và migrate AppUI sử dụng.
- [ ] Cập nhật `AnalysisWorker` để tôn trọng cancel ngay lập tức và tái cấu trúc stage theo TaskGroup.
- [ ] Tách chart workers thành stream realtime + snapshot với timeout và degrade mode.
- [ ] Điều chỉnh NewsService sử dụng TaskGroup và timeout/backoff mới.
- [ ] Tích hợp UI Queue Monitor và logging chuẩn hóa metadata.
- [ ] Bổ sung cấu hình UI/JSON cho timeout, realtime toggle, queue limit.
- [ ] Viết tài liệu hướng dẫn QA/Product về hành vi mới (stop nhanh, autorun ưu tiên người dùng, shutdown).
- [ ] Cập nhật bộ kiểm thử/tài liệu đảm bảo backward compatibility (legacy refresh, force quit).


