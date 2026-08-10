"""找出 dbs3 帧里跨帧稳定的检测框(疑似固定元素误检)。
固定元素误检的特征:同一位置在大量帧里都有框,且该位置不是真怪刷新点。
输出:按位置聚类的框,标注出现帧数,画框图供视觉确认。
"""
import glob
import os
import sys
from collections import defaultdict

import cv2

sys.path.insert(0, '.')

from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect

det = OpenVinoYolo8Detect(weights='assets/mob_model/mob.onnx',
                          model_h=1280, model_w=1280)

frames = sorted(glob.glob('dataset/raw/dong_bu_yan_shan_3/frame_*.png'))
# 位置聚类:key=(x//100*100, y//100*100), value=帧名列表
clusters = defaultdict(list)
total_boxes = 0

for fp in frames:
    img = cv2.imread(fp)
    if img is None:
        continue
    boxes = det.detect(img, threshold=0.25)  # 低阈值抓误检
    for b in boxes:
        cx, cy = int((b.x + b.width / 2) / 100) * 100, int((b.y + b.height / 2) / 100) * 100
        clusters[(cx, cy)].append(os.path.basename(fp))
    total_boxes += len(boxes)

print(f'总帧: {len(frames)}, 总检测框(0.25阈值): {total_boxes}')
print(f'位置聚类: {len(clusters)} 个\n')

# 按出现帧数排序:出现越多的越可能是固定元素误检
stable = sorted(clusters.items(), key=lambda kv: -len(kv[1]))
print('=== 跨帧稳定出现的框(前15,疑似固定元素误检) ===')
for (cx, cy), fl in stable[:15]:
    pct = len(fl) / len(frames) * 100
    print(f'位置({cx},{cy}): {len(fl)} 帧 ({pct:.0f}%) 示例帧: {fl[0]}, {fl[-1]}')

# 保存每簇的一张示例帧画框,供视觉确认
os.makedirs('screenshots/fp_check', exist_ok=True)
for i, ((cx, cy), fl) in enumerate(stable[:10]):
    sample = fl[len(fl) // 2]
    fp = f'dataset/raw/dong_bu_yan_shan_3/{sample}'
    img = cv2.imread(fp)
    # 画该簇的框(重新检测,只画落在这个100x100格的框)
    for b in det.detect(img, threshold=0.25):
        bx, by = int((b.x + b.width / 2) / 100) * 100, int((b.y + b.height / 2) / 100) * 100
        if (bx, by) == (cx, cy):
            x1, y1 = int(b.x), int(b.y)
            x2, y2 = int(b.x + b.width), int(b.y + b.height)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 3)
    cv2.imwrite(f'screenshots/fp_check/cluster_{i:02d}_{cx}_{cy}_{sample}.png', img)
    print(f'saved cluster_{i:02d}_{cx}_{cy}_{sample}.png')
