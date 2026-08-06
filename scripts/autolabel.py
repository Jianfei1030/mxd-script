#!/usr/bin/env python3
"""Auto-label remaining raw frames using the weak YOLO bootstrap model.

Loads dataset/runs/mob_bootstrap/weights/best.pt (or --model) and writes
YOLO-format txt files next to each PNG in dataset/raw/<地图名>/ for frames
frame_<start>.png .. frame_<end>.png. Frames with zero detections get no txt.

用法:
    python scripts/autolabel.py
    python scripts/autolabel.py --maps myfield1 myfield2 --start 10 --end 49
    python scripts/autolabel.py --model dataset/runs/mob_bootstrap/weights/best.pt --conf 0.25
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = ROOT / "dataset" / "runs" / "mob_bootstrap" / "weights" / "best.pt"
RAW_DIR = ROOT / "dataset" / "raw"
DEFAULT_CONF = 0.25
IMGSZ = 1280
DEFAULT_MAPS = ("map1", "map2", "map3")
DEFAULT_START, DEFAULT_END = 10, 49


def main() -> int:
    parser = argparse.ArgumentParser(description='弱模型自举自动标注剩余帧')
    parser.add_argument('--maps', nargs='+', default=DEFAULT_MAPS,
                        help='要自动标注的地图名, 默认 %(default)s')
    parser.add_argument('--start', type=int, default=DEFAULT_START,
                        help='起始帧号(含), 默认 %(default)s')
    parser.add_argument('--end', type=int, default=DEFAULT_END,
                        help='结束帧号(含), 默认 %(default)s')
    parser.add_argument('--model', default=str(DEFAULT_MODEL),
                        help='弱模型权重路径, 默认 %(default)s')
    parser.add_argument('--conf', type=float, default=DEFAULT_CONF,
                        help='置信度阈值, 默认 %(default)s')
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: model not found: {model_path}", file=sys.stderr)
        return 1

    model = YOLO(str(model_path))

    total_frames = 0
    total_with_detections = 0
    total_boxes = 0

    for map_name in args.maps:
        map_dir = RAW_DIR / map_name
        if not map_dir.is_dir():
            print(f"WARN: skipping missing dir: {map_dir}", file=sys.stderr)
            continue

        map_frames = 0
        map_with_detections = 0
        map_boxes = 0

        for frame_idx in range(args.start, args.end + 1):
            png = map_dir / f"frame_{frame_idx:04d}.png"
            if not png.exists():
                continue

            map_frames += 1
            results = model.predict(
                source=str(png),
                imgsz=IMGSZ,
                conf=args.conf,
                verbose=False,
            )
            result = results[0]
            boxes = result.boxes

            if boxes is None or len(boxes) == 0:
                continue

            cls = boxes.cls.cpu().numpy().astype(int)
            xywhn = boxes.xywhn.cpu().numpy()
            lines = []
            for c, (x, y, w, h) in zip(cls, xywhn):
                lines.append(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")

            txt_path = png.with_suffix(".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            map_with_detections += 1
            map_boxes += len(lines)

        print(
            f"{map_name}: {map_frames} frames processed, "
            f"{map_with_detections} with detections, {map_boxes} boxes written"
        )
        total_frames += map_frames
        total_with_detections += map_with_detections
        total_boxes += map_boxes

    print(
        f"TOTAL: {total_frames} frames, "
        f"{total_with_detections} with detections, {total_boxes} boxes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
