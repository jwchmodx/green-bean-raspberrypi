#!/usr/bin/env python3
import time
import cv2
from picamera2 import Picamera2

def start_camera(width=1280, height=720, fps=30):
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (width, height), "format": "BGR888"}
    )
    picam2.configure(config)

    # 자동노출/화이트밸런스는 기본으로 두고,
    # AF는 Auto(연속)로 시작. 필요하면 아래 주석 해제해서 고정 가능.
    picam2.set_controls({
        "AfMode": 2,  # 0: Manual, 1: Auto(원샷), 2: Continuous
    })

    picam2.start()
    time.sleep(0.2)  # 워밍업
    return picam2

def main():
    W, H = 1280, 720
    window = "Pi Cam Preview (ESC=quit, s=save, r=restart, f=AF-once)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    picam2 = None
    last_restart = 0.0

    try:
        picam2 = start_camera(W, H)

        while True:
            try:
                frame = picam2.capture_array()  # RGB
                # OpenCV는 BGR이 기본이라 변환
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                cv2.imshow(window, frame_bgr)

                key = cv2.waitKey(1) & 0xFF
                if key == 27:  # ESC
                    break
                elif key == ord('s'):
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    fname = f"capture_{ts}.jpg"
                    cv2.imwrite(fname, frame_bgr)
                    print(f"[Saved] {fname}")
                elif key == ord('r'):
                    raise RuntimeError("Manual restart requested")
                elif key == ord('f'):
                    # AF 원샷 한번 돌리고(1), 다시 연속(2)으로
                    picam2.set_controls({"AfMode": 1})
                    time.sleep(0.2)
                    picam2.set_controls({"AfMode": 2})
                    print("[AF] One-shot trigger")

            except Exception as e:
                # 카메라 타임아웃/끊김 등 발생 시 자동 재시작
                now = time.time()
                if now - last_restart < 1.0:
                    time.sleep(0.5)
                last_restart = now
                print(f"[WARN] Camera error: {e} -> restarting...")

                try:
                    if picam2 is not None:
                        picam2.stop()
                        picam2.close()
                except Exception:
                    pass

                time.sleep(0.5)
                picam2 = start_camera(W, H)

    finally:
        try:
            if picam2 is not None:
                picam2.stop()
                picam2.close()
        except Exception:
            pass
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
