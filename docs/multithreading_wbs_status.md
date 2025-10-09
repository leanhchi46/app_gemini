# Trạng thái triển khai refactor đa luồng

Tài liệu này đối chiếu tiến độ thực tế với Work Breakdown Structure (WBS) trong kế hoạch `docs/multithreading_refactor_plan.md`.

## Tóm tắt cấp cao

| WBS | Phạm vi | Trạng thái | Ghi chú chính |
| --- | --- | --- | --- |
| 8.1 | ThreadingManager 2.0 & bộ công cụ QA | Hoàn tất | API `submit`/`cancel_group`/`await_idle` mới và fixture test đã có sẵn. |
| 8.2 | ChartTab refactor | Hoàn tất | `ChartController` điều phối task group `chart.refresh`, backlog guard được test. |
| 8.3 | NewsService refactor | Hoàn tất | `NewsController` + timeout provider 20s, ưu tiên người dùng qua `refresh_now`. |
| 8.4 | AnalysisWorker refactor | Hoàn tất | `AnalysisController` quản lý session, pipeline dùng `CancelToken` và giới hạn upload ≤10 ảnh. |
| 8.5 | AppUI tích hợp & shutdown | **Đang dở dang** | AppUI đã dùng controller cho start/stop nhưng vẫn còn nhiều lời gọi `submit_task` legacy, chưa có feature flag tổng & UI queue monitor. |

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

### 8.4 Module AnalysisWorker
- `AnalysisController` điều phối session `analysis.session`, gắn metadata và dọn dẹp khi future hoàn tất.【F:APP/core/analysis_controller.py†L16-L84】
- `AnalysisWorker` nhận `CancelToken`, kiểm tra `_is_cancelled`, giới hạn upload ≤10 ảnh và sử dụng TaskGroup `analysis.upload` cho batch upload; `_drain_upload_record` xử lý cancel ngay lập tức.【F:APP/core/analysis_worker.py†L37-L190】【F:APP/core/analysis_worker.py†L312-L409】
- Unit test đảm bảo `stop_session` cancel cả `analysis.session` lẫn `analysis.upload` như checklist.【F:tests/core/test_analysis_controller.py†L64-L76】

### 8.5 Module AppUI & Shutdown
- AppUI đã gọi `AnalysisController` trong `start_analysis/stop_analysis`, đáp ứng yêu cầu ưu tiên thao tác người dùng.【F:APP/ui/app_ui.py†L918-L960】
- Tuy nhiên vẫn còn nhiều worker UI sử dụng `threading_manager.submit_task` legacy (`_scan_folder_worker`, export, MT5, v.v.), nên checklist "UI chỉ tương tác qua Facade" chưa đạt.【F:APP/ui/app_ui.py†L989-L1026】
- Chưa có feature flag tổng `USE_NEW_THREADING_STACK`, UI queue monitor hay cập nhật shutdown dialog như mục 8.5.2-8.5.3; cần triển khai tiếp để đáp ứng bảng checklist.【F:docs/multithreading_refactor_plan.md†L301-L314】

## Đề xuất bước tiếp theo
1. **Hoàn tất 8.5.1**: thay thế các lời gọi `threading_manager.submit_task` còn lại trong AppUI bằng facade chuyên trách (tạo thêm controller cho MT5/file I/O nếu cần) và bổ sung feature flag tổng cho phép rollback.【F:APP/ui/app_ui.py†L989-L1026】【F:docs/multithreading_refactor_plan.md†L301-L314】
2. **Triển khai 8.5.2**: hiện thực hoá hàng đợi ưu tiên Autorun vs thao tác tay dựa trên API controller mới, kèm unit test mô phỏng race condition như hướng dẫn.【F:docs/multithreading_refactor_plan.md†L303-L333】
3. **Triển khai 8.5.3**: sử dụng `ThreadingManager.await_idle`/`shutdown` trong quy trình đóng app, bổ sung dialog tiến trình và logging backlog UI, đồng thời viết test end-to-end theo checklist.【F:APP/utils/threading_utils.py†L217-L242】【F:docs/multithreading_refactor_plan.md†L303-L337】
4. **8.5.4 Tài liệu**: cập nhật README/hướng dẫn vận hành để mô tả facade mới, UI queue monitor và feature flag rollback theo checklist tài liệu.【F:docs/multithreading_refactor_plan.md†L301-L314】

Hoàn thành các hạng mục trên sẽ kết thúc Sprint 6 trong kế hoạch và thoả tiêu chí tổng thể của dự án.【F:docs/multithreading_refactor_plan.md†L353-L361】
