"""攻击区标定:把锚点、身体中心、攻击区、怪框画到一张图上,肉眼调参数。

用法(仓库根目录):
  "H:/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/calibrate_attack_zone.py \
      --frame screenshots/test_frames/training_ground_full_2560x1440.png \
      --name Yufeng咕咕 --width 600 --height 200 --offset 90

看图调三个参数:
  --offset  名字牌到身体中心的距离(青色竖线的长度)
  --width/--height  攻击区(黄框)。目标是刚好覆盖你打得到的范围
调好后把值填进 GUI 的「攻击区宽/高(像素)」「名字牌到身体偏移(像素)」。
"""
import argparse
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.detect import anchor  # noqa: E402
from src.task import farm_logic  # noqa: E402

WEIGHTS = os.path.join('assets', 'mob_model', 'mob.onnx')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--frame', required=True)
    p.add_argument('--name', default='')
    p.add_argument('--width', type=float, default=600)
    p.add_argument('--height', type=float, default=200)
    p.add_argument('--offset', type=float, default=90)
    p.add_argument('--region-w', type=float, default=0.30)
    p.add_argument('--region-h', type=float, default=0.30)
    p.add_argument('--region-cy', type=float, default=0.55)
    p.add_argument('--out', default=os.path.join('screenshots', 'calibrate_attack_zone.png'))
    args = p.parse_args()

    frame = cv2.imread(args.frame)
    if frame is None:
        raise SystemExit(f'读不到帧: {args.frame}')
    h, w = frame.shape[:2]
    canvas = frame.copy()

    region = anchor.search_region(w, h, args.region_w, args.region_h, args.region_cy)
    cv2.rectangle(canvas, (region[0], region[1]), (region[2], region[3]), (255, 128, 0), 2)
    cv2.putText(canvas, 'search region', (region[0] + 6, region[1] + 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 128, 0), 2)

    hit = anchor.find_in_region(frame, args.name, region) if args.name.strip() else None
    if hit is None:
        print(f'未定位到角色名「{args.name}」,退回画面中心')
        hit = anchor.Anchor(w / 2.0, h / 2.0, 0)
    else:
        print(f'锚点 x={hit.x:.0f} y={hit.y:.0f} 框宽={hit.width}')
        cv2.rectangle(canvas, (int(hit.x - hit.width / 2), int(hit.y - 20)),
                      (int(hit.x + hit.width / 2), int(hit.y + 20)), (0, 0, 255), 2)

    body = anchor.body_center(hit, args.offset)
    cv2.line(canvas, (int(hit.x), int(hit.y)), (int(body[0]), int(body[1])), (255, 255, 0), 2)
    cv2.circle(canvas, (int(body[0]), int(body[1])), 6, (255, 255, 0), -1)

    zone = farm_logic.attack_zone(body, args.width, args.height)
    cv2.rectangle(canvas, (int(zone[0]), int(zone[1])), (int(zone[2]), int(zone[3])), (0, 255, 255), 3)

    from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
    boxes = OpenVinoYolo8Detect(weights=WEIGHTS, model_h=1280, model_w=1280).detect(
        frame, threshold=0.5, label=0)
    inside = 0
    for b in boxes:
        centre = (b.x + b.width / 2, b.y + b.height / 2)
        hot = farm_logic.point_in_zone(centre, zone)
        inside += hot
        colour = (0, 255, 0) if hot else (128, 128, 128)
        cv2.rectangle(canvas, (b.x, b.y), (b.x + b.width, b.y + b.height), colour, 2)
        cv2.circle(canvas, (int(centre[0]), int(centre[1])), 4, colour, -1)
    print(f'怪 {len(boxes)} 只,区内 {inside} 只')

    os.makedirs(os.path.dirname(args.out) or '.', exist_ok=True)
    cv2.imwrite(args.out, canvas)
    print('已写出', args.out)


if __name__ == '__main__':
    main()
