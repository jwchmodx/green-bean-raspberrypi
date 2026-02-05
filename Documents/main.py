"""
brain_5.py - Bean sorting controller with API-based defect detection

Connects to:
- Arduino via serial for hardware control
- green-bean-defect-detecting-ai API for classification
"""

import json
import logging
import os
import shutil
import serial
import time
import threading
import queue
import random
import cv2
import numpy as np
import requests
from pathlib import Path

from picamera2 import Picamera2
from libcamera import controls

# =========================
# Configuration
# =========================
API_BASE_URL = "http://121.88.140.70:8000/api/v1"
API_TIMEOUT = 10  # seconds

# If False, skip API calls and use random GOOD/DEFECT for testing
USE_API = True  # True: 실제 API /predict 사용. API 서버(localhost:8000) 실행 필요

PORT = "/dev/ttyUSB0"
BAUD = 115200

# =========================
# Serial (포트 없어도 키보드/프리뷰/와핑은 동작)
# =========================
try:
    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    time.sleep(2)
except Exception as e:
    ser = None
    print(f"[RPi] Serial not connected ({e}). Keyboard / preview / warp still work.")

send_lock = threading.Lock()
running = True

# Bean index & state management
current_index = 0  # incremented per bean
bean_states_lock = threading.Lock()
bean_states: dict[int, int] = {}  # index -> class_idx (0=good, 1=defect)
classification_queue: "queue.Queue[tuple[int, str]]" = queue.Queue()
classifier_running = True


def send_line(s: str):
    """Thread-safe serial write. 포트 미연결 시 무시."""
    if ser is None:
        return
    with send_lock:
        try:
            ser.write((s.strip() + "\n").encode())
        except Exception:
            pass

# =========================
# Save directory
# =========================
BASE_DIR = Path.home() / "Documents" / "bean_images"
BASE_DIR.mkdir(parents=True, exist_ok=True)
(BASE_DIR / "normal").mkdir(exist_ok=True)
(BASE_DIR / "defect").mkdir(exist_ok=True)

# =========================
# Predict 로그 (파일에 남김)
# =========================
PREDICT_LOG_FILE = Path.home() / "Documents" / "main_predict.log"

def _setup_predict_log():
    """예측 결과를 파일에 기록하는 로거 설정."""
    log = logging.getLogger("predict")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = logging.FileHandler(PREDICT_LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)
    return log

predict_logger: logging.Logger | None = None

# =========================
# Warp (4-point perspective) - 저장/로드 + 편집 상태
# =========================
WARP_POINTS_FILE = Path.home() / "Documents" / "warp_points.json"
warp_points_lock = threading.Lock()
warp_points: list | None = None  # 4개면 [ [x,y], ... ] 순서: 좌상, 우상, 우하, 좌하

# 라이브뷰 위에서 편집할 때 사용할 상태
warp_request = False          # 터미널에서 warp 명령으로 편집 요청
warp_edit_mode = False        # 현재 PREVIEW_WINDOW에서 편집 중인지
warp_edit_pts: list = []      # 편집 중인 4점 (좌상, 우상, 우하, 좌하)
warp_edit_frame_bgr = None    # 편집에 사용하는 정지화면 (BGR)


def load_warp_points() -> list | None:
    """저장된 4점 로드. 없거나 형식 오류면 None."""
    global warp_points
    if not WARP_POINTS_FILE.exists():
        return None
    try:
        with open(WARP_POINTS_FILE, "r", encoding="utf-8") as f:
            pts = json.load(f)
        if not isinstance(pts, list) or len(pts) != 4:
            return None
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                return None
        with warp_points_lock:
            warp_points = [list(map(float, p)) for p in pts]
        return warp_points
    except Exception:
        return None


def save_warp_points(pts: list) -> None:
    """4점을 JSON으로 저장하고 전역 warp_points 갱신."""
    global warp_points
    with open(WARP_POINTS_FILE, "w", encoding="utf-8") as f:
        json.dump(pts, f, indent=2)
    with warp_points_lock:
        warp_points = [list(p) for p in pts]


