import serial
import time
import threading
import cv2
from pathlib import Path

from picamera2 import Picamera2
from libcamera import controls

# =========================
# Serial
# =========================
PORT = "/dev/ttyACM0"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=0.2)
time.sleep(2)

send_lock = threading.Lock()
running = True

# =========================
# Save directory
# =========================
BASE_DIR = Path.home() / "Documents" / "bean_images"
BASE_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Camera init + auto-restart helper
# =========================
def start_camera_still(width=2304, height=1296):
    picam2 = Picamera2()
    cfg = picam2.create_still_configuration(
        main={"size": (width, height), "format": "BGR888"}
    )
    picam2.configure(cfg)
    picam2.start()
    time.sleep(0.3)
    return picam2

picam2 = start_camera_still()

def restart_camera():
    global picam2
    try:
        picam2.stop()
        picam2.close()
    except Exception:
        pass
    time.sleep(0.3)
    picam2 = start_camera_still()

def send_line(s: str):
    # 두 스레드에서 동시에 write 방지
    with send_lock:
        ser.write((s.strip() + "\n").encode())

# =========================
# Capture + dummy classify (0/1 alternating)
# =========================
toggle = 0  # 0 -> 1 -> 0 -> 1 ...

def capture_image(slot_idx: int) -> str:
    global picam2
    img_path = BASE_DIR / f"bean_{slot_idx}_{int(time.time()*1000)}.jpg"
    try:
        # AF 원샷/오토
        picam2.set_controls({"AfMode": controls.AfModeEnum.Auto})
        time.sleep(0.25)

        frame = picam2.capture_array()  # BGR888
        ok = cv2.imwrite(str(img_path), frame)
        if not ok:
            print("[ERROR] cv2.imwrite failed")
            return ""
        return str(img_path)

    except Exception as e:
        print(f"[WARN] capture failed: {e} -> restarting camera")
        restart_camera()
        return ""

def external_classify_alternating(_img_path: str) -> int:
    global toggle
    res = toggle
    toggle = 1 - toggle
    return res

# =========================
# Arduino line handler
# =========================
def handle_line(line: str):
    # CAP 프로토콜만 처리 (오탐 방지 위해 "CAP "로 엄격히)
    if not line.startswith("CAP "):
        return

    parts = line.split()
    if len(parts) != 2:
        return

    try:
        idx = int(parts[1])
    except:
        return

    print(f"[RPi] CAP received: {idx}")

    img = capture_image(idx)
    if not img:
        res = 1  # fail-safe
        print(f"[RPi] capture FAILED -> RES {idx} {res}")
    else:
        res = external_classify_alternating(img)
        print(f"[RPi] saved {img} -> RES {idx} {res}")

    send_line(f"RES {idx} {res}")

# =========================
# Keyboard thread for homing
# =========================
HELP = """
[RPi Command]
  home        -> send HOME (enter manual home mode)
  zero        -> send ZERO (set slot0 and start FSM)
  a/d/A/D     -> send JOG <key>  (must be in home mode)
  help        -> show help
  q           -> quit
"""

def keyboard_loop():
    global running
    print(HELP)
    while running:
        try:
            cmd = input("cmd> ").strip()
        except (EOFError, KeyboardInterrupt):
            running = False
            break

        if cmd == "q":
            print("bye")
            running = False
            break
        elif cmd == "help":
            print(HELP)
        elif cmd == "home":
            send_line("HOME")
        elif cmd == "zero":
            send_line("ZERO")
        elif cmd in ["a", "d", "A", "D"]:
            send_line(f"JOG {cmd}")
        else:
            print("unknown. type 'help'")

th = threading.Thread(target=keyboard_loop, daemon=True)
th.start()

print("RPi: ready, waiting for CAP...")

try:
    while running:
        raw = ser.readline()
        if not raw:
            continue

        line = raw.decode(errors="ignore").strip()
        if not line:
            continue

        # 아두이노 로그 보고 싶으면 주석 해제
        # print("ARD:", line)

        handle_line(line)

finally:
    running = False
    try:
        ser.close()
    except:
        pass
    try:
        picam2.stop()
        picam2.close()
    except:
        pass
    print("RPi: stopped")
