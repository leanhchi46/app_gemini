# Tổng quan logic kiểm tra điều kiện No-Trade

Tài liệu này mô tả cách hệ thống đánh giá các điều kiện "Không vào lệnh" (No-Trade) dựa trên mã nguồn tại `APP/core/trading/conditions.py`.

## 1. Kích hoạt tính năng
- Kiểm tra chỉ diễn ra khi cờ `RunConfig.no_trade.enabled` được bật. Nếu tắt, hàm `check_no_trade_conditions` trả về `NoTradeCheckResult()` rỗng và bỏ qua mọi điều kiện.
- Khi được kích hoạt, hệ thống ghi log mức `DEBUG` để đánh dấu thời điểm bắt đầu đánh giá.

## 2. Kiến trúc kiểm tra
Hàm `check_no_trade_conditions` áp dụng Strategy Pattern: mỗi điều kiện riêng biệt được triển khai dưới dạng lớp con của `AbstractCondition` và khai báo trong một danh sách cố định. Vòng lặp chính lần lượt gọi `condition.check(...)` cho từng điều kiện và thu thập các `NoTradeViolation`.

Các điều kiện hiện có bao gồm:
1. `NewsCondition`
2. `SpreadCondition`
3. `ATRCondition`
4. `SessionCondition`
5. `KeyLevelCondition`
6. `UpcomingNewsWarningCondition`

Mỗi điều kiện trả về `NoTradeViolation` (hoặc `None`). `NoTradeViolation` chứa `condition_id`, thông báo hiển thị, mức độ nghiêm trọng (`severity`) và cờ `blocking` cho biết có nên dừng giao dịch ngay hay chỉ cảnh báo. `check_no_trade_conditions` gom các vi phạm vào `NoTradeCheckResult`, phân tách `blocking` và `warnings` để các tầng trên quyết định hành động. Hàm cũng log mức `INFO` với bản tóm tắt nếu xuất hiện vi phạm hoặc cảnh báo. Kể từ bản cập nhật này, `NoTradeCheckResult` còn mang theo cấu trúc `metrics` chứa các chỉ số telemetries (spread, ATR, key level) để UI và các tác vụ hậu kiểm có thể tái sử dụng mà không phải tính lại.

## 3. Chi tiết từng điều kiện
### 3.1 NewsCondition
- Yêu cầu `NewsService` được truyền qua `kwargs`. Nếu thiếu, đây được xem là lỗi cấu hình và điều kiện trả về thông báo lỗi.
- Khi `RunConfig.news.block_enabled` bật, điều kiện gọi `news_service.is_in_news_blackout` với symbol hiện tại. Nếu hàm trả về `True`, điều kiện trả về lý do chặn giao dịch vì tin tức quan trọng.

### 3.2 SpreadCondition
- Đòi hỏi dữ liệu MT5 an toàn (`safe_mt5_data`). Nếu không có dữ liệu, điều kiện trả về lỗi "Không có dữ liệu MT5".
- Khi giá trị `spread_max_pips` > 0, điều kiện tận dụng `NoTradeMetrics` để lấy spread hiện tại, median/p90 của 5 phút và 30 phút gần nhất, đồng thời tính phần trăm spread so với ATR M5.
- Nếu spread hiện tại vượt ngưỡng cấu hình, điều kiện trả về thông báo spread quá cao, đính kèm toàn bộ telemetry nhằm phục vụ dashboard cũng như nhật ký.
- Nếu spread hiện tại vẫn an toàn nhưng ngưỡng cấu hình thấp hơn p90 5 phút (dễ dẫn đến chặn lệnh giả), điều kiện tạo `warning` gợi ý nâng ngưỡng với biên an toàn 5%.

### 3.3 ATRCondition
- Cần dữ liệu MT5 và ngưỡng `min_atr_m5_pips` > 0.
- Sử dụng `NoTradeMetrics` để chuyển đổi ATR M5 (đơn vị giá) sang pips, đồng thời so sánh với ADR20 nhằm đánh giá độ phù hợp của ngưỡng cấu hình.
- Nếu ATR M5 nhỏ hơn ngưỡng tối thiểu, điều kiện trả về lý do biến động thấp kèm tỷ lệ ATR/ADR20.
- Nếu ngưỡng cấu hình vượt quá 35% ADR20 (khả năng cao ngưỡng bị đặt quá chặt), điều kiện sinh `warning` gợi ý giá trị hợp lý hơn.
- Thiếu dữ liệu ATR dẫn tới lỗi cấu hình.

### 3.4 SessionCondition
- Nếu không có dữ liệu MT5, điều kiện bỏ qua (trả về `None`).
- Ánh xạ trạng thái killzone hiện tại (`safe_mt5_data['killzone_active']`) sang khóa phiên giao dịch (`asia`, `london`, `ny`).
- Đối với mỗi phiên, kiểm tra cờ cho phép tương ứng (`allow_session_*`).
  - Nếu đang ở trong một killzone xác định mà phiên đó bị tắt, điều kiện trả về thông báo không được phép giao dịch trong phiên đó.
  - Nếu không xác định được phiên hiện tại (ngoài killzone) và có bất kỳ phiên nào bị tắt, điều kiện trả về lý do ngoài phiên được phép.

