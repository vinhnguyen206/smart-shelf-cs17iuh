#!/usr/bin/env python3
"""
Smart Shelf Control & Admin Panel
=================================

An always-on admin panel that runs on the Jetson HOST (outside the vending
container). It stays up even while the vending app is stopped, so it can:

  - show health (BLE, camera, serial, wifi, internet) and START/STOP the app
  - manage the 15 shelf slots (name, price, discount, weight, image)
  - show current stock per slot
  - manage employee RFID cards
  - configure the VietQR / SePay payment account
  - tail the vending app log

Why separate from main.py: the page that starts main.py cannot itself be
served by main.py (it must exist while the vending app is OFF).

Runs on power-on via systemd (control-agent.service). Join the shelf wifi
(SmartShelf-CS17IUH) and open:  http://10.42.0.1:8088

Pure standard library - no pip install needed. Works on Python 3.6+.
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
DB_DIR = WORKDIR + "/database"
# Host device paths to check
CAMERA_DEV = "/dev/video0"
SERIAL_DEVS = ["/dev/ttyUSB0", "/dev/ttyACM0"]
# TensorRT engine the vending app needs
ENGINE_REL = "app/modules/detector/models/yolo11n-person-640.engine"
PORT = 8088

# Fixed shelf geometry - the loadcell mapping depends on it, so slots are
# edited in place, never added or removed.
FLOORS = 3
COLUMNS = 5
SLOTS = FLOORS * COLUMNS

# Vietnamese bank BIN codes for VietQR (acqId)
BANKS = [
    ("970407", "Techcombank"),
    ("970436", "Vietcombank"),
    ("970415", "VietinBank"),
    ("970418", "BIDV"),
    ("970405", "Agribank"),
    ("970422", "MB Bank"),
    ("970416", "ACB"),
    ("970423", "TPBank"),
    ("970432", "VPBank"),
    ("970403", "Sacombank"),
    ("970443", "SHB"),
    ("970441", "VIB"),
]


# ---- Shell helpers ----------------------------------------------------------
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


def run_argv(argv, data=None, timeout=20):
    """Run without a shell (safe for arbitrary content), return (rc, stdout)."""
    try:
        p = subprocess.run(argv, input=data, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return 124, b"timeout"
    except Exception as e:
        return 1, str(e).encode()


# ---- Container file access --------------------------------------------------
def db_read(name):
    """Read a JSON file from the container's database/ directory."""
    rc, out = run_argv(["sudo", "docker", "exec", CONTAINER,
                        "cat", "%s/%s" % (DB_DIR, name)])
    if rc != 0:
        raise IOError(out.decode("utf-8", "replace")[:200])
    return json.loads(out.decode("utf-8"))


def db_write(name, obj):
    """Write JSON into the container's database/ dir, keeping a .bak copy."""
    path = "%s/%s" % (DB_DIR, name)
    # Keep one backup so a bad edit is always recoverable on the device.
    run("sudo docker exec %s sh -c 'cp %s %s.bak 2>/dev/null || true'"
        % (CONTAINER, path, path))
    body = json.dumps(obj, ensure_ascii=False, indent=4).encode("utf-8")
    rc, out = run_argv(["sudo", "docker", "exec", "-i", CONTAINER,
                        "sh", "-c", "cat > " + path], data=body)
    if rc != 0:
        raise IOError(out.decode("utf-8", "replace")[:200])


# ---- Health -----------------------------------------------------------------
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
    if not container_running():
        return False
    rc, _ = run("sudo docker exec %s test -e %s/%s"
                % (CONTAINER, WORKDIR, ENGINE_REL))
    return rc == 0


def gather_health():
    return {
        "container": container_running(),
        "vending_running": main_py_running(),
        "camera": host_path_exists(CAMERA_DEV),
        "serial": any(host_path_exists(d) for d in SERIAL_DEVS),
        "bluetooth": bluetooth_ok(),
        "engine": engine_ok(),
        "wifi": wifi_status(),
        "internet": internet_ok(),
    }


