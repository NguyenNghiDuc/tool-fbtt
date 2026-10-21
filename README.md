# FBTT Studio

Ứng dụng quản lý video Facebook Fanpage/TikTok bằng FastAPI, SQLite, FFmpeg và giao diện web tiếng Việt. Đây là bản triển khai MVP có kiểm thử nội bộ; kết nối nền tảng thật cần cấu hình ứng dụng và kiểm duyệt API. Chi tiết từng mục và phần còn thiếu ở [báo cáo](docs/PROGRESS.md).

## Giao diện Studio

Giao diện được thiết kế lại với sidebar tối, vùng nội dung sáng, màu xanh dương chủ đạo, icon SVG nội bộ và bố cục riêng cho điện thoại. Dashboard hiển thị thống kê thực, bài sắp đăng, dòng hoạt động và phân bố hàng đợi. Có vùng kéo thả video, hiện/ẩn mật khẩu, menu drawer hỗ trợ bàn phím và trạng thái focus/reduced-motion.

[Dashboard](docs/evidence/desktop.png) · [Đăng nhập](docs/evidence/login-desktop.png) · [Giao diện điện thoại](docs/evidence/mobile.png)

Khi cập nhật bản đã tải về, giữ nguyên `.env` và `data`, thay mã nguồn bằng bản mới, khởi động lại và nhấn **Ctrl+F5** trong trình duyệt. Không cần tạo lại tài khoản hoặc khóa mã hóa cho thay đổi giao diện này.

## Chạy trên máy

Yêu cầu Python 3.12+, FFmpeg/ffprobe có trong PATH.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/setup.py
python scripts/run.py
```

Mở http://localhost:8000. Tên đăng nhập mặc định `admin`; mật khẩu ngẫu nhiên nằm trong `.env`, không được in ra log. `setup.py` chỉ tạo mới, không ghi đè cấu hình. Giữ `ENCRYPTION_KEY` cố định: đổi/mất khóa sẽ không giải mã được token và 2FA đã lưu. `ADMIN_PASSWORD` chỉ dùng để tạo người dùng đầu tiên, không đổi mật khẩu người dùng đã có.

## Docker / VPS

```bash
python scripts/setup.py
docker compose up -d --build
```

Lệnh setup cần thư viện cryptography (`pip install -r requirements.txt` hoặc tạo `.env` thủ công từ `.env.example`). Compose chỉ mở `127.0.0.1:8000`; dùng reverse proxy HTTPS và đặt `BASE_URL` đúng domain trước khi dùng OAuth. Dữ liệu lưu ở named volume `fbtt-data`; container chạy UID 10001, tự khởi động lại và xoay vòng log Docker.

Chỉ chạy **một instance / một Uvicorn worker** cho SQLite và vòng lặp nền. Worker nền chạy mỗi 15 giây, quét `data/inbox`, tạo lịch hôm nay, xử lý bài và thông báo. Token được kiểm tra gia hạn mỗi 5 phút. Không có cơ chế tự nâng lên PostgreSQL.

Trong cloud có proxy CA, build bằng:

```bash
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t fbtt:test .
```

Khi container gọi HTTPS trong môi trường proxy, mount CA bundle chỉ đọc và đặt `SSL_CERT_FILE` theo môi trường chạy. Không tắt xác thực TLS.

## Quy trình sử dụng

1. Thêm tài khoản (Facebook cần Page ID), nhóm/ngách và ghi chú. Bấm kết nối OAuth, đăng nhập tài khoản có quyền quản lý Page/TikTok. Profile mới mặc định tạm dừng.
2. Upload video hoặc thả vào `data/inbox`. Gán video cho tài khoản, gán các sản phẩm liên quan. Kiểm tra video trùng, tỉ lệ, thumbnail.
3. Thêm sản phẩm, link affiliate và mẫu caption. Mỗi dòng là một biến thể; hỗ trợ `{ten_san_pham}`, `{gia}`, `{link}`, `{hashtag}`. Tự thêm `#quảngcáo`.
4. Bật trạng thái hoạt động cho profile. Tạo lịch theo giờ Việt Nam, ngày trong tuần, độ lệch và giới hạn bài/ngày. Bài được tạo trong ngày; những khung giờ đã qua không đăng bù tự động.
5. Xem trước ở Hàng đợi, xử lý cảnh báo nội dung rồi duyệt. Mặc định chưa gửi lên nền tảng (`PUBLISH_ENABLED=false`). Chỉ bật `true` sau khi cấu hình và thử với tài khoản được ủy quyền.
6. Xem nhật ký/báo cáo. Bài TikTok xử lý xong sẽ chuyển sang chờ gắn Shop link thủ công. Nút dừng chặn bắt đầu việc mới; không thu hồi được yêu cầu đã gửi.

