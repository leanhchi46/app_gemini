# Kế hoạch chuyển đổi PyQt6

## Giai đoạn 0 – Chuẩn bị hiện trạng (Hoàn thành)
### Cấu hình, lưu trữ và phụ thuộc dịch vụ
- `APP/configs/workspace_config.py` chịu trách nhiệm tạo workspace, nạp JSON cấu hình và tự động mã hóa/giải mã các khóa nhạy cảm (`telegram.token`, `fmp.api_key`, `te.api_key`) thông qua tiện ích `APP.utils.general_utils`. Các helper về thư mục báo cáo và bộ nhớ đệm upload giúp toàn dự án dùng chung một nguồn sự thật.
- Quy trình khởi động trong `APP/main.py` tải cấu hình workspace, khởi tạo `LoggingConfig`, cài đặt logging bằng `APP.persistence.log_handler.setup_logging`, sau đó mới dựng UI để bảo đảm mọi lỗi sớm đều được ghi lại.
- `AppUI` kết hợp các service nghiệp vụ (`NewsService`, `gemini_service`, `mt5_service`) cùng controller (`AnalysisController`, `IOController`, `MT5Controller`, `NewsController`) và sở hữu chung `ThreadingManager`. Các tác vụ nền đẩy callback về hàng đợi UI nhằm duy trì ranh giới rõ ràng giữa logic và toolkit giao diện.

### Vòng lặp Tkinter & điều phối luồng
- `APP/main.py` khởi tạo Tk root, gán `AppUI.shutdown` cho sự kiện `WM_DELETE_WINDOW` rồi mới gọi `root.mainloop()`, nhờ vậy quá trình đóng cửa sổ luôn giải phóng tài nguyên.
- Bên trong `AppUI`, mọi tác vụ nền được gửi qua `ThreadingManager.submit`, các luồng worker đưa callback vào `AppUI.ui_queue` thay vì thao tác trực tiếp lên widget. `APP/ui/utils/ui_builder.poll_ui_queue` rút queue mỗi 100ms bằng `root.after` và cảnh báo khi backlog vượt `ui_backlog_warn_threshold`.
- Các job định kỳ khác (watch thư mục, autorun, kiểm tra kết nối MT5) cũng tận dụng `root.after`, tạo nên lịch sự kiện cần được ánh xạ sang signal/slot khi chuyển qua PyQt6.

### Kiểm thử baseline
- Đã chạy `pytest` để ghi nhận hành vi hiện tại: 40 kiểm thử (bao gồm UI/threading) đều đậu trên Python 3.12.10.

## Giai đoạn 1 – Tách logic khỏi Tkinter (Hoàn thành)
- Tạo gói `APP.ui.state` với các lớp bất biến `UiConfigState`, `AutorunState`, `PromptState` gom cấu hình UI thuần Python và hỗ trợ chuyển đổi sang `RunConfig`/payload workspace.
- `AppUI` chuyển sang xây dựng `_build_config_state()` thay vì truy cập trực tiếp `tk.Variable`, giúp controller/service chỉ thao tác với trạng thái trung lập.
- Bổ sung kiểm thử `tests/ui/test_config_state.py` để bảo đảm quá trình chuyển đổi state ↔ workspace nhất quán và không phụ thuộc toolkit.

## Giai đoạn 2 – Dựng khung PyQt6 (Hoàn thành)
- Khởi tạo gói `APP.ui.pyqt6` với `PyQtApplication` quản lý vòng đời `QApplication`, `ThreadingManager` và queue UI chung cho giai đoạn chuyển tiếp.
- Xây dựng `TradingMainWindow` dựa trên `QMainWindow`/`QTabWidget`, tạo ba tab nền tảng (Tổng quan, Biểu đồ, Tin tức) hiển thị dữ liệu từ `UiConfigState` và cung cấp các nút tương tác mẫu.
- Tạo `UiQueueBridge` cùng `QtThreadingAdapter` để ánh xạ hàng đợi callback Tkinter sang signal/slot PyQt6, đồng thời thêm kiểm thử `tests/ui/test_pyqt6_bridge.py` xác nhận kết quả và lỗi được đưa về thread giao diện.