# ---- Machine control --------------------------------------------------------
def start_vending():
    run("sudo docker start %s" % CONTAINER)
    if main_py_running():
        return "Máy đang chạy sẵn"
    # bash -ic (INTERACTIVE) is required: the container activates its cv2/CUDA
    # environment in ~/.bashrc, which a login shell (-lc) does not read.
    rc, out = run(
        'sudo docker exec -d %s bash -ic "cd %s && python3 main.py '
        '>> /tmp/main.log 2>&1"' % (CONTAINER, WORKDIR))
    return "Đã khởi động" if rc == 0 else "Lỗi khởi động: %s" % out


def stop_vending():
    rc, _ = run('sudo docker exec %s pkill -2 -f "python3 main.py"' % CONTAINER)
    return "Đã dừng" if rc == 0 else "Máy vốn không chạy"


def read_log(lines=120):
    rc, out = run("sudo docker exec %s tail -n %d /tmp/main.log"
                  % (CONTAINER, int(lines)), timeout=20)
    return out if rc == 0 else "Không đọc được log (container tắt?)"


# ---- Domain helpers ---------------------------------------------------------
def get_products():
    """15 slots in shelf order; tolerate a short/long file."""
    try:
        items = db_read("products.json")
    except Exception:
        items = []
    out = []
    for i in range(SLOTS):
        p = items[i] if i < len(items) else {}
        out.append({
            "slot": i + 1,
            "floor": p.get("floor", i // COLUMNS + 1),
            "column": p.get("column", i % COLUMNS + 1),
            "product_id": p.get("product_id", ""),
            "product_name": p.get("product_name", ""),
            "price": p.get("price", 0),
            "discount": p.get("discount", 0),
            "weight": p.get("weight", 0),
            "max_quantity": p.get("max_quantity", 0),
            "img_url": p.get("img_url", ""),
        })
    return out


def save_products(rows):
    """Write the 15 slots back, preserving any extra keys already on disk."""
    try:
        existing = db_read("products.json")
    except Exception:
        existing = []
    result = []
    for i in range(SLOTS):
        base = dict(existing[i]) if i < len(existing) else {}
        r = rows[i] if i < len(rows) else {}
        base["product_name"] = str(r.get("product_name", "")).strip()
        base["price"] = int(r.get("price") or 0)
        base["discount"] = int(r.get("discount") or 0)
        base["weight"] = int(r.get("weight") or 0)
        base["max_quantity"] = int(r.get("max_quantity") or 0)
        base["img_url"] = str(r.get("img_url", "")).strip()
        base["floor"] = i // COLUMNS + 1
        base["column"] = i % COLUMNS + 1
        base.setdefault("product_id", "")
        result.append(base)
    db_write("products.json", result)


def get_stock():
    """Verified quantity per slot, joined with the product name."""
    try:
        values = db_read("loadcell.json").get("values", [])
    except Exception:
        values = []
    prods = get_products()
    out = []
    for i in range(SLOTS):
        q = values[i] if i < len(values) else 0
        out.append({
            "slot": i + 1,
            "floor": i // COLUMNS + 1,
            "column": i % COLUMNS + 1,
            "name": prods[i]["product_name"] or "(trống)",
            "qty": q,
            # 200/222 = product placed wrong, 255 = loadcell read error
            "err": "sai vị trí" if q in (200, 222) else ("lỗi cân" if q == 255 else ""),
        })
    return out


def get_payment():
    try:
        d = db_read("sepay_info.json")
    except Exception:
        d = {}
    return {
        "vietqrAccountNo": d.get("vietqrAccountNo", ""),
        "vietqrAccountName": d.get("vietqrAccountName", ""),
        "vietqrAcqId": d.get("vietqrAcqId", ""),
        "sepayAuthToken": d.get("sepayAuthToken", ""),
        "sepayBankAccountId": d.get("sepayBankAccountId", ""),
    }


def save_payment(p):
    try:
        d = db_read("sepay_info.json")
    except Exception:
        d = {}
    for k in ("vietqrAccountNo", "vietqrAccountName", "vietqrAcqId",
              "sepayAuthToken", "sepayBankAccountId"):
        if k in p:
            d[k] = str(p[k]).strip()
    db_write("sepay_info.json", d)


# ---- Web UI -----------------------------------------------------------------
PAGE = r"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quản trị kệ CS17IUH</title>
<style>
 :root{color-scheme:dark}
 *{box-sizing:border-box}
 body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;
      background:#0f1220;color:#e8eaf0;padding-bottom:40px}
 .wrap{max-width:900px;margin:0 auto;padding:16px}
 h1{font-size:19px;margin:6px 0 14px}
 .tabs{display:flex;gap:6px;overflow-x:auto;margin-bottom:14px;padding-bottom:4px}
 .tab{flex:0 0 auto;padding:9px 14px;border-radius:10px;background:#1a1e33;
      color:#9aa0b8;cursor:pointer;font-size:14px;white-space:nowrap;border:0}
 .tab.on{background:#2d6cdf;color:#fff;font-weight:600}
 .card{background:#1a1e33;border-radius:14px;padding:16px;margin-bottom:14px}
 .row{display:flex;align-items:center;justify-content:space-between;
      padding:9px 0;border-bottom:1px solid #2a2f4a}
 .row:last-child{border-bottom:0}
 .dot{width:11px;height:11px;border-radius:50%;display:inline-block;margin-right:8px}
 .ok{background:#25c26e}.bad{background:#e0483d}.warn{background:#e8a33d}
 .val{color:#9aa0b8;font-size:13px}
 button{padding:14px;font-size:16px;font-weight:600;border:0;border-radius:11px;
        color:#fff;cursor:pointer;width:100%;margin-top:9px}
 .start{background:#25a35a}.stop{background:#c0392b}.save{background:#2d6cdf}
 button:active{opacity:.8}
 h2{font-size:15px;margin:0 0 10px;color:#c9cee0}
 .slot{border:1px solid #2a2f4a;border-radius:11px;padding:12px;margin-bottom:10px}
 .slot h3{margin:0 0 9px;font-size:14px;color:#8fb4ff}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
 label{display:block;font-size:11px;color:#9aa0b8;margin-bottom:3px}
 input,select{width:100%;padding:9px;border-radius:8px;border:1px solid #333a5c;
        background:#111424;color:#e8eaf0;font-size:14px}
 .full{grid-column:1/-1}
 table{width:100%;border-collapse:collapse;font-size:13px}
 td,th{padding:7px 5px;border-bottom:1px solid #2a2f4a;text-align:left}
 th{color:#9aa0b8;font-weight:500;font-size:12px}
 pre{background:#0b0e1a;padding:11px;border-radius:9px;overflow:auto;
     font-size:11px;max-height:65vh;line-height:1.45;margin:0}
 .msg{text-align:center;color:#8fb4ff;font-size:13px;min-height:19px;margin-top:9px}
 .hint{color:#e8a33d;font-size:12px;margin-top:8px;line-height:1.5}
 .tagerr{color:#e0483d;font-size:11px}
 .chip{display:inline-block;background:#232a45;border-radius:7px;padding:5px 9px;
       margin:3px 5px 3px 0;font-size:13px}
 .chip b{color:#fff}
 .del{background:none;border:0;color:#e0483d;cursor:pointer;width:auto;
      padding:0 0 0 7px;margin:0;font-size:14px}
 .addrow{display:flex;gap:8px;margin-top:10px}
 .addrow input{flex:1}.addrow button{width:auto;padding:9px 16px;margin:0}
</style></head><body><div class="wrap">
<h1>🛒 Quản trị kệ CS17IUH</h1>
<div class="tabs">
  <button class="tab on" data-t="may">⚙️ Máy</button>
  <button class="tab" data-t="sp">📦 Sản phẩm</button>
  <button class="tab" data-t="ton">🗂️ Tồn kho</button>
  <button class="tab" data-t="rfid">🪪 Thẻ RFID</button>
  <button class="tab" data-t="pay">💳 Thanh toán</button>
  <button class="tab" data-t="log">📜 Nhật ký</button>
</div>

<div id="may" class="pane">
  <div class="card" id="health">Đang kiểm tra…</div>
  <div class="card">
    <div class="row" style="font-size:15px"><span>Vòng bán hàng (main.py)</span><span id="vstate">—</span></div>
    <button class="start" onclick="act('start')">▶ Khởi động máy</button>
    <button class="stop"  onclick="act('stop')">⏹ Dừng máy</button>
    <div class="msg" id="msgmay"></div>
  </div>
</div>

<div id="sp" class="pane" hidden>
  <div class="card">
    <h2>15 ngăn · 3 tầng × 5 cột</h2>
    <div id="plist">Đang tải…</div>
    <button class="save" onclick="saveProducts()">💾 Lưu sản phẩm</button>
    <div class="msg" id="msgsp"></div>
    <div class="hint" id="hintsp" hidden>⚠️ Máy đang chạy — bấm Dừng rồi Khởi động lại để áp dụng thay đổi.</div>
  </div>
</div>

<div id="ton" class="pane" hidden>
  <div class="card">
    <h2>Tồn kho theo ngăn</h2>
    <table><thead><tr><th>Ngăn</th><th>Vị trí</th><th>Sản phẩm</th><th>SL</th></tr></thead>
    <tbody id="stock"><tr><td colspan="4">Đang tải…</td></tr></tbody></table>
    <div class="hint">Mã 200/222 = đặt sai vị trí · 255 = lỗi đọc cân</div>
  </div>
</div>

<div id="rfid" class="pane" hidden>
  <div class="card">
    <h2>Thẻ nhân viên</h2>
    <div id="rlist">Đang tải…</div>
    <div class="addrow">
      <input id="newrfid" placeholder="Mã thẻ, vd 0001529690" inputmode="numeric">
      <button class="save" onclick="addRfid()">Thêm</button>
    </div>
    <button class="save" onclick="saveRfids()">💾 Lưu thẻ</button>
    <div class="msg" id="msgrfid"></div>
  </div>
</div>

<div id="pay" class="pane" hidden>
  <div class="card">
    <h2>Tài khoản nhận tiền (VietQR)</h2>
    <div class="grid">
      <div class="full"><label>Ngân hàng</label><select id="acq"></select></div>
      <div class="full"><label>Số tài khoản</label><input id="accno" inputmode="numeric"></div>
      <div class="full"><label>Tên chủ tài khoản (không dấu)</label><input id="accname"></div>
    </div>
    <h2 style="margin-top:16px">Xác nhận tự động (SePay)</h2>
    <div class="grid">
      <div class="full"><label>SePay Auth Token</label><input id="token" type="password"></div>
      <div class="full"><label>SePay Bank Account ID</label><input id="bankid"></div>
    </div>
    <button class="save" onclick="savePay()">💾 Lưu thanh toán</button>
    <div class="msg" id="msgpay"></div>
    <div class="hint">QR sẽ trỏ về tài khoản này. Cần Internet mới tạo QR và xác nhận được tiền vào.</div>
  </div>
</div>

<div id="log" class="pane" hidden>
  <div class="card">
    <h2>Nhật ký máy (main.log)</h2>
    <pre id="logbox">Đang tải…</pre>
    <button class="save" onclick="loadLog()">🔄 Tải lại</button>
  </div>
</div>
</div>
<script>
var products=[], rfids=[], running=false;
function $(i){return document.getElementById(i)}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}

document.querySelectorAll('.tab').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');
    document.querySelectorAll('.pane').forEach(function(p){p.hidden=true});
    $(b.dataset.t).hidden=false;
    if(b.dataset.t==='sp')loadProducts();
    if(b.dataset.t==='ton')loadStock();
    if(b.dataset.t==='rfid')loadRfids();
    if(b.dataset.t==='pay')loadPay();
    if(b.dataset.t==='log')loadLog();
  }});

// --- May ---
var LBL={container:"Container",camera:"Camera",serial:"Cổng cân (serial)",
 bluetooth:"Bluetooth",engine:"Model AI",internet:"Internet"};
function dot(v){return '<span class="dot '+(v?'ok':'bad')+'"></span>'}
function refresh(){
 fetch('/api/health',{cache:'no-store'}).then(function(r){return r.json()}).then(function(h){
  var html='';
  ['container','camera','serial','bluetooth','engine','internet'].forEach(function(k){
    html+='<div class="row"><span>'+dot(h[k])+LBL[k]+'</span><span class="val">'+
          (h[k]?'OK':'chưa')+'</span></div>';});
  html+='<div class="row"><span>📶 Wifi</span><span class="val">'+esc(h.wifi)+'</span></div>';
  $('health').innerHTML=html;
  running=h.vending_running;
  $('vstate').innerHTML=running?'<span class="dot ok"></span>Đang chạy'
                               :'<span class="dot warn"></span>Chưa chạy';
  $('hintsp').hidden=!running;
 }).catch(function(){$('health').textContent='Không kết nối được agent'});
}
function act(a){
 $('msgmay').textContent='Đang '+(a==='start'?'khởi động':'dừng')+'…';
 fetch('/api/'+a,{method:'POST'}).then(function(r){return r.json()})
  .then(function(r){$('msgmay').textContent=r.result||'xong';setTimeout(refresh,1500)})
  .catch(function(e){$('msgmay').textContent='Lỗi: '+e});
}

// --- San pham ---
function loadProducts(){
 fetch('/api/products',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
  products=d; var h='';
  for(var f=1;f<=3;f++){
    h+='<h2 style="margin-top:14px">Tầng '+f+'</h2>';
    d.filter(function(p){return p.floor===f}).forEach(function(p){
      var i=p.slot-1;
      h+='<div class="slot"><h3>Ngăn '+p.slot+' · tầng '+p.floor+' cột '+p.column+'</h3><div class="grid">'+
       '<div class="full"><label>Tên sản phẩm</label><input data-i="'+i+'" data-k="product_name" value="'+esc(p.product_name)+'"></div>'+
       '<div><label>Giá (đ)</label><input data-i="'+i+'" data-k="price" inputmode="numeric" value="'+esc(p.price)+'"></div>'+
       '<div><label>Giảm giá (%)</label><input data-i="'+i+'" data-k="discount" inputmode="numeric" value="'+esc(p.discount)+'"></div>'+
       '<div><label>Khối lượng 1 cái (g)</label><input data-i="'+i+'" data-k="weight" inputmode="numeric" value="'+esc(p.weight)+'"></div>'+
       '<div><label>SL tối đa</label><input data-i="'+i+'" data-k="max_quantity" inputmode="numeric" value="'+esc(p.max_quantity)+'"></div>'+
       '<div class="full"><label>Ảnh (URL)</label><input data-i="'+i+'" data-k="img_url" value="'+esc(p.img_url)+'"></div>'+
       '</div></div>';});
  }
  $('plist').innerHTML=h;
 });
}
function saveProducts(){
 document.querySelectorAll('#plist input').forEach(function(el){
   products[+el.dataset.i][el.dataset.k]=el.value;});
 $('msgsp').textContent='Đang lưu…';
 fetch('/api/products',{method:'POST',body:JSON.stringify(products)})
  .then(function(r){return r.json()})
  .then(function(r){$('msgsp').textContent=r.result||r.error||'Đã lưu'})
  .catch(function(e){$('msgsp').textContent='Lỗi: '+e});
}

// --- Ton kho ---
function loadStock(){
 fetch('/api/stock',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
  $('stock').innerHTML=d.map(function(s){
   return '<tr><td>'+s.slot+'</td><td class="val">T'+s.floor+'·C'+s.column+'</td><td>'+
     esc(s.name)+'</td><td>'+(s.err?'<span class="tagerr">'+s.err+'</span>':s.qty)+'</td></tr>';
  }).join('');
 });
}

// --- RFID ---
function loadRfids(){
 fetch('/api/rfids',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
  rfids=d; drawRfids();});
}
function drawRfids(){
 $('rlist').innerHTML=rfids.length?rfids.map(function(c,i){
   return '<span class="chip"><b>'+esc(c)+'</b><button class="del" onclick="delRfid('+i+')">✕</button></span>';
 }).join(''):'<span class="val">Chưa có thẻ nào</span>';
}
function delRfid(i){rfids.splice(i,1);drawRfids()}
function addRfid(){
 var v=$('newrfid').value.trim();
 if(v && rfids.indexOf(v)<0){rfids.push(v);$('newrfid').value='';drawRfids()}
}
function saveRfids(){
 $('msgrfid').textContent='Đang lưu…';
 fetch('/api/rfids',{method:'POST',body:JSON.stringify(rfids)})
  .then(function(r){return r.json()})
  .then(function(r){$('msgrfid').textContent=r.result||r.error||'Đã lưu'})
  .catch(function(e){$('msgrfid').textContent='Lỗi: '+e});
}

// --- Thanh toan ---
function loadPay(){
 fetch('/api/payment',{cache:'no-store'}).then(function(r){return r.json()}).then(function(d){
  $('acq').innerHTML=d.banks.map(function(b){
    return '<option value="'+b[0]+'"'+(b[0]===d.vietqrAcqId?' selected':'')+'>'+b[1]+' ('+b[0]+')</option>';
  }).join('');
  $('accno').value=d.vietqrAccountNo; $('accname').value=d.vietqrAccountName;
  $('token').value=d.sepayAuthToken; $('bankid').value=d.sepayBankAccountId;
 });
}
function savePay(){
 $('msgpay').textContent='Đang lưu…';
 fetch('/api/payment',{method:'POST',body:JSON.stringify({
   vietqrAcqId:$('acq').value, vietqrAccountNo:$('accno').value,
   vietqrAccountName:$('accname').value, sepayAuthToken:$('token').value,
   sepayBankAccountId:$('bankid').value})})
  .then(function(r){return r.json()})
  .then(function(r){$('msgpay').textContent=r.result||r.error||'Đã lưu'})
  .catch(function(e){$('msgpay').textContent='Lỗi: '+e});
}

// --- Log ---
function loadLog(){
 $('logbox').textContent='Đang tải…';
 fetch('/api/logs',{cache:'no-store'}).then(function(r){return r.text()})
  .then(function(t){$('logbox').textContent=t; $('logbox').scrollTop=$('logbox').scrollHeight})
  .catch(function(e){$('logbox').textContent='Lỗi: '+e});
}

refresh(); setInterval(function(){if(!$('may').hidden)refresh()},3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else None

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p == "/" or p.startswith("/index"):
                self._send(200, PAGE, "text/html; charset=utf-8")
            elif p == "/api/health":
                self._json(gather_health())
            elif p == "/api/products":
                self._json(get_products())
            elif p == "/api/stock":
                self._json(get_stock())
            elif p == "/api/rfids":
                try:
                    self._json(db_read("rfids.json"))
                except Exception:
                    self._json([])
            elif p == "/api/payment":
                d = get_payment()
                d["banks"] = BANKS
                self._json(d)
            elif p == "/api/logs":
                self._send(200, read_log(), "text/plain; charset=utf-8")
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            if p == "/api/start":
                self._json({"result": start_vending()})
            elif p == "/api/stop":
                self._json({"result": stop_vending()})
            elif p == "/api/products":
                save_products(self._body() or [])
                self._json({"result": "Đã lưu sản phẩm"})
            elif p == "/api/rfids":
                cards = [str(c).strip() for c in (self._body() or []) if str(c).strip()]
                db_write("rfids.json", cards)
                self._json({"result": "Đã lưu %d thẻ" % len(cards)})
            elif p == "/api/payment":
                save_payment(self._body() or {})
                self._json({"result": "Đã lưu thanh toán"})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    print("Control & Admin panel on http://0.0.0.0:%d" % PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
