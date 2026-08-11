import os
import unittest

import cv2
import numpy as np

from src.detect import minimap


def make_base(h=94, w=122):
    """合成底图(BGRA):透明背景 + 两块棕色地形 + 一条灰绳。"""
    img = np.zeros((h, w, 4), np.uint8)
    img[80:90, 5:60] = (30, 80, 150, 255)   # BGR 棕 + 不透明
    img[40:46, 40:110] = (30, 80, 150, 255)
    img[46:80, 70:73] = (127, 127, 127, 255)
    return img


def make_panel(base, scale=2.0, offset=(7, 11), bg=(40, 30, 20), pad=60):
    """把底图按 scale 放大、贴到深色面板 offset 处,模拟游戏内小地图。"""
    h, w = base.shape[:2]
    big = cv2.resize(base, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    ph, pw = int(h * scale) + pad, int(w * scale) + pad
    panel = np.full((ph, pw, 3), bg, np.uint8)
    ox, oy = offset
    for y in range(big.shape[0]):
        for x in range(big.shape[1]):
            if big[y, x, 3] > 0:
                panel[oy + y, ox + x] = big[y, x, :3]
    return panel


class TestYellowDots(unittest.TestCase):

    def test_finds_two_dots_with_subpixel_centroid(self):
        panel = np.zeros((100, 100, 3), np.uint8)
        cv2.circle(panel, (20, 30), 2, (0, 255, 255), -1)   # BGR 黄
        cv2.circle(panel, (70, 60), 3, (0, 255, 255), -1)
        dots = minimap.find_yellow_dots(panel)
        self.assertEqual(len(dots), 2)
        cx, cy, area = min(dots)  # 最左那颗
        self.assertAlmostEqual(cx, 20, delta=1.0)
        self.assertAlmostEqual(cy, 30, delta=1.0)
        self.assertGreaterEqual(area, minimap.MIN_DOT_AREA)

    def test_rejects_oversize_yellow_blob_and_noise(self):
        panel = np.zeros((100, 100, 3), np.uint8)
        cv2.rectangle(panel, (10, 10), (50, 50), (0, 255, 255), -1)  # 大块黄=装饰
        panel[80, 80] = (0, 255, 255)                                # 单像素噪声
        self.assertEqual(minimap.find_yellow_dots(panel), [])


class TestTransform(unittest.TestCase):

    def test_roundtrip(self):
        meta = {'scale': 2.0, 'offset_x': 7.0, 'offset_y': 11.0}
        p = (50.0, 60.0)
        self.assertEqual(minimap.map_to_panel(minimap.panel_to_map(p, meta), meta), p)

    def test_panel_to_map_values(self):
        meta = {'scale': 2.0, 'offset_x': 7.0, 'offset_y': 11.0}
        self.assertEqual(minimap.panel_to_map((27.0, 31.0), meta), (10.0, 10.0))


class TestCalibrate(unittest.TestCase):

    def test_recovers_scale_and_offset(self):
        base = make_base()
        panel = make_panel(base, scale=2.0, offset=(7, 11))
        meta = minimap.calibrate(panel, base)
        self.assertIsNotNone(meta)
        self.assertAlmostEqual(meta['scale'], 2.0, delta=0.1)
        self.assertAlmostEqual(meta['offset_x'], 7.0, delta=2.0)
        self.assertAlmostEqual(meta['offset_y'], 11.0, delta=2.0)
        self.assertGreater(meta['match_score'], minimap.CALIBRATE_MIN_SCORE)

    def test_returns_none_on_garbage_panel(self):
        base = make_base()
        panel = np.full((200, 260, 3), (40, 30, 20), np.uint8)  # 纯背景
        self.assertIsNone(minimap.calibrate(panel, base))


class TestTerrainScore(unittest.TestCase):

    def test_same_terrain_scores_high_scrambled_low(self):
        base = make_base()
        panel = make_panel(base, scale=2.0, offset=(7, 11))
        meta = minimap.calibrate(panel, base)
        self.assertGreater(minimap.terrain_match_score(panel, base, meta), 0.6)
        blank = np.full_like(panel, (40, 30, 20))
        self.assertLess(minimap.terrain_match_score(blank, base, meta), minimap.TERRAIN_MIN_SCORE)


class TestMetaIO(unittest.TestCase):

    def test_save_and_load(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            meta = {'panel_roi': (10, 100, 270, 190), 'scale': 2.0,
                    'offset_x': 7.0, 'offset_y': 11.0, 'search_range': 8, 'match_score': 0.8}
            minimap.save_map_meta(d, meta)
            loaded = minimap.load_map_meta(d)
            self.assertEqual(loaded['scale'], 2.0)
            self.assertEqual(tuple(loaded['panel_roi']), (10, 100, 270, 190))
            self.assertEqual(loaded['search_range'], 8)

    def test_load_missing_returns_none(self):
        self.assertIsNone(minimap.load_map_meta('不存在的目录'))


class TestUnicodeIO(unittest.TestCase):
    """中文路径回归(预检铁证:cv2.imread/imwrite 在 Windows 非 ASCII 路径下失效,
    imread 静默返 None、imwrite 抛异常;沙箱合成测试全 ASCII 没覆盖到)。"""

    def test_write_then_read_base_map_in_chinese_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, '东部岩山5')
            os.makedirs(sub)
            img = make_base()
            minimap.imwrite_unicode(os.path.join(sub, '底图.png'), img)
            loaded = minimap.load_base_map(sub)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.shape, img.shape)

    def test_meta_roundtrip_in_chinese_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, '中文目录')
            os.makedirs(sub)
            meta = {'panel_roi': (10, 100, 270, 190), 'scale': 2.0,
                    'offset_x': 7.0, 'offset_y': 11.0, 'search_range': 8}
            minimap.save_map_meta(sub, meta)
            self.assertEqual(minimap.load_map_meta(sub)['scale'], 2.0)