## Cấu hình tích hợp

- Facebook: `FACEBOOK_CLIENT_ID`, `FACEBOOK_CLIENT_SECRET`, `FACEBOOK_API_VERSION` (mặc định v25.0; kiểm tra app đang hỗ trợ phiên bản nào). Callback: `{BASE_URL}/oauth/facebook/callback`. Scope: `pages_show_list,pages_read_engagement,pages_manage_posts`. Tài khoản cần quyền quản lý Page và app cần các quyền đã được Meta cấp. Adapter hiện gọi `/PAGE_ID/videos`; **chưa có luồng Reels chuyên biệt**, và cách Meta phân phối video thành Reels cần kiểm tra trên app thật.
- TikTok: `TIKTOK_CLIENT_ID` (client key), `TIKTOK_CLIENT_SECRET`. Callback: `{BASE_URL}/oauth/tiktok/callback`. Scope `user.info.basic,video.publish`. Có PKCE, creator-info, video-init, file-upload, status-fetch; chế độ `SELF_ONLY`, tối đa 64 MiB một chunk. App chưa audit có các hạn chế của TikTok. **Chưa chứng minh đáp ứng đầy đủ UX/content disclosure theo audit TikTok**; phải thử và hoàn thiện consent/disclosure trước production. Nội dung branded/affiliate có thể không được phép đặt riêng tư theo chính sách nền tảng; không đổi sang công khai tự động.
- Facebook Page token lấy qua OAuth → long-lived user token → Page token; không giả định mọi Page token đều có thể tự làm mới. Khi cần cấp quyền lại, hệ thống phát cảnh báo. TikTok dùng refresh token và lưu lại token đã xoay.
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Nếu thiếu Telegram, có thể dùng SMTP với `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_FROM`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `ALERT_EMAIL`. SMTP bắt buộc STARTTLS. Khi cả hai được cấu hình, Telegram được ưu tiên; chưa có tự chuyển kênh nếu Telegram lỗi.
- `AUTO_BACKUP=true`: tạo bản sao mỗi ngày khi ứng dụng đang chạy. `data/backups` hiện cần được chuyển ra nơi lưu trữ khác và dọn theo chính sách của bạn; chưa có retention tự động.

Môi trường hiện chưa có credentials và chưa cấp các host Facebook/TikTok/Telegram trong allowlist mạng. Không có bài đăng, tin Telegram hoặc email thật nào được gửi khi xây dựng/test.

## An toàn hàng đợi

Bài mới cần duyệt mặc định. Lịch tự động vẫn chuyển sang chờ duyệt nếu có cảnh báo nội dung trùng/claim. Mặc định giới hạn 2 bài/ngày/profile, chỉnh tối đa 10 trong cấu hình lịch. Quy định/rate limit nền tảng có thể thấp hơn; HTTP 429 được thử lại có backoff, tối đa 3 lần. Lỗi kết nối chưa gửi yêu cầu có thể thử lại; lỗi không xác định sau khi gửi chuyển `uncertain`, không tự đăng lại. Sau crash, bài đang gửi cũng chuyển `uncertain`; cần kiểm tra trực tiếp trên nền tảng. Trong Hàng đợi, admin/người có quyền đăng có thể đối soát sau khi kiểm tra trực tiếp đúng tài khoản:

- **Đã đăng:** nhập ID bài/video đã xác minh, xác nhận; ghi nhận thành công và đánh dấu video đã dùng. TikTok vẫn cần gắn Shop link thủ công.
- **Chưa đăng:** xác nhận để đưa **chính bài đó** về chờ duyệt lại. Giữ video trong hàng đợi; không tự đăng lại, kể cả khi lịch không yêu cầu duyệt. Profile có thể xử lý bài khác sau đối soát.
- Mỗi quyết định lưu người xác nhận, thời gian, lỗi/tham chiếu cũ và ID mới trong lịch sử đối soát. Chỉ đối soát `uncertain`; quyết định cũ gửi lại sẽ bị từ chối.

