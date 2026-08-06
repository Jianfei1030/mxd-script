import json
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.calibrate_warrior_zone import (  # noqa: E402
    draw_zone_png,
    locate_body,
    write_config,
)

FRAME_W, FRAME_H = 2560, 1440


def make_frame_with_nametag(nametag_pos=(1100, 860), size=(130, 30)):
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    x, y = nametag_pos
    w, h = size
    frame[y:y + h, x:x + w] = 255
    return frame


class FakeOcr:
    def __init__(self, frame):
        self._frame = frame

    def ocr(self, crop):
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = (gray > 128).astype(np.uint8)
        if mask.sum() < 500:
            return []
        ys, xs = np.where(mask)
        box = [(xs.min(), ys.min()), (xs.max(), ys.min()),
               (xs.max(), ys.max()), (xs.min(), ys.max())]
        return [(box, ('Yufeng咕咕', 0.9))]


class TestCalibrateOffline(unittest.TestCase):

    def setUp(self):
        self.frame = make_frame_with_nametag()
        self.fake_ocr = FakeOcr(self.frame)

    def test_locate_body_with_offset(self):
        """名字牌中心 (≈1165,875),身体在其上方 90 → 身体中心 (≈1165,785)。"""
        body = locate_body(self.frame, 'Yufeng咕咕', offset=90, ocr_fn=self.fake_ocr.ocr)
        self.assertAlmostEqual(body[0], 1165, delta=1)
        self.assertAlmostEqual(body[1], 785, delta=1)

    def test_locate_body_miss_returns_none(self):
        body = locate_body(self.frame, '不存在的名字', ocr_fn=self.fake_ocr.ocr)
        self.assertIsNone(body)

    def test_draw_zone_right_facing(self):
        """朝 RIGHT:攻击框 x∈[cx, cx+距离],身体中心绿点。"""
        body = locate_body(self.frame, 'Yufeng咕咕', offset=90, ocr_fn=self.fake_ocr.ocr)
        out = draw_zone_png(self.frame, body, 'RIGHT', 120, 'tmp_zone.png', zone_h=200)
        img = cv2.imread(out)
        os.remove(out)
        self.assertIsNotNone(img)
        # 蓝框应出现在身体中心右侧(红通道=255 的框线像素)
        cx, cy = int(body[0]), int(body[1])
        right_side = img[cy - 100:cy + 100, cx + 1:cx + 121]
        self.assertTrue((right_side[:, :, 2] == 255).any(), 'RIGHT 朝向攻击框应在右侧')

    def test_draw_zone_left_facing(self):
        """朝 LEFT:攻击框 x∈[cx-距离, cx]。"""
        body = locate_body(self.frame, 'Yufeng咕咕', offset=90, ocr_fn=self.fake_ocr.ocr)
        out = draw_zone_png(self.frame, body, 'LEFT', 120, 'tmp_zone_left.png', zone_h=200)
        img = cv2.imread(out)
        os.remove(out)
        cx, cy = int(body[0]), int(body[1])
        left_side = img[cy - 100:cy + 100, cx - 121:cx - 1]
        self.assertTrue((left_side[:, :, 2] == 255).any(), 'LEFT 朝向攻击框应在左侧')

    def test_write_config_creates_and_updates(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'config.json')
            write_config(path, {'攻击距离': 140, '调试开关': True})
            with open(path, encoding='utf-8') as f:
                cfg = json.load(f)
            self.assertEqual(cfg['task_configs']['战士调试']['攻击距离'], 140)
            # 再次写入合并
            write_config(path, {'玩家宽': 80})
            with open(path, encoding='utf-8') as f:
                cfg = json.load(f)
            task_cfg = cfg['task_configs']['战士调试']
            self.assertEqual(task_cfg['攻击距离'], 140)
            self.assertEqual(task_cfg['玩家宽'], 80)


if __name__ == '__main__':
    unittest.main()
