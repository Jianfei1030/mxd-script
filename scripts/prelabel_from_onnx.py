"""用现有 mob.onnx 对 raw 帧批量预标 YOLO txt（弱模型自举第一步）。

用法:
    python scripts/prelabel_from_onnx.py <地图名> [--conf 0.25]

产出:
    对 dataset/raw/<地图名>/frame_*.png 每帧写同名 .txt（YOLO 归一化 0 cx cy w h）。
    无框帧写空 txt（负样本）。已有 txt 的帧跳过（不覆盖人工标注）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect


def main():
    map_name = sys.argv[1] if len(sys.argv) > 1 else 'patrol_ground'
    conf = float(sys.argv[sys.argv.index('--conf') + 1]) if '--conf' in sys.argv else 0.25

    raw_dir = f'dataset/raw/{map_name}'
    if not os.path.isdir(raw_dir):
        print(f'ERROR: 目录不存在 {raw_dir}')
        return 1

    detector = OpenVinoYolo8Detect(weights='assets/mob_model/mob.onnx',
                                   model_h=1280, model_w=1280)

    frames = sorted(f for f in os.listdir(raw_dir) if f.lower().endswith('.png'))
    total_boxes = 0
    with_boxes = 0
    for f in frames:
        txt_path = os.path.join(raw_dir, f.replace('.png', '.txt'))
        if os.path.exists(txt_path) and os.path.getsize(txt_path) > 0:
            print(f'skip {f} (已有标注)')
            continue

        import cv2
        img = cv2.imread(os.path.join(raw_dir, f))
        boxes = detector.detect(img, threshold=conf)
        h, w = img.shape[:2]
        lines = []
        for b in boxes:
            cx = (b.x + b.width / 2) / w
            cy = (b.y + b.height / 2) / h
            bw = b.width / w
            bh = b.height / h
            cls = 1 if b.name == 'player' else 0
            lines.append(f'{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}')
        with open(txt_path, 'w', encoding='utf-8') as out:
            out.write('\n'.join(lines) + '\n')
        if lines:
            with_boxes += 1
            total_boxes += len(lines)
        print(f'{f}: {len(lines)} boxes')

    print(f'DONE: {len(frames)} frames, {with_boxes} with boxes, {total_boxes} total boxes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
