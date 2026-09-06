# Smart Shelf API — Cloudflare Worker + D1

Backend thay cho `smart-shelf-server-backend` (Express + MongoDB trên Render).

**Vì sao đổi:** Render gói free ngủ sau 15 phút → mỗi lần quẹt thẻ nạp hàng phải
chờ 30–60 giây đánh thức. Worker **không có cold start**, D1 nằm ngay biên mạng.

Toàn bộ định dạng phản hồi **giữ nguyên như Express** (kể cả trường `_id`), nên
Jetson (`cloud_sync.py`) và app quản trị React **không phải sửa gì** — chỉ đổi
URL trong `.env`.

## Đã kiểm chứng chạy được (D1 cục bộ)

| Nhóm | Kết quả |
|---|---|
| `get-products` / `get-employee` / `combos` / `posters` / `sepay-config` | đúng y định dạng Jetson đang đọc |
| Đăng nhập bcrypt + JWT (HS256) | token 3 phần, sai mật khẩu → 400, ẩn `password` |
| `POST /api/orders` multipart kèm ảnh | đơn + chi tiết lưu, ảnh vào R2, đọc lại được |
| `POST /api/histories` | lưu, mảng JSON parse đúng |
| Thống kê doanh thu / top sản phẩm | trả số liệu đúng |

## Cài đặt lần đầu

```bash
cd projects/cloud_server/smart-shelf-worker
npm install

# 1) Tạo database (chép database_id in ra, dán vào wrangler.jsonc)
npx wrangler d1 create smart-shelf

# 2) Tạo bucket ảnh
npx wrangler r2 bucket create smart-shelf-images

# 3) Tạo bảng
npm run db:migrate          # --remote (thật)
npm run db:migrate:local    # cục bộ, để thử

# 4) Đặt khóa ký JWT (bí mật, không commit)
npx wrangler secret put JWT_SECRET

# 5) Deploy
npm run deploy
```

Chạy thử cục bộ: `npm run dev` → `http://127.0.0.1:8787`
(cục bộ đọc `JWT_SECRET` từ file `.dev.vars`, file này đã gitignore).

## Chuyển Jetson + app quản trị sang backend mới

Sau khi deploy sẽ có URL dạng `https://smart-shelf-api.<tên>.workers.dev`.

**Jetson** — sửa `projects/local_server/.env`, thay `onrender.com` bằng URL mới:

```
GET_PRODUCTS_API_KEY = "https://.../api/shelves/get-products/<shelf_id>"
GET_RFIDS_API_KEY    = "https://.../api/shelves/get-employee/<shelf_id>"
GET_COMBOS_API_KEY   = "https://.../api/combos"
GET_POSTERS_API_KEY  = "https://.../api/posters"
GET_SEPAY_INFO_API_KEY = "https://.../api/sepay-config/shelf/<shelf_id>"
POST_ORDER_API_KEY   = "https://.../api/orders"
POST_HISTORY_ADDED_PRODUCTS_API_KEY = "https://.../api/histories"
```

**App quản trị** — sửa `smart-shelf-server-frontend/.env`:

```
VITE_API_ENDPOINT=https://smart-shelf-api.<tên>.workers.dev/api
```

## Chuyển dữ liệu từ MongoDB sang D1

Chưa làm. Khi cần: xuất từng collection ra JSON rồi sinh câu `INSERT`, giữ
nguyên `_id` cũ làm `id` — schema thiết kế sẵn để id cũ dùng lại được, nên
`shelf_id` mà Jetson đang có trong `.env` vẫn khớp.

## Giới hạn gói FREE (dư sức cho 1 kệ)

| | Free |
|---|---|
| Worker | 100.000 request/ngày |
| D1 | 500 MB, 5 triệu dòng đọc/ngày |
| R2 | 10 GB lưu trữ |

## Chưa làm

- Chuyển dữ liệu thật từ MongoDB Atlas
- Xác thực JWT cho các route ghi (hiện mở như bản Express cũ — bản Express
  cũng không gắn `verifyToken` vào các route này)
- Webhook SePay (`/api/webhook/sepay-webhook`) và cầu MQTT
