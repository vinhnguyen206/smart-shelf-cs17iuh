# Chạy máy không cần gõ lệnh (auto-start)

Mục tiêu: **cắm điện là chạy**, không phải SSH / docker / python3 nữa.

## Cài 1 lần

Trên Jetson (ngoài container, dấu nhắc `dk@jetson:~$`):

```bash
cd workspace/iot-challenge-2025/khang-jetson/projects/local_server/deploy
bash setup-autostart.sh
```

Script đặt cho container `iot-2708` tự bật mỗi khi Jetson khởi động
(`--restart unless-stopped`) và bật Docker theo máy. Chạy lại nhiều lần
không sao.

## Sau khi cài

- **Cắm điện → đợi ~3 phút → máy tự chạy.** Không gõ gì cả.
- Mở tablet vào kiosk như thường.

## Kiểm tra (sau khi cài, hoặc sau khi khởi động lại Jetson)

```bash
docker logs -f iot-2708 2>&1 | grep --line-buffered Loadcell
```

- Thấy dòng `[Loadcell_...] Received ...` chạy lên → **máy đang chạy đúng**.
- Nếu container bật nhưng app (`main.py`) KHÔNG chạy (log trống, không có
  dòng Loadcell/WiFi) → báo lại, cần thêm bước launcher (systemd) vì entrypoint
  của container không tự gọi `main.py`. Xem `setup-autostart-launcher.sh` bên dưới.

## Các lệnh chỉ dùng khi cần

| Việc | Lệnh |
|---|---|
| Xem log cân | `docker logs -f iot-2708 2>&1 \| grep --line-buffered Loadcell` |
| Khởi động lại app | `docker restart iot-2708` |
| Tắt app tới lần bật tay kế tiếp | `docker stop iot-2708` |
| Tắt hẳn Jetson | `sudo shutdown -h now` |

## Ghi chú

- `unless-stopped`: container tự bật lại khi mất điện/khởi động **và** khi app
  crash — TRỪ khi bạn cố ý `docker stop`. Vậy bạn vẫn tắt tay được khi muốn.
- Cần xác nhận 1 điều ở buổi test tới: container `iot-2708` khi `docker start`
  có tự gọi `main.py` không. Hôm test thấy có (log WiFi/loadcell tự hiện), nên
  nhiều khả năng chỉ cần script này là đủ. Nếu không, ta thêm launcher.
