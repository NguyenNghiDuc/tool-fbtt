# Báo cáo triển khai theo từng mục

Ngày 21/10/2026 (giờ Việt Nam). Phân biệt rõ: **đã triển khai + test nội bộ**, **mô phỏng dịch vụ bên ngoài**, **chưa làm**. Chưa thể đánh dấu toàn bộ tài liệu A–Z hoàn thành.

| Mục | Đã triển khai | Test riêng | Còn thiếu / chưa xác minh |
|---|---|---|---|
| 1. Tài khoản | CRUD, pause/status, nhóm qua niche, ghi chú/màu, 3 vai trò, OAuth state/PKCE, token mã hóa, refresh TikTok và cảnh báo cấp quyền lại | 6 test profile + test 2FA | OAuth thật/quyền app; không thể tự gia hạn mọi loại Facebook Page token |
| 2. Kho video | Upload, tự quét inbox, gán profile, dùng/chưa dùng, SHA-256 chống trùng, ffprobe định dạng/thời lượng/dung lượng/tỉ lệ, thumbnail FFmpeg | 3 test dùng video thật | Gán hàng loạt theo nhóm; tải Drive/URL; cắt/nén, intro/outro/logo/phụ đề; kiểm tra đầy đủ giới hạn thay đổi của từng API |
| 3. Sản phẩm | CRUD tên/giá/ảnh/2 link/hoa hồng/ngách, nhiều sản phẩm/video, CSV nhập nguyên khối, tracking profile/post và click, chặn khi đánh dấu hết hàng | 2 test commerce + tracking/order | Excel; tự phát hiện link chết và tồn kho; tự gắn tracking vào caption |
| 4. Caption | 4 biến, xoay vòng mẫu lưu bền, chọn hashtag, preview và disclosure | 1 test caption | AI Claude; kho hashtag độc lập theo ngách; xoay emoji riêng; comment Facebook đầu tiên |
| 5. Lịch | Khung giờ, thứ trong tuần, timezone, jitter, FIFO/random, planner chống trùng, giữ video, duyệt/hủy/đổi giờ, giới hạn, dừng khẩn cấp, cảnh báo hết kho | 3 test scheduling + daily cap/claim | Lịch tháng/tuần kéo thả; giờ vàng từ tương tác; cảnh báo trước khi kho sắp cạn |
| 6. Publisher | Adapter Facebook video và TikTok riêng tư; worker async tối đa 4, khóa theo profile, lỗi tách biệt, backoff tối đa 3, polling TikTok, manual Shop link, trạng thái uncertain, UI đối soát có audit, processing deadline | 7 test publisher + 11 test đối soát | Tất cả HTTP test dùng mock; chưa gửi thật; chưa Reels chuyên biệt; TikTok audit UX/disclosure và upload chia chunk lớn |
| 7. Thống kê | Nhật ký, tổng hợp trạng thái/profile, ranking doanh thu/hoa hồng sản phẩm từ đơn nhập tay, CSV tránh formula injection, click tracking, chống nhập trùng đơn | 2 test operations | API views/likes/comments/shares; phân tích ngách/giờ; báo cáo nhập nền tảng; Excel |
| 8. Thông báo | Outbox bền trong SQLite, trigger lỗi/token/hết kho, Telegram hoặc SMTP STARTTLS, retry giới hạn, tổng kết cuối ngày | 1 test outbox mô phỏng Telegram | Telegram/email thật; test SMTP thật; phát hiện giảm view/hạn chế; cảnh báo caption sắp cạn; tổng kết bù nếu app tắt lúc 23h |
| 9. Dashboard | 9 trang tiếng Việt, responsive, profile/media/products/captions/schedules/jobs/log/settings, preview/approve, đăng nhập, phân quyền và TOTP | 2 test dashboard + 1 luồng Chromium desktop/mobile | Chưa có calendar kéo thả; chưa có UI toàn bộ tracking/orders; chưa có mã khôi phục 2FA |
| 10. Vận hành | SQLite WAL/FK/unique indexes, mã hóa, session/cookie/CSRF, Docker non-root, compose restart/log rotation, sao lưu snapshot+video thủ công/tự động | 1 test backup + Docker smoke | PostgreSQL/migration phân tán, retention/offsite, restore DR test, giám sát ngoài tiến trình và quy trình cập nhật API |
| 11. Tuân thủ | Rate/daily cap, nội dung trùng, cảnh báo claim theo từ khóa, bắt xác nhận cảnh báo, nhắc quyền ủy quyền; không có like/follow/IP/fingerprint automation | 2 test compliance | Bộ từ khóa cần mở rộng; không thay thế kiểm duyệt hoặc bảo đảm được nền tảng duyệt |

## Bằng chứng kiểm thử

- 49 test API/service độc lập (không đếm lặp test kế thừa). Mỗi nhóm có lệnh `python -m unittest tests.test_<nhóm> -v`.
- Chromium: login → profile → product → caption → upload video thật → gán → tạo bài → duyệt → đối soát cả hai nhánh và lịch sử → pause → mobile 390px không tràn ngang → logout; không lỗi JavaScript.
- Ảnh kiểm thử: [desktop](evidence/desktop.png) và [mobile](evidence/mobile.png) (dữ liệu giả).
- Docker: build thật với proxy CA; smoke test kiểm tra UID không phải root, SQLite khởi tạo, health và giao diện. Xem kết quả cuối trong `docs/TEST_RESULTS.txt`.
- Các nền tảng, OAuth, Telegram dùng phản hồi giả lập trong test; không được xem là kiểm thử end-to-end với dịch vụ thật.

## Sửa theo đánh giá mã nguồn

Đã xử lý các điểm **1, 4, 5** trong đánh giá: đối soát uncertain/deadline processing; IP thật từ proxy được cấu hình tin cậy; chẩn đoán maintenance an toàn và tách lỗi từng bước. Có 19 test hồi quy mới và test UI hai nhánh đối soát. Chi tiết ở [REVIEW_FIXES.md](REVIEW_FIXES.md).

Các điểm còn lại chưa được đánh dấu hoàn thành: TikTok audit/disclosure, Facebook Reels/comment đầu tiên, streaming/chunk upload, tái cấu trúc records, đổi mật khẩu/mã khôi phục 2FA. Lịch hiện nằm trong bảng `schedules` riêng với unique index theo profile, không nằm trong `records`.

## Việc tiếp theo theo tài liệu gốc

1. Hoàn thiện kiểm thử OAuth và publisher trên app đã cấp quyền, TikTok audit/consent/disclosure trước production.
2. Tiếp tục các tính năng mở rộng trong bảng: xử lý video, Excel/AI, lịch kéo thả, metrics API, link health, Drive, cảnh báo nâng cao.
3. Chạy kiểm thử khôi phục và triển khai HTTPS với credentials thực do chủ app cấu hình.

Các mục mở rộng không được đánh dấu đã xong chỉ vì MVP cùng nhóm đã có. Cấu hình thật còn thiếu không ngăn các test nội bộ, nhưng ngăn kết luận hệ thống đã sẵn sàng đăng production.
