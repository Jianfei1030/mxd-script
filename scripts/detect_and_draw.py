"""用训练好的模型对帧做推理,把检测框画回 PNG 供肉眼验收。

用法:
    python scripts/detect_and_draw.py <模型.pt> <图片或目录> [--conf 0.25] [--out 目录]

- 输入是单张 PNG 或一个目录(批量)。
- 输出:单张 → 同目录 <原名>_detected.png;目录 → <out>/<原名>_detected.png。
- 依赖: ultralytics (pip install ultralytics)。
"""
import argparse
import os
import sys

import cv2

from ultralytics import YOLO


def detect_one(model, img_path, conf, out_path):
    img = cv2.imread(img_path)
    if img is None:
        print(f'ERROR: 无法读取 {img_path}')
        return
    results = model.predict(img, conf=conf, imgsz=1280, verbose=False)
    r = results[0]
    for box in r.boxes:
        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
        cls = int(box.cls[0])
        score = float(box.conf[0])
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        label = f'{r.names[cls]} {score:.2f}'
        cv2.putText(img, label, (x1, max(y1 - 4, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cv2.imwrite(out_path, img)
    print(f'{len(r.boxes)} 个检测 → {out_path}')


def main():
    parser = argparse.ArgumentParser(description='YOLO 推理画框验收')
    parser.add_argument('model', help='模型权重, 如 dataset/runs/mob_bootstrap/weights/best.pt')
    parser.add_argument('input', help='单张 PNG 或目录')
    parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值, 默认 0.25')
    parser.add_argument('--out', default=None, help='批量输出目录, 默认输入目录')
    args = parser.parse_args()

    model = YOLO(args.model)
    if os.path.isdir(args.input):
        out_dir = args.out or args.input
        files = sorted(f for f in os.listdir(args.input) if f.lower().endswith('.png'))
        if not files:
            print(f'目录 {args.input} 无 PNG')
            return
        for f in files:
            detect_one(model, os.path.join(args.input, f), args.conf,
                       os.path.join(out_dir, f.replace('.png', '_detected.png')))
    else:
        base, ext = os.path.splitext(args.input)
        detect_one(model, args.input, args.conf, f'{base}_detected{ext}')


if __name__ == '__main__':
    main()