### 3.5 KeyLevelCondition
- Cần dữ liệu MT5, đặc biệt là danh sách `key_levels_nearby`.
- `NoTradeMetrics` xác định key level gần nhất cùng khoảng cách pips. Với `min_dist_keylvl_pips` > 0, nếu khoảng cách nhỏ hơn ngưỡng thì điều kiện trả về thông báo giá quá gần mức quan trọng.
- Nếu hoàn toàn không có dữ liệu key level (ví dụ fail khi tính toán), điều kiện sinh cảnh báo để trader nhận biết rằng hệ thống không thể xác nhận khoảng cách an toàn.

### 3.6 UpcomingNewsWarningCondition
- Sử dụng `news_service.get_upcoming_events` để quét các sự kiện kinh tế sắp diễn ra.
- Khi tìm thấy sự kiện trong khoảng `max(block_before + block_after, 15 phút)` nhưng chưa bước vào vùng blackout, điều kiện trả về một cảnh báo (`blocking=False`, `severity="warning"`).
- Giúp trader chuẩn bị trước, đồng thời UI vẫn hiển thị trạng thái giao dịch đang cho phép.

## 4. Giá trị trả về
- Hàm trả về `NoTradeCheckResult` chứa hai danh sách: `blocking` (các vi phạm cần dừng giao dịch) và `warnings` (cảnh báo bổ sung), cùng trường `metrics` phục vụ UI.
- `NoTradeCheckResult.to_messages()` chuyển đổi thành chuỗi kèm icon (`⛔/⚠️/ℹ️`) để hiển thị thống nhất trên UI.
- Nếu không có vi phạm hay cảnh báo, `has_blockers()` trả về `False` và UI hiển thị thông điệp “✅ Không có trở ngại.”
- Trường `metrics` được UI tái sử dụng để hiển thị bảng tóm tắt các chỉ số bảo vệ ngay cả khi không có vi phạm.

## 5. Bộ chỉ số No-Trade (`NoTradeMetrics`)
- Được xây dựng bởi `collect_no_trade_metrics` tại `APP/core/trading/no_trade_metrics.py` từ `SafeData` và `RunConfig`.
- Bao gồm ba nhóm:
  - **SpreadMetrics**: spread hiện tại, median/p90 5 phút & 30 phút, phần trăm so với ATR M5, ngưỡng cấu hình hiện tại.
  - **AtrMetrics**: ATR M5 theo pips, ADR20 quy đổi pips, tỷ lệ ATR/ADR20 và ngưỡng tối thiểu đang áp dụng.
  - **KeyLevelMetrics**: danh sách mức quan trọng gần nhất, khoảng cách pips tới mức gần nhất và ngưỡng tối thiểu.
- Các điều kiện và UI dùng chung cấu trúc này để đảm bảo một nguồn dữ liệu thống nhất, tránh việc tính toán lại hoặc lệch logic giữa backend/UI.

## 6. Tương tác với phần UI
- Tab Options -> Trading trong `APP/ui/utils/ui_builder.py` cung cấp các trường cấu hình tương ứng: bật/tắt kiểm tra, giới hạn spread, ATR tối thiểu, khoảng cách key level và bộ check phiên giao dịch.
- Ba spinbox chính trong card "Điều kiện không vào lệnh" lần lượt gắn với `nt_spread_max_pips_var`, `nt_min_atr_m5_pips_var` và `trade_min_dist_keylvl_pips_var`. Khi người dùng thay đổi các giá trị này, `AppUI.build_config()` ghi lại vào `RunConfig.no_trade` và được truyền thẳng cho `SpreadCondition`, `ATRCondition` và `KeyLevelCondition` trong vòng lặp đánh giá.
- Các trường này cập nhật các biến trong `AppUI`, từ đó ghi vào `RunConfig` được sử dụng bởi logic kiểm tra.
- Panel “Điều kiện giao dịch” tại `APP/ui/components/chart_tab.py` hiển thị trạng thái tổng hợp (⛔/⚠️/✅) dựa trên `NoTradeCheckResult`, render chi tiết blocker/warning và tái sử dụng `NoTradeMetrics` cho phần “Chỉ số bảo vệ” (spread/ATR/key level) giúp trader đánh giá nhanh chất lượng thị trường. Các vùng văn bản cho “Lý do No-Trade”, “Chỉ số bảo vệ” và “Sự kiện sắp tới” đã chuyển sang dạng `ScrolledText` chỉ đọc với thanh cuộn dọc, vì vậy có thể kéo/scroll để xem toàn bộ thông tin thay vì bị cắt khi nội dung dài.
- Kết quả mới nhất cũng được `AnalysisWorker` serial hóa về dạng dict thông qua `NoTradeCheckResult.to_dict(include_messages=True)` và lưu vào `SafeData.raw['evaluations']['no_trade']` cũng như thuộc tính `AppUI.last_no_trade_result`. Nhờ đó các tab khác (report, phân tích) có thể truy cập lại kết quả kiểm tra gần nhất mà không phải gọi lại backend, bảo đảm trạng thái nhất quán trên toàn ứng dụng.
