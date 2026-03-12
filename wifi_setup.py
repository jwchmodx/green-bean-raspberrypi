#!/usr/bin/env python3
"""Simple WiFi configuration web app for Raspberry Pi."""

import subprocess
import json
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WiFi 설정</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }
  h1 { text-align: center; margin-bottom: 20px; font-size: 1.5em; }
  .status { background: #16213e; padding: 15px; border-radius: 10px; margin-bottom: 20px; }
  .status .connected { color: #4ecca3; font-weight: bold; }
  .wifi-list { list-style: none; }
  .wifi-item {
    background: #16213e; padding: 15px; margin-bottom: 8px; border-radius: 10px;
    cursor: pointer; display: flex; justify-content: space-between; align-items: center;
    transition: background 0.2s;
  }
  .wifi-item:hover { background: #1a3a5c; }
  .wifi-item.active { border: 2px solid #4ecca3; }
  .wifi-name { font-size: 1.1em; }
  .wifi-info { font-size: 0.85em; color: #888; }
  .signal-bars { font-size: 1.2em; }
  .modal-overlay {
    display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.7); z-index: 10; align-items: center; justify-content: center;
  }
  .modal-overlay.show { display: flex; }
  .modal {
    background: #16213e; padding: 25px; border-radius: 15px; width: 90%; max-width: 400px;
  }
  .modal h2 { margin-bottom: 15px; font-size: 1.2em; }
  .modal input {
    width: 100%; padding: 12px; border: 1px solid #333; border-radius: 8px;
    background: #0f3460; color: #eee; font-size: 1em; margin-bottom: 15px;
  }
  .modal .buttons { display: flex; gap: 10px; }
  .btn {
    flex: 1; padding: 12px; border: none; border-radius: 8px; font-size: 1em;
    cursor: pointer; font-weight: bold;
  }
  .btn-connect { background: #4ecca3; color: #1a1a2e; }
  .btn-cancel { background: #333; color: #eee; }
  .btn-scan {
    display: block; width: 100%; padding: 12px; background: #0f3460; color: #eee;
    border: 1px solid #333; border-radius: 10px; font-size: 1em; cursor: pointer;
    margin-bottom: 15px;
  }
  .btn-scan:hover { background: #1a3a5c; }
  .spinner { display: none; text-align: center; padding: 20px; }
  .spinner.show { display: block; }
  .msg { text-align: center; padding: 10px; margin-top: 10px; border-radius: 8px; display: none; }
  .msg.success { display: block; background: #1b4332; color: #4ecca3; }
  .msg.error { display: block; background: #3d0000; color: #ff6b6b; }
</style>
</head>
<body>
<h1>📡 WiFi 설정</h1>

<div class="status">
  현재 연결: <span class="connected" id="current-ssid">스캔 중...</span>
  <br><span class="wifi-info" id="current-ip"></span>
</div>

<button class="btn-scan" onclick="scan()">🔄 WiFi 다시 스캔</button>

<div class="spinner" id="spinner">스캔 중...</div>
<ul class="wifi-list" id="wifi-list"></ul>

<div class="modal-overlay" id="modal">
  <div class="modal">
    <h2 id="modal-ssid"></h2>
    <input type="password" id="password" placeholder="비밀번호 입력" autocomplete="off">
    <div class="buttons">
      <button class="btn btn-cancel" onclick="closeModal()">취소</button>
      <button class="btn btn-connect" onclick="connect()">연결</button>
    </div>
    <div class="msg" id="msg"></div>
  </div>
</div>

<script>
let selectedSSID = '';

async function scan() {
  document.getElementById('spinner').className = 'spinner show';
  document.getElementById('wifi-list').innerHTML = '';
  try {
    const res = await fetch('/api/scan');
    const data = await res.json();
    document.getElementById('current-ssid').textContent = data.current || '없음';
    document.getElementById('current-ip').textContent = data.ip || '';
    const list = document.getElementById('wifi-list');
    list.innerHTML = '';
    data.networks.forEach(net => {
      const li = document.createElement('li');
      li.className = 'wifi-item' + (net.in_use ? ' active' : '');
      li.innerHTML = `
        <div>
          <div class="wifi-name">${net.in_use ? '✅ ' : ''}${net.ssid}</div>
          <div class="wifi-info">${net.security} · ${net.rate}</div>
        </div>
        <div>
          <span class="signal-bars">${net.bars}</span>
          <span class="wifi-info">${net.signal}%</span>
        </div>`;
      li.onclick = () => openModal(net.ssid);
      list.appendChild(li);
    });
  } catch(e) {
    document.getElementById('wifi-list').innerHTML = '<li class="wifi-item">스캔 실패</li>';
  }
  document.getElementById('spinner').className = 'spinner';
}

function openModal(ssid) {
  selectedSSID = ssid;
  document.getElementById('modal-ssid').textContent = ssid + ' 에 연결';
  document.getElementById('password').value = '';
  document.getElementById('msg').className = 'msg';
  document.getElementById('modal').className = 'modal-overlay show';
  document.getElementById('password').focus();
}

function closeModal() {
  document.getElementById('modal').className = 'modal-overlay';
}

async function connect() {
  const pw = document.getElementById('password').value;
  const msg = document.getElementById('msg');
  msg.className = 'msg';
  msg.textContent = '연결 중...';
  msg.style.display = 'block';
  msg.style.background = '#16213e';
  msg.style.color = '#eee';
  try {
    const res = await fetch('/api/connect', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ssid: selectedSSID, password: pw})
    });
    const data = await res.json();
    if (data.success) {
      msg.className = 'msg success';
      msg.textContent = '✅ 연결 성공! IP: ' + (data.ip || '할당 중...');
      setTimeout(() => { closeModal(); scan(); }, 2000);
    } else {
      msg.className = 'msg error';
      msg.textContent = '❌ 연결 실패: ' + data.error;
    }
  } catch(e) {
    msg.className = 'msg error';
    msg.textContent = '❌ 요청 실패';
  }
}

document.getElementById('password').addEventListener('keydown', e => {
  if (e.key === 'Enter') connect();
});

scan();
</script>
</body>
</html>
"""


def get_current_wifi():
    """Get current WiFi connection info."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except Exception:
        pass
    return None


def get_ip():
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip().split()[0] if result.stdout.strip() else ""
    except Exception:
        return ""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/scan")
def api_scan():
    # Rescan
    subprocess.run(["nmcli", "dev", "wifi", "rescan"], capture_output=True, timeout=10)

    result = subprocess.run(
        ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,RATE,BARS,SECURITY", "dev", "wifi", "list"],
        capture_output=True, text=True, timeout=15
    )

    networks = []
    seen = set()
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 6:
            continue
        in_use = parts[0] == "*"
        ssid = parts[1]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        networks.append({
            "in_use": in_use,
            "ssid": ssid,
            "signal": int(parts[2]) if parts[2].isdigit() else 0,
            "rate": parts[3],
            "bars": parts[4],
            "security": parts[5],
        })

    networks.sort(key=lambda x: (-x["in_use"], -x["signal"]))

    return jsonify({
        "current": get_current_wifi(),
        "ip": get_ip(),
        "networks": networks,
    })


@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json()
    ssid = data.get("ssid", "")
    password = data.get("password", "")

    if not ssid:
        return jsonify({"success": False, "error": "SSID가 비어있습니다"})

    try:
        result = subprocess.run(
            ["nmcli", "dev", "wifi", "connect", ssid, "password", password],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            import time
            time.sleep(2)
            return jsonify({"success": True, "ip": get_ip()})
        else:
            error = result.stderr.strip() or result.stdout.strip()
            return jsonify({"success": False, "error": error})
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "연결 시간 초과"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
