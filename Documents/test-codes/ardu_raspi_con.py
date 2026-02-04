import serial
import time

PORT = "/dev/ttyACM0"   # 필요하면 /dev/ttyUSB0 등으로 수정
BAUD = 115200

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)  # 아두이노 리셋 대기

print("Connected. Try: 0 / 90 / 180 / q")

def send_angle(a: int):
    ser.write(f"S {a}\n".encode())

while True:
    cmd = input("angle> ").strip()
    if cmd == "q":
        break

    try:
        a = int(cmd)
    except:
        print("숫자만 입력해줘 (예: 0, 90, 180)")
        continue

    send_angle(a)

    # 아두이노 응답 읽기
    time.sleep(0.1)
    while ser.in_waiting:
        print("Arduino:", ser.readline().decode(errors="ignore").strip())

ser.close()
