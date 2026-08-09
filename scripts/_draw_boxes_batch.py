"""批量把 raw/<地图名> 的 YOLO 标注画回帧上,输出到 preview/boxed/<地图名>/ 供 QC。
用法: python scripts/_draw_boxes_batch.py <地图名>"""
import os
import sys

import cv2

if __name__ == '__main__':
    map_name = sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw_dir = os.path.join(root, 'dataset', 'raw', map_name)
    out_dir = os.path.join(root, 'dataset', 'preview', 'boxed', map_name)
    os.makedirs(out_dir, exist_ok=True)

    frames = sorted(f for f in os.listdir(raw_dir) if f.lower().endswith('.png'))
    total = 0
    for f in frames:
        img = cv2.imread(os.path.join(raw_dir, f))
        h, w = img.shape[:2]
        txt = os.path.join(raw_dir, f.replace('.png', '.txt'))
        if os.path.exists(txt):
            for line in open(txt, encoding='utf-8'):
                parts = line.split()
                if len(parts) != 5:
                    continue
                _, cx, cy, bw, bh = map(float, parts)
                x1, y1 = int((cx - bw / 2) * w), int((cy - bh / 2) * h)
                x2, y2 = int((cx + bw / 2) * w), int((cy + bh / 2) * h)
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                total += 1
        cv2.imwrite(os.path.join(out_dir, f), img)
    print(f'DONE: {len(frames)} frames, {total} boxes drawn -> {out_dir}')