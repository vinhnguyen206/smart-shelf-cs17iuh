#!/usr/bin/env python3
"""
Smart Shelf Control Agent
=========================

A tiny always-on control panel that runs on the Jetson HOST (outside the
container) so you can:
  - see whether everything is healthy (BLE, camera, serial, wifi, internet)
  - press START to launch the vending app (main.py)
  - press STOP to halt it

Why separate from main.py: the page that starts main.py cannot itself be
served by main.py (it must exist while the vending app is OFF).

Runs on power-on via systemd (see control-agent.service). Open it from a
phone/tablet joined to the shelf hotspot:  http://<jetson-ip>:8088

Pure standard library — no pip install needed. Works on Python 3.6+.
"""
import json
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded server that also works on Python 3.6 (Jetson Ubuntu 18.04)."""
    daemon_threads = True

# ---- Config -----------------------------------------------------------------
CONTAINER = "iot-2708"
# Path to local_server INSIDE the container
WORKDIR = "/ultralytics/workspace/iot-challenge-2025/khang-jetson/projects/local_server"
# Host device paths to check
CAMERA_DEV = "/dev/video0"
SERIAL_DEVS = ["/dev/ttyUSB0", "/dev/ttyACM0"]
# TensorRT engine the vending app needs
ENGINE_REL = "app/modules/detector/models/yolo11n-person-640.engine"
PORT = 8088


# ---- Small shell helpers ----------------------------------------------------
def run(cmd, timeout=15):
    """Run a shell command, return (rc, stdout+stderr)."""
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace").strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:
        return 1, str(e)


def container_running():
    rc, out = run("sudo docker inspect -f '{{.State.Running}}' %s" % CONTAINER)
    return rc == 0 and out.strip().endswith("true")


def main_py_running():
    if not container_running():
        return False
    rc, _ = run('sudo docker exec %s pgrep -f "python3 main.py"' % CONTAINER)
    return rc == 0


def host_path_exists(path):
    rc, _ = run("test -e %s" % path)
    return rc == 0


def bluetooth_ok():
    # An adapter is present if `hcitool dev` lists an hci line
    rc, out = run("hcitool dev")
    return rc == 0 and "hci" in out


def wifi_status():
    rc, out = run("nmcli -t -f NAME,TYPE connection show --active")
    if rc != 0:
        return "unknown"
    return out.replace("\n", ", ") or "none"


def internet_ok():
    try:
        s = socket.create_connection(("8.8.8.8", 53), timeout=3)
        s.close()
        return True
    except OSError:
        return False


def engine_ok():
    rc, _ = run("sudo docker exec %s test -e %s/%s" % (CONTAINER, WORKDIR, ENGINE_REL))
    return rc == 0 if container_running() else host_path_exists(
        # fallback: not resolvable off-container; report False
        "/nonexistent")


def gather_health():
    cr = container_running()
    mp = main_py_running()
    return {
        "container": cr,
        "vending_running": mp,
        "camera": host_path_exists(CAMERA_DEV),
        "serial": any(host_path_exists(d) for d in SERIAL_DEVS),
        "bluetooth": bluetooth_ok(),
        "engine": engine_ok() if cr else False,
        "wifi": wifi_status(),
        "internet": internet_ok(),
    }


def start_vending():
    # Bring the container up (its own env sets up cv2/CUDA correctly), then
    # launch main.py if it is not already running.
    run("sudo docker start %s" % CONTAINER)
    if main_py_running():
        return "already running"
    # -d detached; -i INTERACTIVE bash so ~/.bashrc runs and activates the
    # uv/venv that puts cv2 + CUDA on the path (a login shell -lc does NOT
    # source .bashrc, so cv2 is missing there and main.py crashes on import).
    rc, out = run(
        "sudo docker exec -d %s bash -ic 'cd %s && python3 main.py "
        ">> /tmp/main.log 2>&1'" % (CONTAINER, WORKDIR))
    return "started" if rc == 0 else "start failed: %s" % out


def stop_vending():
    rc, _ = run('sudo docker exec %s pkill -2 -f "python3 main.py"' % CONTAINER)
    return "stopped" if rc == 0 else "was not running"


# ---- Web UI -----------------------------------------------------------------
PAGE = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Điều khiển kệ CS17IUH</title>
<style>
 :root{color-scheme:light dark}
 body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#0f1220;color:#e8eaf0}
 .wrap{max-width:520px;margin:0 auto;padding:20px}
 h1{font-size:20px;margin:8px 0 16px}
 .card{background:#1a1e33;border-radius:14px;padding:16px;margin-bottom:14px}
 .row{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #2a2f4a}
 .row:last-child{border-bottom:0}
 .dot{width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:8px}
 .ok{background:#25c26e}.bad{background:#e0483d}.warn{background:#e8a33d}
 .val{color:#9aa0b8;font-size:13px}
 button{width:100%;padding:16px;font-size:18px;font-weight:600;border:0;border-radius:12px;margin-top:10px;color:#fff}
 .start{background:#25a35a}.stop{background:#c0392b}
 button:active{opacity:.8}
 .big{font-size:15px}
 #msg{text-align:center;color:#9aa0b8;font-size:13px;min-height:18px;margin-top:8px}
</style></head><body><div class="wrap">
<h1>🛒 Điều khiển kệ CS17IUH</h1>
<div class="card" id="health">Đang kiểm tra…</div>
<div class="card">
  <div class="row big"><span>Vòng bán hàng (main.py)</span><span id="vstate">—</span></div>
  <button class="start" onclick="act('start')">▶ Khởi động máy</button>
  <button class="stop"  onclick="act('stop')">⏹ Dừng máy</button>
  <div id="msg"></div>
</div>
</div>
<script>
const LABELS={container:"Container",camera:"Camera",serial:"Cổng cân (serial)",
 bluetooth:"Bluetooth",engine:"Model AI",internet:"Internet"};
function dot(v){return '<span class="dot '+(v?'ok':'bad')+'"></span>'}
async function refresh(){
 try{
  const h=await (await fetch('/api/health',{cache:'no-store'})).json();
  let html='';
  for(const k of ['container','camera','serial','bluetooth','engine','internet']){
    html+='<div class="row"><span>'+dot(h[k])+LABELS[k]+'</span>'+
          '<span class="val">'+(h[k]?'OK':'chưa')+'</span></div>';
  }
  html+='<div class="row"><span>📶 Wifi</span><span class="val">'+h.wifi+'</span></div>';
  document.getElementById('health').innerHTML=html;
  const v=document.getElementById('vstate');
  v.innerHTML = h.vending_running ? '<span class="dot ok"></span>Đang chạy'
                                  : '<span class="dot warn"></span>Chưa chạy';
 }catch(e){document.getElementById('health').textContent='Không kết nối được agent';}
}
async function act(a){
 document.getElementById('msg').textContent='Đang '+(a==='start'?'khởi động':'dừng')+'…';
 try{const r=await (await fetch('/api/'+a,{method:'POST'})).json();
     document.getElementById('msg').textContent=r.result||'xong';}
 catch(e){document.getElementById('msg').textContent='Lỗi: '+e;}
 setTimeout(refresh,1500);
}
refresh();setInterval(refresh,2500);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path.startswith("/api/health"):
            self._send(200, json.dumps(gather_health()))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path.startswith("/api/start"):
            self._send(200, json.dumps({"result": start_vending()}))
        elif self.path.startswith("/api/stop"):
            self._send(200, json.dumps({"result": stop_vending()}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    print("Control Agent on http://0.0.0.0:%d" % PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
