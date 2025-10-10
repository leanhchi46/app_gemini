# Trạng thái triển khai refactor đa luồng

Tài liệu này đối chiếu tiến độ thực tế với Work Breakdown Structure (WBS) trong kế hoạch `docs/multithreading_refactor_plan.md`.

## Tóm tắt cấp cao

| WBS | Phạm vi | Trạng thái | Ghi chú chính |
| --- | --- | --- | --- |
| 8.1 | ThreadingManager 2.0 & bộ công cụ QA | Hoàn tất | API `submit`/`cancel_group`/`await_idle` mới và fixture test đã có sẵn. |
| 8.2 | ChartTab refactor | Hoàn tất | `ChartController` điều phối task group `chart.refresh`, backlog guard được test. |
| 8.3 | NewsService refactor | Hoàn tất | `NewsController` + timeout provider 20s, ưu tiên người dùng qua `refresh_now`. |
| 8.4 | AnalysisWorker refactor | Hoàn tất | `AnalysisController` quản lý session, pipeline dùng `CancelToken` và giới hạn upload ≤10 ảnh. |
| 8.5 | AppUI tích hợp & shutdown | Hoàn tất | AppUI dùng facade IO/MT5 mới, autorun ưu tiên người dùng, shutdown dialog + UI queue monitor và feature flag rollback đã kích hoạt. |

## Chi tiết theo hạng mục

### 8.1 ThreadingManager & công cụ test
- `ThreadingManager` mở rộng với `CancelToken`, `TaskRecord`, timeout monitor, `cancel_group`, `await_idle`, `shutdown(force)` theo yêu cầu kiến trúc mới.【F:APP/utils/threading_utils.py†L22-L242】
- Giữ `submit_task` legacy để hỗ trợ phần UI chưa refactor hoàn toàn (phục vụ giai đoạn 8.5).【F:APP/utils/threading_utils.py†L168-L174】
- `tests/conftest.py` cung cấp stub/thư viện giả hỗ trợ fixture kiểm thử như kế hoạch 8.1.2.【F:tests/conftest.py†L1-L121】

### 8.2 Module ChartTab
- `ChartController` đóng gói luồng realtime, sử dụng TaskGroup `chart.refresh`, metadata logging và backlog guard UI.【F:APP/ui/controllers/chart_controller.py†L16-L168】
- `ChartTab` khởi tạo controller, bỏ toàn bộ lời gọi `ThreadingManager.submit_task` trực tiếp cho worker biểu đồ.【F:APP/ui/components/chart_tab.py†L33-L122】【F:APP/ui/components/chart_tab.py†L330-L360】
- Unit test xác minh metadata, backlog guard và huỷ nhóm theo checklist PR.【F:tests/controllers/test_chart_controller.py†L61-L123】

### 8.3 Module NewsService
- `NewsController` quản lý `news.polling`, cung cấp API `start_polling`, `refresh_now`, `stop_polling` với ưu tiên người dùng khi refresh khẩn.【F:APP/ui/controllers/news_controller.py†L16-L127】
- `NewsService.refresh` sử dụng TaskGroup thông qua ThreadingManager, timeout provider cấu hình, retry/cancel token, đồng bộ cache và logging latency.【F:APP/services/news_service.py†L193-L325】
- Bộ test controller/service bao phủ cancel token, TTL và ưu tiên thao tác tay.【F:tests/controllers/test_news_controller.py†L1-L168】【F:tests/services/test_news_service.py†L1-L200】
- Provider TE/FMP fallback SSL/network trả về danh sách rỗng thay vì raise, chỉ log cảnh báo để UI không lỗi khi offline.【F:APP/services/te_service.py†L60-L82】【F:APP/services/fmp_service.py†L72-L111】

### 8.4 Module AnalysisWorker
- `AnalysisController` điều phối session `analysis.session`, gắn metadata và dọn dẹp khi future hoàn tất.【F:APP/core/analysis_controller.py†L16-L84】
- `AnalysisWorker` nhận `CancelToken`, kiểm tra `_is_cancelled`, giới hạn upload ≤10 ảnh và sử dụng TaskGroup `analysis.upload` cho batch upload; `_drain_upload_record` xử lý cancel ngay lập tức.【F:APP/core/analysis_worker.py†L37-L190】【F:APP/core/analysis_worker.py†L312-L409】
- Unit test đảm bảo `stop_session` cancel cả `analysis.session` lẫn `analysis.upload` như checklist.【F:tests/core/test_analysis_controller.py†L64-L76】

### 8.5 Module AppUI & Shutdown
- AppUI tương tác với tất cả worker nền thông qua `AnalysisController`, `IOController`, `MT5Controller`, bảo đảm không còn lời gọi `submit_task` trực tiếp.【F:APP/ui/app_ui.py†L262-L1660】【F:APP/ui/controllers/io_controller.py†L1-L66】【F:APP/ui/controllers/mt5_controller.py†L1-L88】
- Autorun ưu tiên thao tác người dùng thông qua hàng đợi trong `AnalysisController.enqueue_autorun`, có unit test mô phỏng race condition.【F:APP/core/analysis_controller.py†L18-L134】【F:tests/core/test_analysis_controller.py†L76-L105】
- Quy trình shutdown hiển thị `ShutdownDialog`, log backlog UI, chờ toàn bộ TaskGroup qua `await_idle` rồi mới hạ executor; test end-to-end xác nhận thứ tự gọi.【F:APP/ui/app_ui.py†L252-L362】【F:APP/ui/utils/ui_builder.py†L640-L726】【F:tests/ui/test_app_ui_shutdown.py†L1-L73】
- README mô tả facade mới, UI queue monitor và feature flag rollback phục vụ đội vận hành.【F:README.md†L1-L53】

## Đề xuất bước tiếp theo
1. Theo dõi QA regression với cả hai chế độ feature flag (`USE_NEW_THREADING_STACK=0/1`) trước khi phát hành chính thức.
2. Thu thập feedback thực tế về ShutdownDialog và ngưỡng backlog để tinh chỉnh `ui_backlog_warn_threshold` nếu cần.
3. Chuẩn bị checklist rollout production (scripts bật/tắt flag, hướng dẫn giám sát log) cho buổi handover với đội vận hành.【F:docs/multithreading_test_plan.md†L90-L123】
