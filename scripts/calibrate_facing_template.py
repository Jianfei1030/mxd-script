# -*- coding: utf-8 -*-
"""定出头+肩子框在朝向 ROI 内的偏移(spec §3.3:附录 A 没记下来,必须重定)。

用法:
    python scripts/calibrate_facing_template.py <帧图路径> <角色名>

做三件事:
1. 用真的锚点 OCR 在帧里找到角色名字牌
2. 按 facing.roi_box 裁出 180x140 的 ROI
3. 放大 4 倍 + 每 10 原始像素画一条网格线,存成 PNG

然后人工看图,读出头+肩(58x66)左上角在 ROI 内的坐标,填进
src/detect/facing.py 的 TEMPLATE_DX / TEMPLATE_DY。
"""
import os
import sys

import cv2

# 直接运行本脚本时 sys.path[0] 是 scripts/,先把项目根插进去才能 import src
# (与 scripts/calibrate_attack_zone.py 等既有脚本同一惯例)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detect import anchor, facing  # noqa: E402

SCALE = 4
GRID = 10


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    frame = cv2.imread(sys.argv[1])
    if frame is None:
        print('读不出帧图: %s' % sys.argv[1])
        return 2
    name = sys.argv[2]
    h, w = frame.shape[:2]
    region = anchor.search_region(w, h, 0.30, 0.30, 0.55)
    hit = anchor.find_in_region(frame, name, region)
    if hit is None:
        print('锚点没命中。确认角色名对、且这一帧里名字牌没被挡')
        return 1
    print('锚点: x=%.0f y=%.0f width=%d text=%r' % (hit.x, hit.y, hit.width, hit.text))
    roi = facing.crop_roi(frame, hit)
    if roi is None:
        print('ROI 越界(角色贴边),换一帧')
        return 1

    big = cv2.resize(roi, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_NEAREST)
    big = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    for x in range(0, roi.shape[1], GRID):
        cv2.line(big, (x * SCALE, 0), (x * SCALE, big.shape[0]), (0, 128, 255), 1)
        cv2.putText(big, str(x), (x * SCALE + 2, 12),
                    cv2.FONT_HERSHEY_PLAIN, 0.7, (0, 200, 255), 1)
    for y in range(0, roi.shape[0], GRID):
        cv2.line(big, (0, y * SCALE), (big.shape[1], y * SCALE), (0, 128, 255), 1)
        cv2.putText(big, str(y), (2, y * SCALE + 12),
                    cv2.FONT_HERSHEY_PLAIN, 0.7, (0, 200, 255), 1)

    out = 'screenshots/facing_roi_calib.png'
    cv2.imwrite(out, big)
    print('已存 %s(放大 %dx,网格 %d 原始像素)' % (out, SCALE, GRID))
    print('看图读出头+肩 58x66 的左上角坐标,填进 facing.TEMPLATE_DX / TEMPLATE_DY')
    return 0


if __name__ == '__main__':
    sys.exit(main())
