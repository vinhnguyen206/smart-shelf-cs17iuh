# App quản trị kệ (Control & Admin Panel)

Mục tiêu: **cắm điện → Jetson boot + bật hotspot + Control Agent** (vòng bán
hàng CHƯA chạy). Bạn mở trang điều khiển qua hotspot, thấy mọi thứ **xanh**
(cân, camera, serial, bluetooth, mạng...) → bấm **Khởi động** thì máy mới vận
hành. An toàn hơn kiểu "tự chạy mù".

```
Cắm điện → Jetson boot → hotspot + Control Agent (luôn chạy)
              │
   Mở điện thoại/tablet vào hotspot → http://10.42.0.1:8088
              │  thấy health xanh hết
              ▼  bấm "Khởi động máy"
        main.py (vòng bán hàng) chạy   ← setting.html nằm trong đây
```

## Cài 1 lần (trên Jetson HOST)

Ở dấu nhắc `dk@jetson:~$` (NGOÀI container):

```bash
# 1) Lấy thư mục deploy từ container ra host
#    rm -rf là BẮT BUỘC: nếu /tmp/shelf-deploy đã tồn tại, docker cp sẽ chép
#    LỒNG vào trong (thành /tmp/shelf-deploy/deploy/...) và bạn cài lại đúng
#    bản cũ mà không hay biết.
rm -rf /tmp/shelf-deploy
docker cp iot-2708:/ultralytics/workspace/iot-challenge-2025/khang-jetson/projects/local_server/deploy /tmp/shelf-deploy

# 2) Cài Control Agent (chạy khi boot)
sudo bash /tmp/shelf-deploy/setup-control-agent.sh
```

Xong. Từ nay **cắm điện → đợi ~1 phút → mở `http://10.42.0.1:8088`** để xem
sức khỏe và bấm Khởi động.

> Lấy `<jetson-ip>`: script in ra ở cuối, hoặc gõ `hostname -I`. Trên hotspot
> thường là `10.42.0.1` hoặc `192.168.x.x`.

## App quản trị có gì (6 tab)

| Tab | Làm được |
|---|---|
| ⚙️ **Máy** | Health (Container/Camera/Cổng cân/Bluetooth/Model AI/Internet + Wifi) · nút **Khởi động** / **Dừng** |
| 📦 **Sản phẩm** | Sửa 15 ngăn (3 tầng × 5 cột): tên, giá, giảm giá %, khối lượng 1 cái, SL tối đa, ảnh. Dùng khi **fill hàng** |
| 🗂️ **Tồn kho** | Số lượng thực tế từng ngăn + cảnh báo *sai vị trí* (200/222) / *lỗi cân* (255) |
| 🪪 **Thẻ RFID** | Thêm/xóa thẻ nhân viên |
| 💳 **Thanh toán** | Chọn ngân hàng (Techcombank 970407…), số TK, tên chủ TK, token SePay → QR trỏ về tài khoản của bạn |
| 📜 **Nhật ký** | Xem `main.log` để dò lỗi, khỏi cần SSH |

**Lưu ý khi sửa sản phẩm:** nếu máy đang chạy, bấm **Dừng** rồi **Khởi động** lại để áp dụng (app nạp bảng giá/khối lượng lúc khởi động). Mỗi lần lưu, file cũ được giữ thành `.bak` trong container.

Sửa 15 ngăn tại chỗ, **không thêm/xóa ngăn** — vì ánh xạ ngăn ↔ loadcell là cố định.

## Kiểm tra / gỡ lỗi

```bash
systemctl status control-agent --no-pager   # agent có chạy không
journalctl -u control-agent -f              # log của agent
docker logs -f iot-2708 2>&1 | grep --line-buffered Loadcell  # log vòng bán hàng
```

## Cập nhật panel sau khi sửa code

Panel chạy từ bản đã cài ở `/opt/shelf-control/`, nên sau khi kéo code mới phải
chép lại rồi restart (ở `dk@jetson:~$`):

```bash
rm -rf /tmp/shelf-deploy
docker cp iot-2708:/ultralytics/workspace/iot-challenge-2025/khang-jetson/projects/local_server/deploy /tmp/shelf-deploy
sudo bash /tmp/shelf-deploy/setup-control-agent.sh
```

Kiểm tra đã cập nhật đúng chưa (phải ra số > 0):

```bash
grep -c Access-Control /opt/shelf-control/control_agent.py
```

## Ghi chú kỹ thuật

Nút Khởi động chạy `main.py` bằng `docker exec -d ... bash -ic` — **bắt buộc
`-ic` (interactive)** vì container kích hoạt môi trường cv2/CUDA trong
`~/.bashrc`; `bash -lc` (login shell) không đọc file này nên sẽ lỗi
`No module named cv2`.

## Ghi chú

- `setup-autostart.sh` (file cũ) là kiểu **tự chạy vòng bán hàng ngay khi boot**
  — KHÔNG dùng chung với Control Agent. Chọn 1 trong 2: có kiểm soát
  (control-agent) hoặc tự chạy mù (autostart). Khuyên dùng **control-agent**.
