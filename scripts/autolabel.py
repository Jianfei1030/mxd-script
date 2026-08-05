#!/usr/bin/env python3
"""Auto-label remaining raw frames using the weak YOLO bootstrap model.

Loads dataset/runs/mob_bootstrap/weights/best.pt and writes YOLO-format txt
files next to each PNG in dataset/raw/{map1,map2,map3}/ for frames
frame_0010.png .. frame_0049.png. Frames with zero detections get no txt.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "dataset" / "runs" / "mob_bootstrap" / "weights" / "best.pt"
RAW_DIR = ROOT / "dataset" / "raw"
CONF_THRESHOLD = 0.25
IMGSZ = 1280


def main() -> int:
    if not MODEL_PATH.exists():
        print(f"ERROR: model not found: {MODEL_PATH}", file=sys.stderr)
        return 1

    model = YOLO(str(MODEL_PATH))

    total_frames = 0
    total_with_detections = 0
    total_boxes = 0

    for map_name in ("map1", "map2", "map3"):
        map_dir = RAW_DIR / map_name
        if not map_dir.is_dir():
            print(f"WARN: skipping missing dir: {map_dir}", file=sys.stderr)
            continue

        map_frames = 0
        map_with_detections = 0
        map_boxes = 0

        for frame_idx in range(10, 50):
            png = map_dir / f"frame_{frame_idx:04d}.png"
            if not png.exists():
                continue

            map_frames += 1
            results = model.predict(
                source=str(png),
                imgsz=IMGSZ,
                conf=CONF_THRESHOLD,
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