def clear_warp_points() -> None:
    """와핑 초기화: 저장된 4점 삭제 후 원본 뷰로."""
    global warp_points
    with warp_points_lock:
        warp_points = None
    if WARP_POINTS_FILE.exists():
        WARP_POINTS_FILE.unlink()

# =========================
# Camera init + restart
# =========================
def start_camera_still(width=2304, height=1296):
    picam2 = Picamera2()
    cfg = picam2.create_still_configuration(
        main={"size": (width, height), "format": "BGR888"}
    )
    picam2.configure(cfg)
    picam2.start()
    time.sleep(0.3)
    # camera_test.py처럼 연속 AF → 프리뷰/캡처 모두 초점 잘 잡힘
    picam2.set_controls({"AfMode": 2})  # 0: Manual, 1: Auto(원샷), 2: Continuous
    return picam2

picam2 = start_camera_still()
camera_lock = threading.Lock()

def restart_camera():
    global picam2
    try:
        picam2.stop()
        picam2.close()
    except Exception:
        pass
    time.sleep(0.3)
    picam2 = start_camera_still()

def capture_image(bean_id: int, pos: int) -> str:
    """
    Capture image for a bean

    Args:
        bean_id: Unique bean ID from Arduino
        pos: Current capture position

    Returns:
        Image path or empty string on failure
    """
    ts = int(time.time() * 1000)
    img_path = BASE_DIR / f"bean_{bean_id:06d}_pos{pos}_{ts}.jpg"
    try:
        with camera_lock:
            frame = picam2.capture_array()
        # BGR888 → BGR. 저장 시에도 와핑 적용
        frame_bgr = frame.copy()
        with warp_points_lock:
            pts = warp_points
        if pts is not None and len(pts) == 4:
            frame_bgr = _apply_warp(frame_bgr, pts)
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        ok = cv2.imwrite(str(img_path), frame_rgb)
        if not ok:
            print("[ERROR] cv2.imwrite failed")
            return ""
        return str(img_path)

    except Exception as e:
        print(f"[WARN] capture failed: {e} -> restarting camera")
        restart_camera()
        return ""


# =========================
# Live camera preview (camera_test.py 스타일) + 와핑 편집
# =========================
PREVIEW_WINDOW = "Bean Cam (live)"


def _apply_warp(frame_bgr: np.ndarray, pts: list) -> np.ndarray:
    """4점(좌상, 우상, 우하, 좌하) 기준 perspective warp."""
    src = np.array(pts, dtype=np.float32)
    w_top = np.linalg.norm(src[1] - src[0])
    w_bot = np.linalg.norm(src[2] - src[3])
    h_left = np.linalg.norm(src[3] - src[0])
    h_right = np.linalg.norm(src[2] - src[1])
    out_w = int(max(w_top, w_bot))
    out_h = int(max(h_left, h_right))
    if out_w < 1 or out_h < 1:
        return frame_bgr
    dst = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(frame_bgr, M, (out_w, out_h))


def _on_preview_mouse(event, x, y, _flags, _param):
    """PREVIEW_WINDOW에서 warp 편집용 마우스 이벤트."""
    global warp_edit_mode, warp_edit_pts
    if not warp_edit_mode:
        return
    if event != cv2.EVENT_LBUTTONDOWN:
        return
    px, py = float(x), float(y)
    if len(warp_edit_pts) < 4:
        warp_edit_pts.append([px, py])
    else:
        # 가장 가까운 점을 이동
        pts_arr = np.array(warp_edit_pts, dtype=np.float32)
        dists = np.sum((pts_arr - np.array([px, py], dtype=np.float32)) ** 2, axis=1)
        idx = int(np.argmin(dists))
        warp_edit_pts[idx] = [px, py]


