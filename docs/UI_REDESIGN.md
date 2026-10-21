# Thiết kế lại toàn bộ giao diện

Ngày 21/10/2026 (giờ Việt Nam).

## Thay đổi

- Trang đăng nhập chia hai phần trên desktop: phần giới thiệu nền navy và biểu mẫu đăng nhập trên nền trắng; điện thoại ưu tiên biểu mẫu. Có nút hiện/ẩn mật khẩu.
- Hệ thống màu mới: sidebar navy, nội dung sáng, xanh dương cho hành động chính, màu trạng thái riêng cho thành công/chờ/lỗi. Typography, khoảng cách, border, focus và trạng thái disabled thống nhất.
- Sidebar có icon SVG nội bộ, mục đang chọn và số bài chờ. Thanh trên có breadcrumb, làm mới và avatar.
- Dashboard gồm bốn số liệu từ API, hàng đợi, hoạt động, phân bố trạng thái và lối tắt tới các thao tác. Không tạo số tăng trưởng, lượt xem hay biểu đồ giả. Phân bố dùng tối đa 500 job mà API trả về; thống kê tổng dùng endpoint summary.
- Thiết kế lại toàn bộ form và card cho tài khoản/video/sản phẩm/caption/lịch/bài đăng/đối soát/cài đặt; empty state có hướng dẫn theo từng trang.
- Upload hỗ trợ chọn file và kéo thả; tên file được hiển thị trước khi gửi.
- Điện thoại dùng menu drawer, có backdrop, Escape, focus trap, inert và trả focus về nút mở menu. Tôn trọng reduced-motion; không dùng font, icon hay thư viện giao diện từ CDN.
- Không thay đổi schema DB, OAuth, publisher, quyền người dùng hoặc quy trình đối soát trong đợt giao diện này.

## Kiểm thử

- 49 test API/service hiện có vẫn đạt.
- Chromium đi qua login → tạo profile/product/caption → chọn và kéo thả video → gán → tạo/duyệt bài → đối soát hai nhánh và lịch sử → pause → logout.
- Kiểm tra cả 9 trang ở 1440, 390 và 320px: không tràn ngang, không lỗi JavaScript.
- Kiểm tra menu mobile bằng bàn phím, hiện/ẩn mật khẩu và tên file sau drop.
- Docker build và smoke test: container non-root, khởi tạo SQLite, health, dashboard.

Ảnh dùng dữ liệu của bài test độc lập, không phải tài khoản hay bài đăng thật:

- [Dashboard desktop](evidence/desktop.png)
- [Dashboard mobile](evidence/mobile.png)
- [Đăng nhập desktop](evidence/login-desktop.png)
- [Đăng nhập mobile](evidence/login-mobile.png)
- [Tài khoản trên điện thoại](evidence/profiles-mobile.png)
- [Kho video desktop](evidence/media-desktop.png)
- [Đối soát trên điện thoại](evidence/reconciliation.png)

## Cập nhật bản đang dùng

Giữ nguyên `.env` và `data`, cập nhật source từ GitHub, chạy lại `python scripts/run.py`, sau đó Ctrl+F5. Asset có version trong HTML để tránh dùng lại CSS/JS cũ. Không chạy lại setup hoặc đổi ENCRYPTION_KEY cho việc cập nhật CSS.
