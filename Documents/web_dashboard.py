"""
간단한 Flask 웹 대시보드

- 헤드리스 환경(RPi SSH 등)에서도 동작
- `main_predict.log` 내용을 웹에서 확인
- 최근 캡처된 원두 이미지를 "프리뷰" 처럼 보여줌

실행:
    cd ~/Documents
    python web_dashboard.py

브라우저에서:
    http://<라즈베리파이_IP>:5000
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request, send_file


app = Flask(__name__)

# =========================
# Log / 이미지 설정
# =========================
PREDICT_LOG_FILE = Path.home() / "Documents" / "main_predict.log"
BEAN_IMAGE_DIR = Path.home() / "Documents" / "bean_images"


def tail_log(path: Path, lines: int = 100) -> list[str]:
    """간단한 tail 구현 (파일 마지막 N줄)."""
    if not path.exists():
        return []

    # 너무 큰 파일을 한 번에 읽지 않도록, 뒤에서 적당량만 읽기
    with path.open("rb") as f:
        try:
            f.seek(-4096, 2)  # 파일 끝에서 4KB 정도
        except OSError:
            f.seek(0)
        data = f.read().decode(errors="ignore")

    all_lines = data.splitlines()
    return all_lines[-lines:]


# =========================
# Flask Routes
# =========================

INDEX_HTML = """
<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8">
    <title>Green Bean Monitor</title>
    <style>
      body {
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        padding: 0;
        background: #0f172a;
        color: #e5e7eb;
      }
      header {
        padding: 16px 24px;
        background: #020617;
        border-bottom: 1px solid #1e293b;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      header h1 {
        font-size: 20px;
        margin: 0;
      }
      header span {
        font-size: 12px;
        color: #9ca3af;
      }
      main {
        display: grid;
        grid-template-columns: 2fr 1.1fr;
        gap: 16px;
        padding: 16px 24px 24px;
      }
      .card {
        background: #020617;
        border-radius: 12px;
        border: 1px solid #1e293b;
        overflow: hidden;
        display: flex;
        flex-direction: column;
      }
      .card header {
        padding: 10px 14px;
        border-bottom: 1px solid #1e293b;
      }
      .card header h2 {
        margin: 0;
        font-size: 14px;
      }
      .video-wrapper {
        background: #000;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .video-wrapper img {
        width: 100%;
        height: auto;
        display: block;
      }
      .logs {
        padding: 8px 12px 10px;
        background: #020617;
      }
      #log-content {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 11px;
        white-space: pre-wrap;
        background: #020617;
        border-radius: 8px;
        padding: 8px 10px;
        border: 1px solid #1e293b;
        height: 360px;
        overflow-y: auto;
      }
      .toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
      }
      .toolbar button {
        background: #1d4ed8;
        border: none;
        color: white;
        padding: 6px 12px;
        border-radius: 999px;
        font-size: 11px;
        cursor: pointer;
      }
      .toolbar button:hover {
        background: #2563eb;
      }
      .toolbar span {
        font-size: 11px;
        color: #9ca3af;
      }
      @media (max-width: 960px) {
        main {
          grid-template-columns: 1fr;
        }
      }
    </style>
  </head>
  <body>
    <header>
      <div>
        <h1>FocalNet Green Bean Monitor</h1>
        <span>최근 캡처 이미지 &amp; 예측 로그</span>
      </div>
      <span id="status">연결 확인 중...</span>
    </header>

    <main>
      <section class="card">
        <header><h2>Last Captured Bean Image</h2></header>
        <div class="video-wrapper">
          <img id="bean-image" src="/latest_image" alt="Bean image">
        </div>
      </section>

      <section class="card">
        <header><h2>Prediction Log (main_predict.log)</h2></header>
        <div class="logs">
          <div class="toolbar">
            <button type="button" onclick="reloadLogs()">새로고침</button>
            <span id="log-meta"></span>
          </div>
          <div id="log-content">로그를 불러오는 중...</div>
        </div>
      </section>
    </main>

    <script>
      async function reloadLogs() {
        try {
          const resp = await fetch('/logs?lines=120');
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          const data = await resp.json();
          const el = document.getElementById('log-content');
          el.textContent = data.lines.join('\\n');
          el.scrollTop = el.scrollHeight;
          document.getElementById('log-meta').textContent =
            (data.lines.length || 0) + ' lines · ' + (data.exists ? '파일 있음' : '파일 없음');
        } catch (err) {
          document.getElementById('log-content').textContent =
            '로그를 불러오지 못했습니다: ' + err;
        }
      }

      async function pingStatus() {
        try {
          const resp = await fetch('/status');
          const data = await resp.json();
          const el = document.getElementById('status');
          if (data.ok) {
            el.textContent = '웹 서버 동작 중 · 최근 이미지=' + (data.has_image ? '있음' : '없음');
          } else {
            el.textContent = '에러: ' + data.message;
          }
        } catch (err) {
          document.getElementById('status').textContent = '상태 체크 실패';
        }
      }

      function refreshImage() {
        const img = document.getElementById('bean-image');
        if (!img) return;
        const ts = Date.now();
        img.src = '/latest_image?ts=' + ts;
      }

      // 주기적으로 상태/로그/이미지 갱신
      reloadLogs();
      pingStatus();
      refreshImage();
      setInterval(reloadLogs, 5000);
      setInterval(pingStatus, 3000);
      setInterval(refreshImage, 1000);
    </script>
  </body>
  </html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/logs")
def logs():
    try:
        lines = int(request.args.get("lines", 100))
    except ValueError:
        lines = 100
    log_lines = tail_log(PREDICT_LOG_FILE, lines=lines)
    return jsonify(
        {
            "exists": PREDICT_LOG_FILE.exists(),
            "path": str(PREDICT_LOG_FILE),
            "lines": log_lines,
        }
    )


@app.route("/status")
def status():
    has_image = (
        BEAN_IMAGE_DIR.exists()
        and any(BEAN_IMAGE_DIR.glob("bean_*.jpg"))
    )
    return jsonify({"ok": True, "has_image": has_image})


@app.route("/latest_image")
def latest_image():
    if not BEAN_IMAGE_DIR.exists():
        return Response(status=404)
    images = sorted(BEAN_IMAGE_DIR.glob("bean_*.jpg"))
    if not images:
        return Response(status=404)
    latest = images[-1]
    return send_file(latest, mimetype="image/jpeg")


def main():
    # 모든 네트워크에서 접속 가능하게 0.0.0.0 바인딩
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()

