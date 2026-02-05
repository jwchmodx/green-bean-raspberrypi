"""
간단한 Flask 웹 대시보드

- 실시간 카메라 영상 스트림 (Raspberry Pi + Picamera2 기준)
- `main_predict.log` 내용을 웹에서 확인

실행:
    cd ~/Documents
    python web_dashboard.py

브라우저에서:
    http://<라즈베리파이_IP>:5000
"""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, render_template_string, request

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None  # type: ignore


app = Flask(__name__)

# =========================
# Log 설정
# =========================
PREDICT_LOG_FILE = Path.home() / "Documents" / "main_predict.log"


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
# Camera 설정
# =========================
camera_lock = threading.Lock()
picam2: Picamera2 | None = None
use_opencv_fallback = False
cap: cv2.VideoCapture | None = None


def init_camera():
    """Picamera2 우선 사용, 실패 시 /dev/video0 OpenCV 사용."""
    global picam2, cap, use_opencv_fallback

    if Picamera2 is not None:
        try:
            cam = Picamera2()
            cfg = cam.create_video_configuration(
                main={"size": (1280, 720), "format": "RGB888"}
            )
            cam.configure(cfg)
            cam.start()
            time.sleep(0.3)
            picam2 = cam
            use_opencv_fallback = False
            print("[web] Using Picamera2 for live stream")
            return
        except Exception as e:
            print(f"[web] Picamera2 init failed: {e}")

    # fallback: 일반 USB/Webcam
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("카메라를 열 수 없습니다. Picamera2 / /dev/video0 둘 다 실패.")
    use_opencv_fallback = True
    print("[web] Using OpenCV VideoCapture(0) for live stream")


def get_frame_bgr() -> "cv2.Mat":
    """현재 BGR 프레임 하나 가져오기."""
    if not use_opencv_fallback and picam2 is not None:
        with camera_lock:
            frame = picam2.capture_array()
        # RGB888 → BGR
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        return frame_bgr

    if cap is None:
        raise RuntimeError("카메라가 초기화되지 않았습니다.")

    ret, frame_bgr = cap.read()
    if not ret:
        raise RuntimeError("카메라 프레임을 읽지 못했습니다.")
    return frame_bgr


def generate_frames():
    """multipart/x-mixed-replace 로 MJPEG 스트림 생성."""
    while True:
        try:
            frame_bgr = get_frame_bgr()
            # 필요하면 여기에서 resize 가능
            # frame_bgr = cv2.resize(frame_bgr, (960, 540))

            ret, buffer = cv2.imencode(".jpg", frame_bgr)
            if not ret:
                continue

            jpg_bytes = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpg_bytes + b"\r\n"
            )
        except Exception as e:
            print(f"[web] generate_frames error: {e}")
            time.sleep(0.1)


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
        <span>실시간 카메라 프리뷰 &amp; 예측 로그</span>
      </div>
      <span id="status">연결 확인 중...</span>
    </header>

    <main>
      <section class="card">
        <header><h2>Live Camera</h2></header>
        <div class="video-wrapper">
          <img src="{{ url_for('video_feed') }}" alt="Live video">
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
            el.textContent = '웹 서버 동작 중 · 카메라=' + (data.camera_ok ? 'OK' : '오프라인');
          } else {
            el.textContent = '에러: ' + data.message;
          }
        } catch (err) {
          document.getElementById('status').textContent = '상태 체크 실패';
        }
      }

      // 주기적으로 상태/로그 갱신
      reloadLogs();
      pingStatus();
      setInterval(reloadLogs, 5000);
      setInterval(pingStatus, 3000);
    </script>
  </body>
  </html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


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
    camera_ok = True
    if use_opencv_fallback and (cap is None or not cap.isOpened()):
        camera_ok = False
    if not use_opencv_fallback and picam2 is None:
        camera_ok = False
    return jsonify({"ok": True, "camera_ok": camera_ok})


def main():
    init_camera()
    # 모든 네트워크에서 접속 가능하게 0.0.0.0 바인딩
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)


if __name__ == "__main__":
    main()

