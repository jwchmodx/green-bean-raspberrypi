#!/usr/bin/env python3
"""
원두 이미지 empty 전처리: 두 가지 모드
  tag   - 원두 없는 흰 사진을 찾아 파일명 끝에 _empty 붙이기 (OpenCV)
  remove - 파일명에 _empty 가 붙은 파일 전부 삭제
"""

import argparse
from pathlib import Path

import cv2


# 기본 대상 디렉터리 (스크립트 기준 bean_images)
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DIR = SCRIPT_DIR.parent / "bean_images"

# tag 모드: 흰 사진 판별 기준
WHITE_THRESH = 175
WHITE_RATIO_MIN = 0.92
MEAN_MIN = 235


def is_empty_image(
    path: Path,
    white_thresh: int = WHITE_THRESH,
    white_ratio_min: float = WHITE_RATIO_MIN,
) -> bool:
    """이미지가 원두 없는 흰 사진인지 판별."""
    img = cv2.imread(str(path))
    if img is None:
        return False
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    total = h * w
    white_count = (gray >= white_thresh).sum()
    ratio = white_count / total
    if ratio >= white_ratio_min:
        return True
    mean = gray.mean()
    if mean >= MEAN_MIN and ratio >= 0.85:
        return True
    return False


def cmd_tag(args: argparse.Namespace) -> None:
    """원두 없는 흰 사진에 파일명 _empty 붙이기."""
    target_dir = args.dir.resolve()
    if not target_dir.is_dir():
        print(f"Not a directory: {target_dir}")
        return
    renamed = 0
    for path in sorted(target_dir.glob("*.jpg")):
        if path.name.endswith("_empty.jpg"):
            continue
        if not is_empty_image(
            path,
            white_thresh=args.white_thresh,
            white_ratio_min=args.white_ratio,
        ):
            continue
        new_name = path.stem + "_empty.jpg"
        new_path = path.parent / new_name
        if new_path.exists():
            print(f"[SKIP] already exists: {new_path.name}")
            continue
        if args.dry_run:
            print(f"[DRY-RUN] would rename: {path.name} -> {new_name}")
        else:
            path.rename(new_path)
            print(f"renamed: {path.name} -> {new_name}")
        renamed += 1
    print(f"Done. {'Would rename' if args.dry_run else 'Renamed'} {renamed} file(s).")


def cmd_remove(args: argparse.Namespace) -> None:
    """파일명에 _empty 가 붙은 파일 전부 삭제."""
    target_dir = args.dir.resolve()
    if not target_dir.is_dir():
        print(f"Not a directory: {target_dir}")
        return
    removed = 0
    for path in sorted(target_dir.iterdir()):
        if not path.is_file():
            continue
        if "_empty" not in path.name:
            continue
        if args.dry_run:
            print(f"[DRY-RUN] would remove: {path.name}")
        else:
            path.unlink()
            print(f"removed: {path.name}")
        removed += 1
    print(f"Done. {'Would remove' if args.dry_run else 'Removed'} {removed} file(s).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="원두 이미지 empty 전처리: tag(이름 붙이기) / remove(삭제)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_dir(p):
        p.add_argument("dir", nargs="?", type=Path, default=DEFAULT_DIR, help="대상 디렉터리 (기본: Documents/bean_images)")

    # tag
    p_tag = subparsers.add_parser("tag", help="원두 없는 흰 사진에 _empty 붙이기")
    add_dir(p_tag)
    p_tag.add_argument("--dry-run", action="store_true", help="실제 변경 없이 대상만 출력")
    p_tag.add_argument("--white-thresh", type=int, default=WHITE_THRESH, help=f"흰 픽셀 기준 밝기 (기본 {WHITE_THRESH})")
    p_tag.add_argument("--white-ratio", type=float, default=WHITE_RATIO_MIN, help=f"empty 판정 최소 흰 비율 (기본 {WHITE_RATIO_MIN})")
    p_tag.set_defaults(func=cmd_tag)

    # remove
    p_remove = subparsers.add_parser("remove", help="_empty 붙은 파일 전부 삭제")
    add_dir(p_remove)
    p_remove.add_argument("--dry-run", action="store_true", help="실제 삭제 없이 대상만 출력")
    p_remove.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