def preview_loop():
    """실시간 카메라 창.

    - warp_points가 있으면 와핑된 화면을 보여줌.
    - 터미널에서 'warp' 입력 시, 현재 프레임을 freeze해서 같은 창 위에서 4점 편집 모드 진입.
      * 클릭: 점 추가/이동 (4개 이후에는 가장 가까운 점이 이동)
      * Enter: 4점 저장 후 편집 종료
      * ESC: 편집 취소
    """
    global warp_request, warp_edit_mode, warp_edit_pts, warp_edit_frame_bgr

    try:
        cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(PREVIEW_WINDOW, _on_preview_mouse)
    except Exception as e:
        print(f"[Preview] No display: {e}")
        return

    while running:
        try:
            # 터미널에서 warp 명령이 들어오면 편집 모드 진입 준비
            if warp_request and not warp_edit_mode:
                warp_request = False
                with camera_lock:
                    frame = picam2.capture_array()
                warp_edit_frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                # 항상 빈 상태에서 새로 4점을 찍도록 시작
                warp_edit_pts = []
                warp_edit_mode = True
                print("[Warp] Edit mode ON. Click 4 NEW points (1~4). Enter=save, ESC=cancel.")

            if warp_edit_mode:
                # 편집 모드: 정지 화면 위에 점/선 오버레이
                disp = warp_edit_frame_bgr.copy()
                pts_local = list(warp_edit_pts)
                for i, p in enumerate(pts_local):
                    cv2.circle(disp, (int(p[0]), int(p[1])), 8, (0, 255, 0), 2)
                    cv2.putText(
                        disp,
                        str(i + 1),
                        (int(p[0]) + 12, int(p[1])),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                    )
                if len(pts_local) >= 2:
                    for i in range(len(pts_local)):
                        p1 = pts_local[i]
                        p2 = pts_local[(i + 1) % len(pts_local)]
                        cv2.line(
                            disp,
                            (int(p1[0]), int(p1[1])),
                            (int(p2[0]), int(p2[1])),
                            (0, 255, 0),
                            2,
                        )
                cv2.imshow(PREVIEW_WINDOW, disp)
                key = cv2.waitKey(30) & 0xFF
                if key == 27:  # ESC -> 취소
                    warp_edit_mode = False
                    print("[Warp] Edit canceled.")
                elif key in (13, 10) and len(warp_edit_pts) == 4:  # Enter -> 저장
                    save_warp_points(warp_edit_pts)
                    print(f"[Warp] Saved 4 points to {WARP_POINTS_FILE}")
                    warp_edit_mode = False
                continue

            # 일반 라이브 프리뷰: warp_points 있으면 와핑 후 표시
            with camera_lock:
                frame = picam2.capture_array()
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            with warp_points_lock:
                pts = warp_points
            if pts is not None and len(pts) == 4:
                frame_bgr = _apply_warp(frame_bgr, pts)
            cv2.imshow(PREVIEW_WINDOW, frame_bgr)
            if cv2.waitKey(1) & 0xFF == 27:
                break
        except Exception as e:
            print(f"[Preview] {e}")
            break

    try:
        cv2.destroyWindow(PREVIEW_WINDOW)
    except Exception:
        pass


# =========================
# API Client for Classification
# =========================
def check_api_health() -> bool:
    """Check if API server is running"""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=API_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            return data.get("model_loaded", False)
    except requests.exceptions.RequestException as e:
        print(f"[API] Health check failed: {e}")
    return False

