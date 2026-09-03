# Khởi động kệ có kiểm soát (Control Agent)

Mục tiêu: **cắm điện → Jetson boot + bật hotspot + Control Agent** (vòng bán
hàng CHƯA chạy). Bạn mở trang điều khiển qua hotspot, thấy mọi thứ **xanh**
(cân, camera, serial, bluetooth, mạng...) → bấm **Khởi động** thì máy mới vận
hành. An toàn hơn kiểu "tự chạy mù".

```
Cắm điện → Jetson boot → hotspot + Control Agent (luôn chạy)
              │
   Mở điện thoại/tablet vào hotspot → http://<jetson-ip>:8088
              │  thấy health xanh hết
              ▼  bấm "Khởi động máy"
        main.py (vòng bán hàng) chạy   ← setting.html nằm trong đây
```

## Cài 1 lần (trên Jetson HOST)

Ở dấu nhắc `dk@jetson:~$` (NGOÀI container):

```bash
# 1) Lấy thư mục deploy từ container ra host
docker cp iot-2708:/ultralytics/workspace/iot-challenge-2025/khang-jetson/projects/local_server/deploy /tmp/shelf-deploy

# 2) Cài Control Agent (chạy khi boot)
sudo bash /tmp/shelf-deploy/setup-control-agent.sh
```

Xong. Từ nay **cắm điện → đợi ~1 phút → mở `http://<jetson-ip>:8088`** để xem
sức khỏe và bấm Khởi động.

> Lấy `<jetson-ip>`: script in ra ở cuối, hoặc gõ `hostname -I`. Trên hotspot
> thường là `10.42.0.1` hoặc `192.168.x.x`.

## Trang điều khiển làm gì

- **Health**: Container / Camera / Cổng cân (serial) / Bluetooth / Model AI / Internet + trạng thái Wifi
- **▶ Khởi động máy**: bật container (nếu tắt) rồi chạy `main.py`
- **⏹ Dừng máy**: tắt `main.py` (container vẫn còn, bấm Khởi động lại nhanh)

## Kiểm tra / gỡ lỗi

```bash
systemctl status control-agent --no-pager   # agent có chạy không
journalctl -u control-agent -f              # log của agent
docker logs -f iot-2708 2>&1 | grep --line-buffered Loadcell  # log vòng bán hàng
```

## Cần xác nhận ở buổi test tới

Nút **Khởi động** đang chạy `main.py` bằng:
`docker exec -d iot-2708 bash -lc "cd <workdir> && python3 main.py"`.
Hôm 3/9 cách `docker exec` từng thiếu `cv2` (thiếu biến môi trường), nên khi
test cần xác nhận lệnh này nạp đúng môi trường (có `cv2`). Nếu không, ta chỉnh
lại cách khởi động (dùng entrypoint của container). Báo lại kết quả là tôi sửa.

## Ghi chú

- `setup-autostart.sh` (file cũ) là kiểu **tự chạy vòng bán hàng ngay khi boot**
  — KHÔNG dùng chung với Control Agent. Chọn 1 trong 2: có kiểm soát
  (control-agent) hoặc tự chạy mù (autostart). Khuyên dùng **control-agent**.