class TestDotTracker(unittest.TestCase):

    def setUp(self):
        self.meta = {'scale': 1.0, 'offset_x': 0.0, 'offset_y': 0.0}

    def test_acquire_picks_the_moving_dot(self):
        before = [(10.0, 10.0, 8), (50.0, 50.0, 8)]   # 左=NPC 静止
        after = [(10.0, 10.0, 8), (58.0, 50.0, 8)]    # 右=自己动了 8px
        t = minimap.DotTracker()
        pos = t.acquire(before, after, self.meta)
        self.assertIsNotNone(pos)
        self.assertAlmostEqual(pos[0], 58.0, delta=0.5)

    def test_acquire_returns_none_when_nothing_moved(self):
        dots = [(10.0, 10.0, 8), (50.0, 50.0, 8)]
        t = minimap.DotTracker()
        self.assertIsNone(t.acquire(dots, dots, self.meta))

    def test_update_nearest_neighbor(self):
        t = minimap.DotTracker()
        t.pos = (50.0, 50.0)
        pos, status = t.update([(10.0, 10.0, 8), (52.0, 51.0, 8)], self.meta, 100.0)
        self.assertEqual(status, 'ok')
        self.assertAlmostEqual(pos[0], 52.0, delta=0.5)

    def test_jump_guard_rejects_far_jump_and_keeps_pos(self):
        t = minimap.DotTracker()  # dt=0 → 上限 = base 4 格
        t.pos = (50.0, 50.0)
        pos, status = t.update([(90.0, 50.0, 8)], self.meta, 100.0)  # 跳 40px=NPC 认错
        self.assertEqual(status, 'suspect')
        self.assertEqual(t.pos, (50.0, 50.0))  # 不采信

    def test_jump_guard_scales_with_dt(self):
        # 评审 3:固定 8 格在慢拍节奏下会误杀正常行走——上限必须随拍间隔自适应
        t = minimap.DotTracker()  # base 4 + 12 格/秒
        t.pos = (50.0, 50.0)
        _, s1 = t.update([(60.0, 50.0, 8)], self.meta, 100.0)  # dt=0 → 上限 4,10px 拒采
        self.assertEqual(s1, 'suspect')
        _, s2 = t.update([(60.0, 50.0, 8)], self.meta, 101.0)  # dt=1s → 上限 16,10px 放行
        self.assertEqual(s2, 'ok')

    def test_lost_when_no_dots(self):
        t = minimap.DotTracker()
        t.pos = (50.0, 50.0)
        pos, status = t.update([], self.meta, 100.0)
        self.assertEqual(status, 'lost')
        self.assertIsNone(pos)

    def test_mismatch_when_cmd_held_but_no_movement(self):
        t = minimap.DotTracker(cmd_mismatch_limit=3.0)
        t.pos = (50.0, 50.0)
        _, s1 = t.update([(50.0, 50.0, 8)], self.meta, 100.0, cmd_dir='right')
        _, s2 = t.update([(50.3, 50.0, 8)], self.meta, 103.5, cmd_dir='right')
        self.assertEqual(s1, 'ok')
        self.assertEqual(s2, 'mismatch')  # 按右 3.5s 只动了 0.3px

    def test_no_mismatch_when_moving_with_cmd(self):
        t = minimap.DotTracker(cmd_mismatch_limit=3.0)
        t.pos = (50.0, 50.0)
        t.update([(50.0, 50.0, 8)], self.meta, 100.0, cmd_dir='right')
        _, status = t.update([(62.0, 50.0, 8)], self.meta, 103.5, cmd_dir='right')
        self.assertEqual(status, 'ok')

    def test_acquire_sets_last_update_then_first_update_ok(self):
        # 评审 #1:acquire 播种须设 _last_update_t,否则首拍 dt=0 → 跳变上限仅 base 4px,
        # 人还在走 → 永久 suspect 楔死。播种后 dt=0.5 → 上限 10px,6px 位移放行。
        before = [(10.0, 10.0, 8)]
        after = [(16.0, 10.0, 8)]   # 走了 6px
        t = minimap.DotTracker()
        self.assertIsNotNone(t.acquire(before, after, self.meta, now=100.0))
        pos, status = t.update([(22.0, 10.0, 8)], self.meta, 100.5)  # 又走 6px
        self.assertEqual(status, 'ok')
        self.assertAlmostEqual(pos[0], 22.0, delta=0.5)

    def test_direction_change_resets_anchor(self):
        # 评审 #6:折返换向不清算旧方向位移——right 3s 无位移 mismatch 后切 left 重新计时
        t = minimap.DotTracker(cmd_mismatch_limit=3.0)
        t.pos = (50.0, 50.0)
        _, s1 = t.update([(50.0, 50.0, 8)], self.meta, 100.0, cmd_dir='right')
        _, s2 = t.update([(50.3, 50.0, 8)], self.meta, 103.5, cmd_dir='right')
        self.assertEqual(s2, 'mismatch')           # right 3.5s 只动 0.3px
        _, s3 = t.update([(50.3, 50.0, 8)], self.meta, 104.0, cmd_dir='left')   # 换向第一拍
        self.assertEqual(s3, 'ok')                 # 换向即重置锚点,不误报
        _, s4 = t.update([(50.3, 50.0, 8)], self.meta, 107.5, cmd_dir='left')   # left 3.5s 未动
        self.assertEqual(s4, 'mismatch')           # 新方向自己的窗口照常判


if __name__ == '__main__':
    unittest.main()