def classify_bean(img_path: str) -> tuple[int, float]:
    """
    Classify a bean image using the API

    Args:
        img_path: Path to the image file

    Returns:
        (class_idx, confidence) - class_idx: 0=good, 1=defect
        Returns (1, 0.0) on failure (fail-safe: treat as defect)
    """
    try:
        with open(img_path, "rb") as f:
            files = {"file": (Path(img_path).name, f, "image/jpeg")}
            response = requests.post(
                f"{API_BASE_URL}/predict",
                files=files,
                timeout=API_TIMEOUT
            )

        if response.status_code == 200:
            result = response.json()
            api_class_idx = result.get("class_idx", 1)
            confidence = result.get("confidence", 0.0)
            class_name = result.get("class_name", "unknown")
            inference_time = result.get("inference_time_ms", 0)

            # API는 class_idx 0=defect, 1=normal 등 4클래스 사용. main은 0=good, 1=defect.
            if class_name == "normal":
                class_idx = 0  # good
            else:
                class_idx = 1  # defect (defect, two_defect, two_normal 등)

            print(f"[API] Prediction: {class_name} -> main idx={class_idx} (conf={confidence:.2%}, time={inference_time:.1f}ms)")
            if predict_logger:
                predict_logger.info(
                    f"img={img_path} api_idx={api_class_idx} class_name={class_name} main_idx={class_idx} "
                    f"confidence={confidence:.4f} inference_time_ms={inference_time} raw={result}"
                )
            return class_idx, confidence
        else:
            print(f"[API] Error response: {response.status_code} - {response.text}")
            return 1, 0.0  # fail-safe: defect

    except requests.exceptions.Timeout:
        print("[API] Request timeout")
        return 1, 0.0
    except requests.exceptions.ConnectionError as e:
        print(f"[API] Connection error: {e}")
        print(f"       URL: {API_BASE_URL}/predict - API 서버 실행 여부 확인 (예: cd green-bean-defect-detecting-ai/Kuffee && python run_api.py)")
        return 1, 0.0
    except Exception as e:
        print(f"[API] Classification failed: {e}")
        return 1, 0.0

# =========================
# Classification worker (async)
# =========================
def classification_worker():
    """Background worker that sends images to the API and records bean states."""
    while classifier_running:
        try:
            idx, img_path = classification_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if USE_API:
            cls, conf = classify_bean(img_path)
        else:
            # Random decision for testing when API is not running
            cls = random.choice([0, 1])
            conf = 0.5

        with bean_states_lock:
            bean_states[idx] = cls

        # 판별 결과에 따라 normal/defect 폴더로 이동 (자동 데이터 수집)
        src = Path(img_path)
        if src.exists():
            subdir = "normal" if cls == 0 else "defect"
            dst = BASE_DIR / subdir / src.name
            try:
                shutil.move(str(src), str(dst))
                print(f"[RPi] moved -> {subdir}/{src.name}")
            except Exception as e:
                print(f"[RPi] move failed: {e}")

        print(
            f"[RPi] bean idx={idx} classified as "
            f"{'GOOD' if cls == 0 else 'DEFECT'} (conf={conf:.2%})"
        )
        classification_queue.task_done()


# =========================
# Arduino line handler (move_complete protocol)
# =========================
def handle_line(line: str):
    """
    Handle incoming line from Arduino.

    Expected:
        "move_complete"

    For each move_complete:
      - Assign a new bean index.
      - Capture an image and enqueue it for inference.
      - Look up bean[index-6] state:
          * if index-6 < 0          -> send 'camera_done_close'
          * if state == good (0)    -> send 'camera_done_open'
          * if state == defect (1)  -> send 'camera_done_close'
          * if state not ready yet  -> fail-safe 'camera_done_close'
    """
    global current_index

    line = line.strip()
    if line != "move_complete":
        return

    idx = current_index
    current_index += 1
    print(f"[RPi] move_complete received -> bean idx={idx}")

    # Capture current bean image
    img = capture_image(bean_id=idx, pos=0)
    if not img:
        # Capture 실패 시 해당 bean을 결점두(1)로 마킹
        print(f"[RPi] capture FAILED for idx={idx} -> mark DEFECT")
        with bean_states_lock:
            bean_states[idx] = 1
    else:
        print(f"[RPi] captured image for idx={idx}: {img}")
        classification_queue.put((idx, img))

    # Decide for bean at index-6
    decision_idx = idx - 6
    if decision_idx < 0:
        print(
            f"[RPi] decision_idx={decision_idx} < 0 -> send camera_done_close"
        )
        send_line("camera_done_close")
        return

    with bean_states_lock:
        cls = bean_states.get(decision_idx)

    if cls is None:
        # API 응답이 아직 안 온 경우: 안전하게 CLOSE
        print(
            f"[RPi] no state yet for bean idx={decision_idx} "
            f"-> fail-safe camera_done_close"
        )
        send_line("camera_done_close")
        return

    if cls == 0:
        print(f"[RPi] bean idx={decision_idx} GOOD -> camera_done_open")
        send_line("camera_done_open")
    else:
        print(f"[RPi] bean idx={decision_idx} DEFECT -> camera_done_close")
        send_line("camera_done_close")

