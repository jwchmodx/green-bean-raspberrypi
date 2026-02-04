import serial
import time
import threading
from picamera2 import Picamera2
from libcamera import controls

PORT = "/dev/ttyACM0"
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=0.2)  # 짧게
time.sleep(2)

# =========================
# Camera init (once)
# =========================
picam2 = Picamera2()
still_cfg = picam2.create_still_configuration(
    main={"size": (2304, 1296), "format": "BGR888"}
)
picam2.configure(still_cfg)
picam2.start()
time.sleep(0.3)

def capture_image(slot_idx: int) -> str:
    img_path = f"/tmp/bean_{slot_idx}_{int(time.time()*1000)}.jpg"
    try:
        picam2.set_controls({"AfMode": controls.AfModeEnum.Auto})
        time.sleep(0.25)

        frame = picam2.capture_array()

        import cv2
        cv2.imwrite(img_path, frame)
        return img_path
    except Exception as e:
        print(f"[ERROR] capture failed: {e}")
        return ""

def external_classify(img_path: str) -> int:
    # TODO: 실제 분류
    return 0

def send_line(s: str):
    ser.write((s.strip() + "\n").encode())

def handle_line(line: str):
    if not line.startswith("CAP"):
        return
    parts = line.split()
    if len(parts) != 2:
        return
    try:
        idx = int(parts[1])
    except:
        return

    img = capture_image(idx)
    res = 1 if not img else external_classify(img)
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
    print(HELP)
    while True:
        cmd = input("cmd> ").strip()
        if cmd == "q":
            print("bye")
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

# start keyboard thread
th = threading.Thread(target=keyboard_loop, daemon=True)
th.start()

print("RPi: ready, waiting for CAP...")

buf = b""
while True:
    raw = ser.readline()
    if not raw:
        # 키보드 쓰레드가 q로 끝나면 메인도 종료하고 싶으면 아래처럼 체크 가능
        if not th.is_alive():
            break
        continue
    line = raw.decode(errors="ignore").strip()
    if not line:
        continue
    # 디버그 로그는 그냥 출력해도 되고, 필요 없으면 주석
    # print("ARD:", line)
    handle_line(line)
