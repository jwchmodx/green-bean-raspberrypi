import subprocess, os, time, urllib.request, uuid, logging, wave, ssl

UPLOAD_URL = "https://121.88.140.70:8080/api/upload?team=default&auto_analyze=true"
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE
RECORD_DIR = os.path.expanduser("~")
DURATION = 900  # 15 minutes
DEVICE = "plughw:CARD=Device,DEV=0"
RATE = 16000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(RECORD_DIR, "continuous_recorder.log")),
    ],
)
log = logging.getLogger("recorder")


def record_chunk(filepath):
    log.info(f"Recording: {filepath}")

    proc = subprocess.Popen(
        ["arecord", "-D", DEVICE, "-f", "S16_LE", "-r", str(RATE),
         "-c", "1", "-t", "raw", "-d", str(DURATION)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(RATE)

        while True:
            chunk = proc.stdout.read(4000)
            if not chunk:
                break
            wf.writeframes(chunk)

    proc.wait()
    return proc.returncode == 0


def upload_file(filepath):
    filename = os.path.basename(filepath)
    boundary = uuid.uuid4().hex

    with open(filepath, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        UPLOAD_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
            if resp.status == 200:
                log.info(f"Uploaded: {filename} ({len(file_data)} bytes)")
                return True
            else:
                log.error(f"Upload failed: HTTP {resp.status}")
                return False
    except Exception as e:
        log.error(f"Upload error: {e}")
        return False


def upload_and_cleanup(filepath):
    """Upload a file and delete it on success. Returns True if uploaded."""
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 1000:
        return False
    if upload_file(filepath):
        os.remove(filepath)
        log.info(f"Deleted local file: {filepath}")
        return True
    return False


def retry_pending():
    """Try to upload any leftover rec_*.wav files from previous failures."""
    pending = sorted(
        f for f in os.listdir(RECORD_DIR)
        if f.startswith("rec_") and f.endswith(".wav")
    )
    if not pending:
        return
    log.info(f"Retrying {len(pending)} pending file(s)")
    for fname in pending:
        path = os.path.join(RECORD_DIR, fname)
        if not upload_and_cleanup(path):
            log.warning(f"Retry failed, will try again later: {fname}")
            break  # server probably down, skip the rest for now


def main():
    log.info("Continuous recorder started")

    while True:
        # Retry any previously failed uploads before recording
        retry_pending()

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(RECORD_DIR, f"rec_{timestamp}.wav")

        if not record_chunk(filepath):
            log.warning("Recording failed, retrying in 10s...")
            time.sleep(10)
            continue

        if not upload_and_cleanup(filepath):
            log.warning(f"Upload failed, keeping: {filepath}")


if __name__ == "__main__":
    main()