- `TradingMainWindow` nay bao gồm năm tab PyQt6 độc lập (Tổng quan, Biểu đồ, Tin tức, Prompt, Lịch sử) nhằm bám sát bố cục Tkinter cũ và cho phép triển khai dần các controller thật.
- `OverviewTab` phát tín hiệu điều phối start/stop autorun, quản lý nhật ký; `ChartTabWidget` tiếp nhận thay đổi cấu hình stream và cập nhật snapshot; `NewsTabWidget` hiển thị bảng tin với trạng thái tải và tùy chọn bỏ qua chặn tin.
- `PromptTabWidget` cho phép đọc/ghi prompt JSON, định dạng lại văn bản bằng pipeline `_normalize_prompt_text` và đồng bộ chế độ auto-load từ cấu hình.
- `HistoryTabWidget` quét thư mục `Reports/` cho từng symbol để hiển thị báo cáo `.md` và ngữ cảnh `.json`, đồng thời cho phép xem trước nội dung theo cơ chế callback PyQt6.
- Các handler trong `TradingMainWindow` đã được ánh xạ sang `QtThreadingAdapter`/`UiQueueBridge`, bảo đảm tác vụ nền ghi nhận kết quả vào tab tương ứng mà không chặn thread giao diện.

- Hoàn thiện `DialogProvider` và bộ hộp thoại PyQt6 (`ShutdownDialog`, `JsonPreviewDialog`) thay thế tiện ích Tkinter, hỗ trợ chọn tệp, mở thư mục và xem JSON ngay trong ứng dụng.
- Bổ sung `ReportTabWidget` để hiển thị danh sách báo cáo Markdown, xem nhanh nội dung, mở hoặc xoá tệp trực tiếp từ PyQt6.
- Dựng `OptionsTabWidget` gom toàn bộ cấu hình API, Context, No-Run/No-Trade, AutoTrade và dịch vụ; mọi thay đổi phát tín hiệu `config_changed` để chuẩn bị nối với controller.
- Cập nhật `TradingMainWindow` tích hợp tab Báo cáo, Tuỳ chọn cùng dialog provider mới; mở rộng kiểm thử bao phủ luồng làm mới báo cáo và thao tác Options.
- Mở rộng `TradingMainWindow` với hàm `snapshot_ui_state()` và `build_workspace_payload()` nhằm tái tạo `UiConfigState` thuần dữ liệu và tạo payload workspace hoàn chỉnh (kèm nội dung prompt) phục vụ Giai đoạn 4.
- Bổ sung spinner quản lý `max_md_reports` trong tab General, đảm bảo tương đương tính năng Tkinter và được xuất ra payload Options.
- Hoàn thiện API tương thích Tkinter (`ui_status`, `ui_progress`, `ui_detail_replace`, hộp thoại thông báo) ngay trên `TradingMainWindow` để các controller hiện hữu có thể chuyển sang PyQt6 mà không cần sửa logic hàng đợi.

## Giai đoạn 4 – Đồng bộ controller & thread (Hoàn thành)
- Thiết lập `ControllerCoordinator` và `ControllerSet` để gom Analysis/IO/Chart/News/MT5 controller dùng chung `ThreadingManager`, đồng thời cập nhật `NewsService` dựa trên `UiConfigState` khởi tạo.
- `TradingMainWindow` tiếp nhận controller set, khởi động stream biểu đồ qua `ChartController.start_stream`, đăng ký polling tin tức với `NewsController.start_polling` và chuyển mọi callback về thread UI thông qua `UiQueueBridge`.
- PromptTab chuyển sang `_submit_io_task` gói `IOController.run`, đưa kết quả future trở lại UI và bảo đảm trạng thái loading được xử lý chính xác.
- Các handler tin tức/biểu đồ ưu tiên gọi controller thật (`refresh_now`, `trigger_refresh`, `request_snapshot`) nhưng vẫn có fallback mock để phục vụ kiểm thử nếu thiếu controller.
- Bổ sung kiểm thử PyQt6 cho cầu nối controller (prompt/news/chart) nhằm xác nhận queue bridge cập nhật widget đúng.
- Tạo `PyQtAnalysisAppAdapter` ánh xạ API Tkinter cho `AnalysisWorker`, bật chạy/huỷ phiên phân tích thật qua `AnalysisController` và lập lịch autorun bằng `QTimer` để khớp luồng nền với PyQt6.