TikTok ở `processing` quá `PROCESSING_TIMEOUT_SECONDS` (mặc định 1800 giây, cho phép 60–86400) chuyển sang `uncertain` và phát cảnh báo. Deadline vẫn được áp dụng khi tạm dừng hoặc tắt đăng thật, miễn vòng worker còn chạy. Hệ thống không kết luận video chưa đăng chỉ vì hết thời hạn; cần đối soát thủ công.

Token/refresh token/2FA mã hóa Fernet, mật khẩu băm scrypt, session opaque băm SHA-256 trong DB, cookie HttpOnly/SameSite (Secure khi BASE_URL HTTPS), chống CSRF bằng header riêng, OAuth state dùng một lần gắn với người dùng và profile, rate limit đăng nhập, chống replay OTP, CSP và nội dung giao diện dùng textContent. API ghi cần header `X-Requested-With: FBTT`. Không bật HTTP debug/access log: callback chứa OAuth code.

## Reverse proxy và chẩn đoán lỗi

Giới hạn đăng nhập chỉ tin `X-Forwarded-For` nếu **IP TCP kết nối trực tiếp** thuộc `TRUSTED_PROXY_CIDRS`. Mặc định không tin proxy nào; header gửi từ client không được tin sẽ bị bỏ qua. Chuỗi proxy được đọc từ phải sang trái, dừng ở hop đầu tiên không tin cậy để bỏ các địa chỉ giả chèn ở đầu. Header lỗi/quá dài/trùng lặp sẽ dùng IP TCP thay thế.

Nếu Nginx và ứng dụng chạy trực tiếp trên cùng VPS, có thể đặt `TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128`. Khi dùng Docker, cấu hình đúng IP gateway/proxy mà container nhìn thấy, không suy đoán là loopback. Chỉ tin proxy bạn kiểm soát; không dùng wildcard hoặc toàn bộ Internet. Nginx phải ghi đè header bằng địa chỉ nó quan sát được, ví dụ:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 510m;
}
```

Ứng dụng tự xác minh chuỗi proxy; Docker và `scripts/run.py` tắt việc Uvicorn tự sửa IP từ header trước đó. Nếu tự chạy Uvicorn, phải thêm `--no-proxy-headers`. Đặt `BASE_URL=https://...` để cookie Secure và OAuth redirect đúng HTTPS. Bộ đếm vẫn theo IP: người dùng cùng một NAT có thể chia sẻ giới hạn; đây không phải bộ chống brute-force phân tán.

Maintenance chạy độc lập từng bước refresh token, scan inbox, publisher, operations và cleanup. Khi lỗi, nhật ký/console ghi **tên bước + loại lỗi được cho phép**, không ghi message/URL/request/locals hoặc token. Một bước lỗi không bỏ qua các bước sau; lỗi kho nhật ký cũng không làm chết vòng lặp. Ví dụ: `scan_inbox: PermissionError; retrying next cycle`.

## Sao lưu và khôi phục

Nút tải sao lưu xuất SQLite snapshot và thư mục video trong `.tar.gz`, không kèm `.env`/khóa mã hóa. Sao lưu này chứa dữ liệu riêng tư; bảo quản hạn chế quyền truy cập. Sao lưu riêng `.env` ở kho bảo mật. Muốn khôi phục: dừng ứng dụng, giải nén bản sao tin cậy vào thư mục data mới, dùng đúng ENCRYPTION_KEY và quyền UID 10001 nếu chạy Docker, sau đó khởi động lại. Không giải nén bản sao không rõ nguồn gốc. Chưa có công cụ restore tự động hay test khôi phục disaster-recovery đầy đủ.

## Kiểm thử

```bash
python -m unittest discover -s tests -t . -v
node tests/browser.cjs
python scripts/test_docker.py
```

Test API dùng unittest + httpx MockTransport, video/thumbnail dùng FFmpeg thật. Test trình duyệt cần Node, Playwright và Chromium (`CHROMIUM_PATH` mặc định `/usr/bin/chromium`). Test Docker cần image `fbtt:test`, daemon local; chạy container độc lập, không dùng credentials/volume production. Xem ma trận [PROGRESS.md](docs/PROGRESS.md).