# =========================
# Keyboard thread for control
# =========================
HELP = """
[RPi Command]
  home        -> send HOME
  s           -> send ZERO
  w           -> 라이브뷰 창에서 와핑 4점 편집 모드 진입 (Enter=save, ESC=cancel)
  c           -> 와핑 초기화 (저장된 4점 삭제, 원본 뷰로)
  a/d/A/D     -> send JOG <key>
  status      -> check API health
  help        -> show help
  q           -> quit
"""


def keyboard_loop():
    global running, warp_request
    print(HELP)
    while running:
        try:
            cmd = input("cmd> ").strip()
        except (EOFError, KeyboardInterrupt):
            running = False
            break

        if cmd == "q":
            running = False
            break
        elif cmd == "help":
            print(HELP)
        elif cmd == "home":
            send_line("HOME")
        elif cmd == "s":
            send_line("ZERO")
        elif cmd == "w":
            warp_request = True
            print("[Warp] Edit mode requested. Go to camera window and adjust 4 points (Enter=save, ESC=cancel).")
        elif cmd == "c":
            clear_warp_points()
            print("[Warp] Cleared. Preview shows raw (no warp).")
        elif cmd in ["a", "d", "A", "D"]:
            send_line(f"JOG {cmd}")
        elif cmd == "status":
            healthy = check_api_health()
            print(f"[RPi] API status: {'OK - model loaded' if healthy else 'NOT READY'}")
        else:
            print("unknown. type 'help'")

# =========================
# Main
# =========================
if __name__ == "__main__":
    predict_logger = _setup_predict_log()
    print(f"[RPi] Predict log file: {PREDICT_LOG_FILE}")
    # 저장된 와핑 4점 있으면 로드
    if load_warp_points() is not None:
        print(f"[RPi] Loaded warp points from {WARP_POINTS_FILE}")
    # Check API on startup
    print("[RPi] Checking API connection...")
    if check_api_health():
        print("[RPi] API connected and model loaded!")
    else:
        print("[RPi] WARNING: API not ready. Classification will fail-safe to defect.")

    th = threading.Thread(target=keyboard_loop, daemon=True)
    th.start()

    # Start classification worker
    worker = threading.Thread(target=classification_worker, daemon=True)
    worker.start()

    # 실시간 카메라 창 (camera_test.py 스타일)
    # DISPLAY가 없는(headless) 환경에서는 프리뷰 스레드를 띄우지 않고,
    # 카메라 캡처/분류만 동작하게 한다.
    if os.environ.get("DISPLAY"):
        preview_thread = threading.Thread(target=preview_loop, daemon=True)
        preview_thread.start()
        preview_suffix = " (ESC in preview window to close it)"
    else:
        preview_suffix = " (no local preview window; use web_dashboard.py or saved images)"

    if ser is not None:
        print("\nRPi: ready, waiting for move_complete ..." + preview_suffix)
    else:
        print("\nRPi: ready (no serial). cmd> w / s / c / status / help ..." + preview_suffix)

    try:
        while running:
            if ser is None:
                time.sleep(0.1)
                continue
            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode(errors="ignore").strip()
            if not line:
                continue

            handle_line(line)

    finally:
        running = False
        classifier_running = False
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        try:
            picam2.stop()
            picam2.close()
        except:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        print("RPi: stopped")
