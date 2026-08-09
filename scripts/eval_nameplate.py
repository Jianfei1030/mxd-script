"""离线批量评估 v3:模拟真实 _resolve_anchor 阶梯,不改任何 src 代码。

每帧判定:
1. OCR 慢通道(find_in_region,搜索区宽1.0高0.6) → 命中 + 暗底验证 → OK
2. OCR 失败 → 模板快通道(以OCR候选/画面中心为窗心) → 命中 + 暗底验证 → OK
3. 都失败 → FAIL

注意:OCR 命中即成功(真实流程中 find_in_region 返回即用锚点),
不需要再对同一帧做模板匹配。
"""
import argparse
import glob
import os
import sys

import cv2

sys.path.insert(0, '.')

from src.detect import anchor
from src.detect.anchor import search_region, split_match, capture_template, has_dark_background
from src.detect.anchor import AnchorHit

NAME = '端侧大模型'
OUT_DIR = 'screenshots/eval_nameplate'
os.makedirs(OUT_DIR, exist_ok=True)

# 搜索区(与 GUI 配置一致)
SEARCH_W, SEARCH_H, SEARCH_CY = 1.0, 0.6, 0.55


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--splits', type=int, default=4)
    ap.add_argument('--dark-ratio', type=float, default=0.30)
    ap.add_argument('--threshold', type=float, default=0.3)
    ap.add_argument('--verify-dark', type=int, default=1)
    args = ap.parse_args()

    # 裁真名字牌模板(从 frame_0120,视觉模型确认无遮挡)
    src = 'dataset/raw/dong_bu_yan_shan_2/frame_0120.png'
    frame = cv2.imread(src)
    h, w = frame.shape[:2]
    region = search_region(w, h, SEARCH_W, SEARCH_H, SEARCH_CY)
    hit = anchor.find_in_region(frame, NAME, region)
    tmpl = capture_template(frame, hit, pad=12, half_h=18)
    print(f'模板来源: {src} shape={tmpl.shape}\n')

    frames = sorted(glob.glob('dataset/raw/dong_bu_yan_shan_2/frame_*.png'))
    stats = {'ok_ocr': 0, 'ok_tmpl': 0, 'fail': 0}
    fails = []

    for fp in frames:
        frame_name = os.path.basename(fp)
        if fp == src:
            stats['ok_ocr'] += 1
            continue
        frame = cv2.imread(fp)
        h, w = frame.shape[:2]

        # 1. OCR 慢通道(真实 find_in_region)
        region = search_region(w, h, SEARCH_W, SEARCH_H, SEARCH_CY)
        ocr_hit = anchor.find_in_region(frame, NAME, region)
        if ocr_hit is not None:
            # 暗底验证:拒绝状态栏/组队列表等干扰位置的命中
            dark_ok = (not args.verify_dark) or has_dark_background(frame, ocr_hit,
                                                                     min_ratio=args.dark_ratio)
            if dark_ok:
                stats['ok_ocr'] += 1
                _save(frame, frame_name, 'OK_ocr', ocr_hit, None)
                continue

        # 2. 模板快通道:以 OCR 候选(或画面中心)为窗心
        center = (ocr_hit.x, ocr_hit.y) if ocr_hit else (w / 2, h * SEARCH_CY)
        hit_tmpl = split_match(frame, tmpl, center, 240, 80, args.threshold,
                               splits=args.splits, verify_dark=bool(args.verify_dark))
        if hit_tmpl is not None:
            stats['ok_tmpl'] += 1
            _save(frame, frame_name, 'OK_tmpl', ocr_hit, hit_tmpl)
            continue

        stats['fail'] += 1
        fails.append(frame_name)
        _save(frame, frame_name, 'FAIL', ocr_hit, None)

    total = len(frames)
    ok = stats['ok_ocr'] + stats['ok_tmpl']
    print(f'{"通道":<12} {"通过":>5}')
    print('-' * 20)
    print(f'{"OCR慢通道":<12} {stats["ok_ocr"]:>5}')
    print(f'{"模板快通道":<12} {stats["ok_tmpl"]:>5}')
    print(f'{"失败":<12} {stats["fail"]:>5}')
    print('-' * 20)
    print(f'{"合计":<12} {ok:>5}/{total} = {ok/total*100:.1f}%')
    print(f'\n失败帧: {fails}')
    return 0 if ok / total >= 0.8 else 1


def _save(frame, frame_name, status, ocr_hit, hit):
    out = frame.copy()
    if ocr_hit:
        cv2.circle(out, (int(ocr_hit.x), int(ocr_hit.y)), 15, (0, 255, 255), 2)
        cv2.putText(out, f'OCR "{ocr_hit.text}"', (int(ocr_hit.x) - 60, int(ocr_hit.y) - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
    if hit:
        color = (0, 255, 0)
        x0 = int(hit.x - hit.width / 2)
        y0 = int(hit.y - 25)
        x1 = int(hit.x + hit.width / 2)
        y1 = int(hit.y + 25)
        cv2.rectangle(out, (x0, y0), (x1, y1), color, 2)
        cv2.putText(out, f'{status} ({hit.x:.0f},{hit.y:.0f})', (x0, max(10, y0 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1)
    cv2.imwrite(os.path.join(OUT_DIR, f'{frame_name}_{status}.png'), out)


if __name__ == '__main__':
    sys.exit(main())