## Checklist theo giai đoạn

### Giai đoạn 0 – Chuẩn bị & kiểm thử hiện trạng
- [x] Rà soát cấu hình, lưu trữ và phụ thuộc dịch vụ dùng chung trong toàn dự án.
- [x] Chạy toàn bộ kiểm thử tự động để chốt baseline trước khi refactor.
- [x] Tài liệu hóa vòng lặp Tkinter, cơ chế queue và các tác vụ định kỳ cần bảo toàn.

### Giai đoạn 1 – Tách logic khỏi Tkinter
- [x] Hoàn thiện lớp trạng thái trung lập thay thế `tk.Variable` cho phần cấu hình.
- [x] Điều chỉnh controller/service sử dụng state mới thay vì truy cập widget trực tiếp.
- [x] Bổ sung kiểm thử xác thực state trung lập để đảm bảo hành vi đồng nhất giữa toolkit.

### Giai đoạn 2 – Dựng khung PyQt6
- [x] Khởi tạo `PyQtApplication` điều phối QApplication, ThreadingManager và queue UI.
- [x] Dựng `TradingMainWindow` với bố cục tab tương đương Tkinter và liên kết `UiConfigState`.
- [x] Tạo cầu nối signal/slot (`UiQueueBridge`, `QtThreadingAdapter`) kèm kiểm thử để đảm bảo callback nền lên UI hoạt động an toàn.

### Giai đoạn 3 – Di chuyển từng module UI
- [x] Tạo `OverviewTab` với tín hiệu khởi động/hủy phiên, quản lý autorun và nhật ký phiên phân tích.
- [x] Port tab biểu đồ sang `ChartTabWidget`, phát tín hiệu cập nhật cấu hình/refresh/snapshot phục vụ kết nối HistoryManager.
- [x] Dựng `NewsTabWidget` hiển thị bảng tin, trạng thái tải và checkbox bỏ qua chặn tin để chuẩn bị nối với `NewsController`.
- [x] Triển khai `PromptTabWidget` hỗ trợ load/save định dạng JSON, reformat prompt và đồng bộ trạng thái auto-load.
- [x] Xây dựng `HistoryTabWidget` để quét báo cáo/ctx và hiển thị preview thông qua cầu nối tín hiệu PyQt6.
- [x] Chuyển các dialog và thao tác hộp thoại (shutdown, xem JSON, chọn tệp) sang PyQt6 và gắn kết với `TradingMainWindow`.
- [x] Port tab Báo cáo (`ReportTabWidget`) cho phép làm mới, mở, xoá báo cáo Markdown kèm preview nhanh.
- [x] Hoàn thiện tab Tuỳ chọn (`OptionsTabWidget`) gom cấu hình chi tiết và phát tín hiệu khi người dùng chỉnh sửa.
- [x] Cho phép PyQt6 chụp snapshot state và sinh payload workspace đầy đủ (bao gồm nội dung prompt, API key, persistence) thông qua `TradingMainWindow.snapshot_ui_state()` và `build_workspace_payload()`.
- [x] Bổ sung API tương thích Tkinter để cập nhật trạng thái, tiến trình, nhật ký và hiển thị dialog ngay trong PyQt6, sẵn sàng cho bước nối controller.

> ✅ Đã hoàn thành toàn bộ Giai đoạn 3 – mọi tab, dialog và tiện ích Tkinter đã có bản PyQt6 tương ứng, sẵn sàng bước sang Giai đoạn 4.

### Giai đoạn 4 – Đồng bộ controller & thread
- [x] Tạo `ControllerCoordinator` gom controller/service dựa trên `UiConfigState` và `ThreadingManager`.
- [x] Kết nối `TradingMainWindow` với `ChartController`/`NewsController` thông qua `UiQueueBridge`.
- [x] Chuẩn hoá các thao tác PromptTab bằng `IOController.run` và callback future.
- [x] Đồng bộ lại cấu hình Options cho services và kích hoạt autorun tin tức sau mỗi thay đổi.
- [x] Bổ sung kiểm thử PyQt6 xác nhận bridge controller (prompt/news/chart) hoạt động chính xác.
- [x] Hoàn thiện adapter AnalysisController cùng cơ chế autorun PyQt6 (QTimer, cập nhật trạng thái session).
