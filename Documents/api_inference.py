import argparse
from pathlib import Path
from typing import List

import requests


BASE_URL = "http://121.88.140.70:8000"


def health_check() -> None:
    """API Health 체크."""
    resp = requests.get(f"{BASE_URL}/api/v1/health", timeout=5)
    resp.raise_for_status()
    print("Health:", resp.json())


def get_model_info() -> None:
    """모델 정보 조회."""
    resp = requests.get(f"{BASE_URL}/api/v1/model/info", timeout=5)
    resp.raise_for_status()
    print("Model info:", resp.json())


def get_classes() -> None:
    """클래스 정보 조회."""
    resp = requests.get(f"{BASE_URL}/api/v1/classes", timeout=5)
    resp.raise_for_status()
    print("Classes:", resp.json())


def predict_single(image_path: Path) -> None:
    """단일 이미지 inference."""
    if not image_path.is_file():
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {image_path}")

    # FastAPI Swagger에서 보통 file 파라미터 이름이 "file" 이라고 가정
    files = {"file": (image_path.name, image_path.read_bytes(), "image/jpeg")}
    resp = requests.post(f"{BASE_URL}/api/v1/predict", files=files, timeout=30)
    resp.raise_for_status()
    print("Single prediction result:")
    print(resp.json())


def predict_batch(image_paths: List[Path]) -> None:
    """여러 이미지 batch inference."""
    if not image_paths:
        raise ValueError("이미지 경로가 비어 있습니다.")

    files = []
    # FastAPI에서 List[UploadFile]일 때 param 이름을 "files" 라고 가정
    for p in image_paths:
        if p.is_file():
            files.append(("files", (p.name, p.read_bytes(), "image/jpeg")))

    if not files:
        raise ValueError("유효한 이미지 파일이 없습니다.")

    resp = requests.post(f"{BASE_URL}/api/v1/predict/batch", files=files, timeout=60)
    resp.raise_for_status()
    print("Batch prediction result:")
    print(resp.json())


def collect_images_from_dir(dir_path: Path, limit: int | None = None) -> List[Path]:
    images = sorted(
        [p for p in dir_path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    )
    if limit is not None:
        images = images[:limit]
    return images


def main():
    parser = argparse.ArgumentParser(description="Remote FocalNet 커피콩 결점 분류 API inference 스크립트")
    parser.add_argument(
        "--mode",
        choices=["single", "batch"],
        default="single",
        help="single: 단일 이미지, batch: 여러 이미지",
    )
    parser.add_argument(
        "--image",
        type=str,
        help="단일 이미지 파일 경로 (mode=single일 때 사용)",
    )
    parser.add_argument(
        "--dir",
        type=str,
        help="배치로 보낼 이미지가 들어있는 디렉토리 (mode=batch일 때 사용)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="배치 모드에서 보낼 최대 이미지 개수",
    )
    parser.add_argument(
        "--no-health-check",
        action="store_true",
        help="시작할 때 health/model/classes 체크 생략",
    )

    args = parser.parse_args()

    if not args.no_health_check:
        print("=== Health Check ===")
        health_check()
        print("\n=== Model Info ===")
        get_model_info()
        print("\n=== Classes ===")
        get_classes()
        print()

    if args.mode == "single":
        if not args.image:
            raise SystemExit("--image 경로를 지정해야 합니다 (mode=single).")
        predict_single(Path(args.image))
    else:
        if not args.dir:
            raise SystemExit("--dir 경로를 지정해야 합니다 (mode=batch).")
        img_dir = Path(args.dir)
        if not img_dir.is_dir():
            raise SystemExit(f"디렉토리가 아닙니다: {img_dir}")
        images = collect_images_from_dir(img_dir, limit=args.limit)
        print(f"배치로 보낼 이미지 개수: {len(images)}")
        predict_batch(images)


if __name__ == "__main__":
    main()

