#!/usr/bin/env python3
import serial
import time
import cv2
from pathlib import Path
from picamera2 import Picamera2
from libcamera import controls

# =========================
# Serial Setup
# =========================
PORT = "/dev/ttyUSB0"
BAUD = 115200

# =========================
# Camera Setup
# =========================
def start_camera(width=2304, height=1296):
    picam2 = Picamera2()
    cfg = picam2.create_still_configuration(
        main={"size": (width, height), "format": "BGR888"}
    )
    picam2.configure(cfg)
    picam2.start()
    time.sleep(0.3)
    return picam2

def capture_image(picam2, save_path):
    try:
        picam2.set_controls({"AfMode": controls.AfModeEnum.Auto})
        time.sleep(0.25)
        frame = picam2.capture_array()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ok = cv2.imwrite(str(save_path), frame)
        if ok:
            print(f"[OK] Saved: {save_path}")
            return True
        else:
            print("[ERROR] Failed to save image")
            return False
    except Exception as e:
        print(f"[ERROR] Capture failed: {e}")
        return False

def send_command(ser, cmd):
    ser.write((cmd.strip() + "\n").encode())
    time.sleep(0.1)

def main():
    # Choose category
    print("=" * 40)
    print("  Data Collector - Green Bean")
    print("=" * 40)
    print("\nChoose category:")
    print("  1. normal")
    print("  2. defect")
    print()

    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            category = "normal"
            break
        elif choice == "2":
            category = "defect"
            break
        else:
            print("Invalid input. Please enter 1 or 2.")

    # Setup directories
    data_dir = Path.home() / "Documents" / "data" / category
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving images to: {data_dir}")

    # Initialize serial
    print(f"\nConnecting to Arduino on {PORT}...")
    ser = serial.Serial(PORT, BAUD, timeout=0.2)
    time.sleep(2)
    print("Serial connected.")

    # Initialize camera
    print("Starting camera...")
    picam2 = start_camera()
    print("Camera ready.")

    # Count existing images
    existing = list(data_dir.glob("*.jpg"))
    img_count = len(existing)

    HELP = """
========================================
  Commands:
    ENTER       -> step motor + capture
    home        -> send HOME
    zero        -> send ZERO
    a/d/A/D     -> JOG motor
    help        -> show this help
    q           -> quit
========================================
"""
    print("\n" + "=" * 40)
    print(f"Category: {category.upper()}")
    print(f"Existing images: {img_count}")
    print(HELP)

    try:
        while True:
            user_input = input(f"[{img_count}] cmd> ").strip()

            if user_input == 'q':
                print("\nExiting...")
                break
            elif user_input == 'help':
                print(HELP)
            elif user_input == 'home':
                print("  Sending HOME...")
                send_command(ser, "HOME")
            elif user_input == 'zero':
                print("  Sending ZERO...")
                send_command(ser, "ZERO")
            elif user_input in ['a', 'd', 'A', 'D']:
                print(f"  JOG {user_input}...")
                send_command(ser, f"JOG {user_input}")
            elif user_input == '':
                # ENTER pressed: step motor + capture
                print("  Stepping motor...")
                send_command(ser, "JOG d")
                time.sleep(0.3)

                # Capture image
                ts = int(time.time() * 1000)
                img_path = data_dir / f"{category}_{img_count:04d}_{ts}.jpg"

                print("  Capturing image...")
                if capture_image(picam2, img_path):
                    img_count += 1
            else:
                print("  Unknown command. Type 'help' for options.")

            print()

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")

    finally:
        print("Cleaning up...")
        try:
            ser.close()
        except:
            pass
        try:
            picam2.stop()
            picam2.close()
        except:
            pass
        print("Done.")

if __name__ == "__main__":
    main()
