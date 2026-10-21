# Sửa sau đánh giá ngày 21/10/2026

Phạm vi đợt này: các điểm 1, 4 và 5. Tất cả kết quả dịch vụ ngoài vẫn là mô phỏng; chưa gửi bài thật lên Meta/TikTok.

## 1. Giải phóng profile qua đối soát có xác nhận

Trong Hàng đợi, admin/publisher có biểu mẫu chọn **đã đăng / chưa đăng**, phải xác nhận đã kiểm tra trực tiếp trên nền tảng. Đã đăng cần ID bài/video thực đã xác minh; TikTok chuyển chờ gắn Shop link. Chưa đăng đưa bài về pending, giữ video để scheduler không lấy lại và bắt duyệt mới trước khi gửi. Không có hành động retry ngầm. Hai người đối soát đồng thời chỉ một quyết định được commit.

Lịch sử có user, thời gian, kết quả, lỗi và remote reference cũ, ID mới, số lần đã thử và thời điểm gửi trước đó. Cập nhật job/video và audit chung giao dịch SQLite. Poll trả muộn không ghi đè một quyết định đã thay đổi trạng thái job.

`processing_since` được bổ sung không xóa dữ liệu cũ. Job processing cũ lấy mốc started/created; job mới lấy mốc upload xong. `PROCESSING_TIMEOUT_SECONDS=1800` mặc định. Hết deadline → uncertain + cảnh báo; không coi đó là thất bại chắc chắn và không tự đăng lại. Kiểm tra deadline chạy cả khi hệ thống pause/publishing false, trong vòng tick.

11 test mới kiểm tra migration DB cũ và hai kết quả, quyền truy cập, xác nhận/ID bắt buộc, deadline khi polling lỗi/publisher tắt, phản hồi hỏng, poll muộn, quyết định đồng thời và video kế tiếp được đăng sau giải phóng profile. Chromium chạy cả hai nhánh, lịch sử và biểu mẫu ở màn hình 390px.

## 4. IP thật sau proxy

`TRUSTED_PROXY_CIDRS` mặc định rỗng; chỉ tin header khi TCP peer nằm trong danh sách tin cậy. Đọc XFF từ phải sang trái, dừng ở địa chỉ không tin cậy đầu tiên. Bỏ header lỗi/quá dài/trùng. Không cho cấu hình wildcard hoặc CIDR /0. Chuẩn hóa IPv4/IPv6. Docker/local launcher tắt xử lý proxy header trước của Uvicorn; README có cấu hình Nginx và hướng dẫn xác định proxy thực trong Docker.

4 test mới: hai client sau cùng proxy có bộ đếm riêng; peer không tin không đổi IP để vượt rate limit; spoofed prefix không vượt giới hạn; IPv6/header lỗi/duplicate và cấu hình không an toàn. Giới hạn theo IP vẫn có thể chia sẻ cho nhiều người chung NAT và không ngăn tấn công phân tán.

## 5. Chẩn đoán maintenance

Mỗi bước độc lập, ghi mã bước và loại exception đã được cho phép vào event/console. Không ghi message exception, URL, request, token hoặc traceback locals. Lỗi lưu event được ghi loại lỗi ra console và không kết thúc vòng lặp. Không nuốt cancellation lúc shutdown. Bước refresh giữ chu kỳ 5 phút, các bước khác 15 giây.

4 test mới: phân loại/redact lỗi và tiếp tục bước sau; nhịp refresh/cleanup; cancellation; DB ghi sự kiện bị lỗi vẫn tiếp tục.

## Còn lại

- Chưa thử Fanpage thật: cần Meta app, callback HTTPS, Page được ủy quyền, quyền API và cấu hình credentials ở môi trường chạy.
- Chưa triển khai Reels/comment đầu tiên, public TikTok/audit UX/disclosure, streaming chunk lớn, migration records sang bảng chuyên biệt, đổi mật khẩu và mã khôi phục 2FA.
- `records` hiện chứa sản phẩm/caption/cursor; lịch đã có bảng `schedules` riêng. Chưa có migration PostgreSQL.
