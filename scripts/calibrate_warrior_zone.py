"""攻击距离标定工具(Phase 1,spec §3.6)。

用法:
    python scripts/calibrate_warrior_zone.py <帧PNG> [--name 角色名] [--json configs/xxx.json]

流程(交互式):
    1. 用屏幕截图 / 抓帧 PNG 作为输入(名字牌必须在画面内,默认帧尺寸 2560x1440)
    2. 脚本 OCR 定位名字牌 → 推算身体中心(名字牌 + 偏移)
    3. 命令行交互:输入攻击距离(px) → 画攻击框 PNG → 肉眼对照实际挥刀命中点
    4. 贴合 → y 写配置;不贴合 → 输入 ±20 调整值重画,循环直到贴合
    5. 玩家宽/高/名字牌偏移也可在同一步骤里标定

只读工具:不抓屏、不按键、不连游戏,离线可跑。
"""
import argparse
import json
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.detect import anchor  # noqa: E402
from src.task.farm_logic import warrior_attack_zone  # noqa: E402

DEFAULT_FRAME_W, DEFAULT_FRAME_H = 2560, 1440
ZONE_H_DEFAULT = 200
OFFSET_DEFAULT = 90
PLAYER_W_DEFAULT = 60
PLAYER_H_DEFAULT = 120
STEP = 20  # ±20px 步进


def locate_body(frame, character_name, offset=OFFSET_DEFAULT, ocr_fn=None):
    """OCR 定位名字牌(在角色脚下),返回 (身体中心 x, y) 或 None。

    ocr_fn 可注入,离线测试不加载模型(项目约定,见 AGENTS.md §8)。
    """
    h, w = frame.shape[:2]
    hit = anchor.find_in_region(
        frame, character_name, anchor.search_region(w, h, 0.30, 0.30), ocr_fn=ocr_fn)
    if hit is None:
        return None
    return anchor.body_center(hit, offset)


def draw_zone_png(frame, body_center, facing, attack_distance, out_path, zone_h=ZONE_H_DEFAULT):
    """画攻击框到 PNG(身体中心锚,朝向侧半矩形),返回输出路径。"""
    zone = warrior_attack_zone(body_center, facing, attack_distance, zone_h)
    x, y, w, h = (int(v) for v in zone)
    img = frame.copy()
    cv2.rectangle(img, (x, y), (x + w, y + h), (255, 0, 0), 3)
    cx, cy = int(body_center[0]), int(body_center[1])
    cv2.circle(img, (cx, cy), 6, (0, 255, 0), -1)
    cv2.imwrite(out_path, img)
    return out_path


def write_config(config_path, values):
    """把标定值写进现有配置文件(JSON 中的全局配置项)。"""
    if not os.path.exists(config_path):
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
    with open(config_path, encoding='utf-8') as f:
        config = json.load(f)
    # ok 框架配置结构:task_configs[任务名]['配置项']
    task_name = '战士调试'
    task_configs = config.setdefault('task_configs', {})
    task_cfg = task_configs.setdefault(task_name, {})
    task_cfg.update(values)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f'已写入 {config_path}: {values}')


def main():
    parser = argparse.ArgumentParser(description='攻击距离/玩家尺寸标定(Phase 1)')
    parser.add_argument('frame', help='游戏截图 PNG 路径(2560x1440,名字牌可见)')
    parser.add_argument('--name', default='', help='角色名(名字牌文本)')
    parser.add_argument('--json', dest='config_path', default='configs/config.json',
                        help='写配置的 JSON 路径(默认 configs/config.json)')
    parser.add_argument('--facing', choices=['LEFT', 'RIGHT'], default='RIGHT',
                        help='标定时的朝向(默认 RIGHT)')
    args = parser.parse_args()

    frame = cv2.imread(args.frame)
    if frame is None:
        print(f'无法读取图片: {args.frame}')
        sys.exit(1)
    fh, fw = frame.shape[:2]
    if fw != DEFAULT_FRAME_W or fh != DEFAULT_FRAME_H:
        print(f'警告: 帧尺寸 {fw}x{fh} 非 2560x1440,锚点识别 ROI 按比例适配')

    if not args.name:
        print('请提供 --name 角色名(名字牌文本),用于 OCR 定位身体中心')
        sys.exit(1)

    body = locate_body(frame, args.name)
    if body is None:
        print(f'未找到角色名 "{args.name}" 的名字牌,请检查 --name 与截图')
        sys.exit(1)
    print(f'名字牌定位成功,身体中心 = {body}')

    distance = int(input('输入攻击距离(像素,默认 120): ').strip() or 120)
    zone_h = int(input(f'输入攻击区高度(像素,默认 {ZONE_H_DEFAULT}): ').strip() or ZONE_H_DEFAULT)
    offset = int(input(f'输入名字牌到身体偏移(像素,默认 {OFFSET_DEFAULT}): ').strip() or OFFSET_DEFAULT)
    pw = int(input(f'输入玩家宽(像素,默认 {PLAYER_W_DEFAULT}): ').strip() or PLAYER_W_DEFAULT)
    ph = int(input(f'输入玩家高(像素,默认 {PLAYER_H_DEFAULT}): ').strip() or PLAYER_H_DEFAULT)

    # 重定位(用新偏移)
    body = locate_body(frame, args.name, offset)
    if body is None:
        print(f'重定位失败(偏移 {offset}),请检查角色名')
        sys.exit(1)

    out_dir = 'screenshots/calibrate'
    os.makedirs(out_dir, exist_ok=True)

    while True:
        out = os.path.join(out_dir, f'zone_{args.facing}_{distance}px.png')
        draw_zone_png(frame, body, args.facing, distance, out, zone_h)
        print(f'已画攻击框: {out} (距离 {distance}px,高 {zone_h}px,偏移 {offset}px)')
        print('打开该 PNG,对照实际挥刀最远命中点。')
        resp = input('贴合吗? y=写配置; n+数字=调整(如 n+20 / n-20,回车重画当前值): ').strip().lower()
        if resp == 'y':
            values = {'攻击距离': distance, '攻击区高': zone_h,
                      '名字牌到身体偏移': offset, '玩家宽': pw, '玩家高': ph,
                      '调试开关': True}
            write_config(args.config_path, values)
            print('标定完成。')
            break
        if resp.startswith('n'):
            tail = resp[1:].strip()
            if tail:
                try:
                    distance += int(tail)
                except ValueError:
                    print(f'无法解析调整值 "{tail}",保持 {distance}')
            else:
                distance += STEP
            print(f'攻击距离 → {distance}px')
            continue
        print('无法识别输入,保持当前值重画')


if __name__ == '__main__':
    main()
