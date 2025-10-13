# Phân tích logic tin tức

## 1. Kiến trúc tổng thể
- `NewsService` chịu trách nhiệm thu thập, lọc và cache dữ liệu lịch kinh tế; đồng thời cung cấp API phân tích tin tức cho các phần còn lại của ứng dụng.【F:APP/services/news_service.py†L42-L200】
- `NewsController` đóng vai trò facade, điều phối các tác vụ nền chạy trong `ThreadingManager` và đẩy kết quả cập nhật tin tức vào hàng đợi UI theo từng mức ưu tiên (autorun hay thao tác người dùng).【F:APP/ui/controllers/news_controller.py†L16-L121】
- Lớp `AppUI` khởi tạo cả hai thành phần trên, đăng ký callback cập nhật giao diện và đảm bảo vòng đời của polling tin tức khi ứng dụng mở hoặc tắt.【F:APP/ui/app_ui.py†L183-L371】
- Thành phần `NewsTab` trên giao diện hiển thị danh sách sự kiện, phân loại màu sắc theo mức độ ảnh hưởng và cung cấp thông điệp hướng dẫn khi không có dữ liệu.【F:APP/ui/components/news_tab.py†L18-L113】

## 2. Thu thập dữ liệu từ provider
- `NewsService.update_config` nạp cấu hình `RunConfig`, khởi tạo lại `FMPService` và `TEService` nếu được bật, đồng thời đặt timezone phục vụ chuyển đổi giờ hiển thị.【F:APP/services/news_service.py†L67-L95】
- `FMPService` sử dụng `investpy` để lấy lịch kinh tế trong 7 ngày tới và trả về danh sách sự kiện thô.【F:APP/services/fmp_service.py†L31-L70】
- `TEService` đăng nhập vào Trading Economics, hỗ trợ bỏ qua xác minh SSL khi cấu hình yêu cầu và trả về danh sách sự kiện lịch kinh tế; lỗi xác thực được ghi log và trả về danh sách rỗng thay vì chặn hệ thống.【F:APP/services/te_service.py†L14-L95】
- Khi refresh, `NewsService` tạo một công việc cho từng provider đang bật thông qua `ThreadingManager`, truyền metadata (component, provider, priority) để hỗ trợ telemetry và kiểm soát hủy tác vụ.【F:APP/services/news_service.py†L240-L337】
- Kết quả từ mỗi provider được chuyển đổi sang định dạng chung, loại bỏ bản ghi trùng thông qua `_dedup_ids` và chuẩn hóa thời gian sang `datetime` UTC.【F:APP/services/news_service.py†L339-L455】

## 3. Lọc và cache tin tức quan trọng
- Sau khi tổng hợp dữ liệu, `_filter_high_impact` giữ lại các sự kiện có impact cao, tiêu đề khớp `priority_keywords` từ cấu hình và cả những bản tin có `surprise_score` vượt ngưỡng cài đặt để đảm bảo không bỏ lỡ các biến động bất ngờ.【F:APP/services/news_service.py†L95-L111】【F:APP/services/news_service.py†L457-L480】
- Các bộ chuyển đổi dữ liệu giữ lại trường `actual/forecast/previous/unit`, đồng thời `_enrich_event_metrics` tính toán `surprise_score` và hướng biến động giúp UI hiển thị rõ mức độ bất ngờ của từng sự kiện.【F:APP/services/news_service.py†L387-L455】【F:APP/services/news_service.py†L580-L610】
- Cache tin tức được bảo vệ bằng khóa và TTL. Nếu tuổi cache nhỏ hơn TTL, dịch vụ trả về dữ liệu cache và bỏ qua việc gọi provider nhằm tiết kiệm quota và giảm tải.【F:APP/services/news_service.py†L220-L278】
- Khi cache được làm mới từ mạng, callback đã đăng ký được gọi để đẩy dữ liệu mới lên giao diện; đồng thời thời điểm refresh cuối cùng và độ trễ được lưu lại để phục vụ báo cáo và phân tích sau này.【F:APP/services/news_service.py†L251-L277】

### 3.1 Kiểm tra nhanh danh sách đã lọc trên UI
- Khi `NewsTab.update_news_list` nhận dữ liệu đã cache, mỗi dòng sẽ được gán màu sắc theo trường `impact` (High/Medium/Low) và kèm các cột Actual/Forecast/Previous/Surprise đã định dạng để người dùng so sánh số liệu nhanh chóng.【F:APP/ui/components/news_tab.py†L64-L133】
- Nếu vẫn thấy các sự kiện mức Medium/Low không chứa từ khóa ưu tiên (ví dụ: "MBA Mortgage Applications"), cần kiểm tra lại dữ liệu provider vì các bản ghi như vậy sẽ bị loại bỏ ở bước `_filter_high_impact`; hiện tượng này thường chỉ xảy ra khi provider đánh dấu sai trường `impact` hoặc tiêu đề trùng khớp một từ khóa quan trọng.【F:APP/services/news_service.py†L457-L480】

## 4. Phân tích cửa sổ “cấm giao dịch”
- `NewsService.is_in_news_blackout` kiểm tra cấu hình chặn giao dịch, tính toán khoảng thời gian trước/sau tin theo từng sự kiện và trả về lý do nếu hiện tại nằm trong vùng cấm.【F:APP/services/news_service.py†L118-L145】
- `get_upcoming_events` ánh xạ symbol sang danh sách tiền tệ, từ đó lấy các quốc gia liên quan để lọc sự kiện phù hợp; mỗi sự kiện được bổ sung thời gian địa phương và chuỗi “time remaining” để hiển thị cho người dùng.【F:APP/services/news_service.py†L147-L178】【F:APP/services/news_service.py†L398-L421】
- `get_news_analysis` kết hợp hai API trên để trả về kết quả tổng hợp gồm trạng thái cấm giao dịch, lý do, ba sự kiện sắp tới, thời gian refresh cuối và độ trễ lấy dữ liệu.【F:APP/services/news_service.py†L182-L203】

