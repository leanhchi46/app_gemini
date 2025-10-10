# APP Gemini – Kiến trúc đa luồng mới

Tài liệu này tóm tắt cách vận hành kiến trúc đa luồng sau giai đoạn refactor, đồng thời cung cấp hướng dẫn rollback khi cần.

## Facade/Controller cho UI

| Thành phần | Facade | Nhóm task | Ghi chú |
| --- | --- | --- | --- |
| Phân tích | `AnalysisController` | `analysis.session`, `analysis.upload` | Hỗ trợ hàng đợi autorun và ưu tiên thao tác tay, truyền `on_start` để UI cập nhật trạng thái. |
| Biểu đồ | `ChartController` | `chart.refresh` | Kiểm soát luồng realtime với backlog guard dựa trên `ui_queue`. |
| Tin tức | `NewsController` | `news.polling` | Ưu tiên người dùng, tích hợp timeout provider. |
| Tệp & I/O | `IOController` | `ui.*` (scan, export, workspace…) | Bao bọc mọi thao tác file/ENV/API key, gắn metadata đồng bộ logging. |
| MT5 | `MT5Controller` | `mt5.connect/check/snapshot` | Đảm bảo cancel group trước khi gửi tác vụ mới, phục vụ kết nối & snapshot. |

> **Lưu ý:** UI không gọi `ThreadingManager.submit_task` trực tiếp nữa. Mọi worker phải đi qua facade tương ứng để hưởng lợi từ cancel token, metadata và feature flag rollback.

## Feature flag rollback

- Biến môi trường: `USE_NEW_THREADING_STACK`
- Mặc định: `True`
- Khi đặt về `0`/`false`/`off`, AppUI và các controller phụ trợ sẽ quay lại hành vi legacy (`submit_task` trực tiếp). Dùng cho tình huống cần rollback khẩn cấp trong ≤5 phút theo checklist WBS.

## UI queue monitor

- `ui_builder.poll_ui_queue` đo backlog mỗi 100 ms.
- Nếu `queue.qsize()` vượt `app.ui_backlog_warn_threshold` (mặc định 50), hệ thống log cảnh báo và ghi nhận thời điểm cuối cùng để tránh spam.
- Backlog cũng được chụp lại trong quy trình shutdown giúp QA đánh giá tình trạng nghẽn UI.

## Quy trình shutdown an toàn

1. Huỷ timer autorun/MT5 và dừng các controller.
2. Hiển thị `ShutdownDialog` thông báo tiến trình cho người dùng.
3. Lưu workspace, ngắt MT5, log backlog UI.
4. Gọi `ThreadingManager.await_idle` cho mọi nhóm (`analysis.session`, `analysis.upload`, `news.polling`, `chart.refresh`).
5. Đóng executor qua `ThreadingManager.shutdown(wait=True, timeout=5.0)` rồi huỷ cửa sổ.

## Kiểm thử bắt buộc

```bash
pytest tests/controllers/test_chart_controller.py \
       tests/controllers/test_news_controller.py \
       tests/services/test_news_service.py \
       tests/core/test_analysis_controller.py \
       tests/ui/test_app_ui_threading.py \
       tests/ui/test_app_ui_shutdown.py
```

## Tham khảo thêm

- [Kế hoạch refactor đa luồng](docs/multithreading_refactor_plan.md)
- [Test plan & checklist QA](docs/multithreading_test_plan.md)
- [Báo cáo tiến độ WBS](docs/multithreading_wbs_status.md)
