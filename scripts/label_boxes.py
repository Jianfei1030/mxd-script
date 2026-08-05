"""YOLO 格式人工框标注/纠错工具（cv2 鼠标拖拽版）。

用法:
    python scripts/label_boxes.py <图片文件夹> [--check]

操作:
    鼠标左键拖拽  = 添加一个 mob 框
    r / d          = 删除最后一个框
    n / 空格       = 保存当前图标注并进入下一张（0 个框会存空 txt，作为负样本）
    p / Backspace  = 返回上一张（自动保存当前图）
    q / Esc        = 退出

保存:
    与图片同名的 .txt 文件（YOLO 归一化格式: 0 cx cy w h），放在图片所在目录。

依赖:
    cv2（使用嵌入式 python 运行，无额外 pip 依赖）。
"""
import argparse
import os
import sys

import cv2


def print_usage():
    print("""
YOLO 标注工具
操作:
  鼠标左键拖拽  = 添加 mob 框
  r / d          = 删除最后一个框
  n / 空格       = 保存并下一张（0 框则保存空 txt 作为负样本）
  p / Backspace  = 保存并返回上一张
  q / Esc        = 退出
""")


def label_folder(folder):
    files = sorted([f for f in os.listdir(folder) if f.lower().endswith('.png')])
    if not files:
        print('No PNG images found in', folder)
        return

    idx = 0
    boxes = []
    drawing = False
    start = (0, 0)
    img = None
    orig = None
    current_path = None

    def txt_path_for(path):
        base, _ = os.path.splitext(path)
        return base + '.txt'

    def load_image(path):
        nonlocal img, orig, boxes, current_path
        current_path = path
        orig = cv2.imread(path)
        if orig is None:
            raise RuntimeError(f'无法读取图片: {path}')
        img = orig.copy()
        boxes = []
        txt_path = txt_path_for(path)
        if os.path.exists(txt_path):
            with open(txt_path, encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        boxes.append(list(map(float, parts[1:])))

    def redraw():
        nonlocal img
        img = orig.copy()
        h, w = img.shape[:2]
        for box in boxes:
            cx, cy, bw, bh = box
            x1 = int((cx - bw / 2) * w)
            y1 = int((cy - bh / 2) * h)
            x2 = int((cx + bw / 2) * w)
            y2 = int((cy + bh / 2) * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)

    def save_current():
        if current_path is None:
            return
        txt_path = txt_path_for(current_path)
        with open(txt_path, 'w', encoding='utf-8') as f:
            for box in boxes:
                f.write(f"0 {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}\n")
        print(f'saved {txt_path} ({len(boxes)} boxes)')

    def mouse(event, x, y, flags, param):
        nonlocal drawing, start, img
        h, w = orig.shape[:2]
        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            start = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and drawing:
            img = orig.copy()
            redraw()
            cv2.rectangle(img, start, (x, y), (0, 255, 0), 2)
        elif event == cv2.EVENT_LBUTTONUP:
            drawing = False
            x1, y1 = start
            x2, y2 = x, y
            x1, x2 = min(x1, x2), max(x1, x2)
            y1, y2 = min(y1, y2), max(y1, y2)
            if x2 > x1 and y2 > y1:
                cx = ((x1 + x2) / 2) / w
                cy = ((y1 + y2) / 2) / h
                bw = (x2 - x1) / w
                bh = (y2 - y1) / h
                boxes.append([cx, cy, bw, bh])
                redraw()

    print_usage()
    cv2.namedWindow('label')
    cv2.setMouseCallback('label', mouse)
    load_image(os.path.join(folder, files[idx]))

    while True:
        cv2.imshow('label', img)
        key = cv2.waitKey(50) & 0xFF
        if key in (ord('q'), 27):  # q or Esc
            break
        elif key in (ord('r'), ord('d')) and boxes:
            boxes.pop()
            redraw()
        elif key in (ord('n'), ord(' ')):
            save_current()
            idx += 1
            if idx >= len(files):
                print('All images labeled')
                break
            load_image(os.path.join(folder, files[idx]))
        elif key in (ord('p'), 8):  # p or Backspace
            save_current()
            idx -= 1
            if idx < 0:
                idx = 0
            load_image(os.path.join(folder, files[idx]))

    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description='YOLO bounding box labeler (cv2)')
    parser.add_argument('folder', help='folder containing PNG images')
    parser.add_argument('--check', action='store_true', help='non-interactive sanity check (no GUI)')
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f'Folder not found: {args.folder}')
        sys.exit(1)

    pngs = sorted([f for f in os.listdir(args.folder) if f.lower().endswith('.png')])
    print(f'Found {len(pngs)} PNG images in {args.folder}')

    if args.check:
        print('Sanity check passed: imports OK, folder readable.')
        return

    label_folder(args.folder)


if __name__ == '__main__':
    main()