## 5. Điều phối polling và ưu tiên
- `NewsController.start_polling` tạo `CancelToken`, đăng ký callback và kích hoạt refresh autorun đầu tiên. Các lần autorun tiếp theo sẽ bị chặn nếu hàng đợi UI đang vượt ngưỡng để tránh quá tải giao diện.【F:APP/ui/controllers/news_controller.py†L37-L58】
- Khi người dùng yêu cầu làm mới, controller hủy toàn bộ tác vụ `news.polling` đang chạy, tái tạo token và gửi request với mức ưu tiên “user” để đảm bảo kết quả mới nhất được đưa lên trước.【F:APP/ui/controllers/news_controller.py†L59-L109】
- Callback hoàn tất (`_on_future_done`) đưa payload vào hàng đợi UI nhằm cập nhật giao diện theo cơ chế thread-safe; đồng thời giữ lại payload cuối để phục vụ debug.【F:APP/ui/controllers/news_controller.py†L109-L127】

## 6. Tích hợp giao diện và cấu hình người dùng
- `AppUI` thiết lập đầy đủ biến Tkinter cho news pipeline (TTL, từ khóa ưu tiên, ngưỡng surprise, backoff lỗi, alias quốc gia) và đồng bộ lưu/khôi phục qua workspace để tránh sai lệch cấu hình giữa UI và dịch vụ.【F:APP/ui/app_ui.py†L520-L585】【F:APP/ui/app_ui.py†L662-L1037】
- `ui_builder` cung cấp giao diện nhập các tham số mới (entry từ khóa, spinbox ngưỡng surprise/backoff, vùng JSON alias), còn `NewsTab` hiển thị danh sách sự kiện với các cột số liệu và surprise-score đã định dạng.【F:APP/ui/utils/ui_builder.py†L523-L742】【F:APP/ui/components/news_tab.py†L43-L133】

## 7. Vòng đời và shutdown
- Khi người dùng đóng ứng dụng, `AppUI.shutdown` hủy polling tin tức, chờ nhóm tác vụ `news.polling` kết thúc rồi mới tắt `ThreadingManager`, đảm bảo không còn tác vụ nền nào treo hoặc bị bỏ dở.【F:APP/ui/app_ui.py†L313-L372】

## 8. Bao phủ kiểm thử
- `tests/services/test_news_service.py` xác nhận dịch vụ gắn metadata chính xác khi submit, tôn trọng cache TTL, tính `surprise_score` và bỏ qua provider đang backoff đúng như mong đợi.【F:tests/services/test_news_service.py†L20-L150】
- `tests/controllers/test_news_controller.py` kiểm tra các tình huống start, autorun bị chặn do backlog, refresh theo yêu cầu người dùng và hành vi hủy nhóm tác vụ, giúp đảm bảo logic ưu tiên vận hành đúng.【F:tests/controllers/test_news_controller.py†L22-L106】

Nhờ kiến trúc này, luồng tin tức của ứng dụng đáp ứng các yêu cầu: thu thập đa nguồn, lọc sự kiện quan trọng, duy trì cache hiệu quả, hỗ trợ ưu tiên người dùng và cung cấp thông tin rõ ràng trên UI, đồng thời đảm bảo an toàn đa luồng và khả năng kiểm thử.

## 9. Tiến độ cải tiến logic tin tức
- [x] **Tăng độ giàu thông tin của sự kiện:** `_transform_fmp_data` và `_transform_te_data` giữ lại `actual/forecast/previous`, `_enrich_event_metrics` tính `surprise_score` và `surprise_direction`, giúp UI phản ánh độ bất ngờ của tin.【F:APP/services/news_service.py†L347-L379】【F:APP/services/news_service.py†L436-L481】
- [x] **Biến cấu hình hóa danh sách từ khóa ưu tiên:** `NewsConfig` thêm các trường `priority_keywords`, `surprise_score_threshold`, `provider_error_*`; `AppUI` cùng `ui_builder` cho phép nhập/sửa trực tiếp, và `_filter_high_impact` sử dụng các giá trị này khi lọc dữ liệu.【F:APP/configs/app_config.py†L129-L140】【F:APP/ui/app_ui.py†L662-L1037】【F:APP/ui/utils/ui_builder.py†L523-L742】【F:APP/services/news_service.py†L457-L480】
- [x] **Theo dõi sức khỏe provider và áp dụng backoff:** `NewsService` lưu `ProviderHealthState`, ghi nhận lỗi liên tiếp, bỏ qua provider trong thời gian backoff và reset sau lần gọi thành công để tránh spam endpoint gặp sự cố.【F:APP/services/news_service.py†L40-L198】【F:APP/services/news_service.py†L308-L365】【F:APP/services/news_service.py†L482-L523】
- [x] **Mở rộng ánh xạ symbol → quốc gia:** cấu hình hỗ trợ `currency_country_overrides` và `symbol_country_overrides`, còn `_get_countries_for_symbol` sử dụng mapping mới để lọc sự kiện theo alias tùy biến cho từng workspace.【F:APP/services/news_service.py†L19-L80】【F:APP/services/news_service.py†L96-L117】【F:APP/services/news_service.py†L490-L558】
