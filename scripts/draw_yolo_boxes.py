"""把 YOLO 标注画回图上抽查。用法: python scripts/draw_yolo_boxes.py <图片路径>"""
import os
import sys

import cv2

if __name__ == '__main__':
    img_path = sys.argv[1]
    txt = img_path.replace('images', 'labels').replace('.png', '.txt')
    img = cv2.imread(img_path)
    h, w = img.shape[:2]
    if os.path.exists(txt):
        for line in open(txt, encoding='utf-8'):
            _, cx, cy, bw, bh = map(float, line.split())
            x1, y1 = int((cx - bw / 2) * w), int((cy - bh / 2) * h)
            x2, y2 = int((cx + bw / 2) * w), int((cy + bh / 2) * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
    out = img_path.replace('.png', '_boxed.png')
    cv2.imwrite(out, img)
    print(out)
