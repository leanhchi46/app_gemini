# PyQt6 Health Check

## Smoke Test
1. Chạy `python APP/main.py` để khởi tạo giao diện PyQt6. Xác nhận các tab Overview, Chart, News hiển thị và không báo lỗi.
2. Chọn chức năng autorun: `Overview > Autorun > Start` và theo dõi log trạng thái trong panel → `telemetry.ui_backend=pyqt6`.
3. Sử dụng tab Prompt để nạp prompt mẫu, kiểm tra preview Markdown trong tab Report.

## Threading & Controller Hooks
- Xác nhận `AnalysisController` nhận lệnh chạy từ UI (nút Run Manual) và ghi log `analysis.session`.
- Tab News hiển thị payload mới sau khi chạy `Refresh now`, backlog UI không vượt ngưỡng cảnh báo.

## Legacy Tkinter Fallback
1. `python APP/main.py --use-tk` hiển thị deprecation warning trong log.
2. Thực hiện shutdown (nút Close) để xác nhận quy trình thu dọn vẫn hoạt động.

## Tài liệu bổ sung
- README.md mục "UI backend (PyQt6)"
- docs/pyqt6_migration_plan.md (Giai đoạn 6)
