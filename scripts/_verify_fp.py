"""验证 v5 模型:烟雾误检位置(1800,800)是否还有框。
对比 v4(旧) 和 v5(新) 在 dbs3 100 帧上的检测结果。"""
import glob
import sys

import cv2

sys.path.insert(0, '.')

from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect


def count_boxes_in_region(det, frames, x0, y0, x1, y1, threshold=0.25):
    """统计检测框中心落在 (x0,y0)-(x1,y1) 的帧数。"""
    hits = 0
    total_boxes = 0
    for fp in frames:
        img = cv2.imread(fp)
        if img is None:
            continue
        boxes = det.detect(img, threshold=threshold)
        total_boxes += len(boxes)
        for b in boxes:
            cx, cy = b.x + b.width / 2, b.y + b.height / 2
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                hits += 1
                break
    return hits, total_boxes


frames = sorted(glob.glob('dataset/raw/dong_bu_yan_shan_3/frame_*.png'))
smoke_region = (1700, 720, 1900, 860)  # 烟雾误检区域

for name, w in [('v4(旧)', 'runs/detect/runs/dbs2_incr_v4/weights/best.onnx'),
                ('v5(新)', 'runs/detect/runs/dbs3_incr_v5/weights/best.onnx')]:
    det = OpenVinoYolo8Detect(weights=w, model_h=1280, model_w=1280)
    hits, total = count_boxes_in_region(det, frames, *smoke_region)
    print(f'{name}: 烟雾区(1700-1900,720-860)命中 {hits}/100 帧 | 总检测框 {total}')
