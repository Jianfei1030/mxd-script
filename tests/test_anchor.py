import unittest

import numpy as np

from src.detect import anchor

NAME = 'Yufeng咕咕'


def fake_ocr(texts_per_call):
    """按调用次序依次返回各次的文本列表。每个文本给一个固定的局部框 (10,20)-(140,55)。"""
    calls = {'n': 0}

    def _fn(image):
        i = calls['n']
        calls['n'] += 1
        texts = texts_per_call[i] if i < len(texts_per_call) else []
        return [[[[[10.0, 20.0], [140.0, 20.0], [140.0, 55.0], [10.0, 55.0]], (t, 0.99)]
                 for t in texts]]

    _fn.calls = calls
    return _fn


class TestSearchRegion(unittest.TestCase):

    def test_matches_measured_baseline_region(self):
        """默认区域必须与 spec §3.1 的实测基线是同一块:x 0.35-0.65、y 0.40-0.70。
        名字牌画在角色脚下,而相机对准的是身体,所以牌子系统性地在画面中心偏下
        (实测 y 738-888,中心 813 > 720)—— 搜索区中心因此取 0.55h 而不是 0.5h。"""
        self.assertEqual(anchor.search_region(2560, 1440, 0.30, 0.30), (896, 576, 1664, 1008))

    def test_covers_measured_anchor_range(self):
        """实测 40 帧的名字牌 y ∈ [738, 888]、x ∈ [1073, 1468],必须全落在区内。"""
        x0, y0, x1, y1 = anchor.search_region(2560, 1440, 0.30, 0.30)
        self.assertTrue(x0 <= 1073 and 1468 <= x1)
        self.assertTrue(y0 <= 738 and 888 <= y1)

    def test_excludes_known_decoys(self):
        """右侧组队列表(x≈2303,y≈1032)与左下状态栏(x≈732,y≈1421)都写着同一个角色名,
        必须落在搜索区外,否则锚点会跳到 HUD 上。"""
        x0, y0, x1, y1 = anchor.search_region(2560, 1440, 0.30, 0.30)
        self.assertFalse(x0 <= 2303 <= x1 and y0 <= 1032 <= y1)
        self.assertFalse(x0 <= 732 <= x1 and y0 <= 1421 <= y1)


class TestTiles(unittest.TestCase):

    def test_overlap_exceeds_name_tag_width(self):
        """名字牌实测宽约 130px。相邻块重叠必须大于它,否则牌子骑边界会被两侧切断
        (实测:重叠 60px 时 40 帧里漏检 9 帧)。"""
        got = anchor.tiles((0, 0, 2000, 240))
        self.assertGreater(len(got), 1)
        overlap = got[0][2] - got[1][0]
        self.assertGreaterEqual(overlap, 130)

    def test_covers_region_edges(self):
        got = anchor.tiles((896, 576, 1664, 1008))
        self.assertEqual(min(t[0] for t in got), 896)
        self.assertEqual(max(t[2] for t in got), 1664)
        self.assertEqual(min(t[1] for t in got), 576)
        self.assertEqual(max(t[3] for t in got), 1008)

    def test_terminates_when_overlap_ge_tile(self):
        """重叠 >= 块宽会让步长变成 0,必须有下限保护,不能死循环。"""
        got = anchor.tiles((0, 0, 1000, 100), tile_w=200, tile_h=100, overlap=500)
        self.assertLess(len(got), 2000)


class TestFindInWindow(unittest.TestCase):

    def setUp(self):
        self.frame = np.zeros((1440, 2560, 3), np.uint8)

    def test_translates_to_frame_coordinates(self):
        fn = fake_ocr([[NAME]])
        got = anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn)
        # 窗口原点 (1300-240, 880-80) = (1060, 800);局部框中心 (75, 37.5)
        self.assertEqual((got.x, got.y), (1135.0, 837.5))
        self.assertEqual(got.width, 130)

    def test_rejects_merged_text(self):
        """与邻牌粘连(实测 '小白雪人ifeng咕咕' 宽 212px)会把锚点带偏 100-200px,必须丢弃。"""
        fn = fake_ocr([['小白雪人ifeng咕咕']])
        self.assertIsNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_rejects_truncated_text(self):
        """被宠物牌遮挡后只剩尾巴(实测 'ng咕咕'),中心右偏,同样丢弃。"""
        fn = fake_ocr([['ng咕咕']])
        self.assertIsNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_ignores_surrounding_whitespace(self):
        fn = fake_ocr([['  ' + NAME + ' ']])
        self.assertIsNotNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_clamps_window_to_frame(self):
        """角色贴边时窗口会越界,裁剪不许产生空图或负坐标。"""
        fn = fake_ocr([[NAME]])
        got = anchor.find_in_window(self.frame, NAME, (30, 20), 240, 80, ocr_fn=fn)
        self.assertIsNotNone(got)


class TestFindInRegion(unittest.TestCase):

    def setUp(self):
        self.frame = np.zeros((1440, 2560, 3), np.uint8)
        self.region = (896, 576, 1664, 1008)

    def test_returns_first_match_with_global_coordinates(self):
        """第 3 块才命中,坐标必须按第 3 块的原点平移。"""
        boxes = anchor.tiles(self.region)
        self.assertGreaterEqual(len(boxes), 3)
        fn = fake_ocr([[], [], [NAME]])
        got = anchor.find_in_region(self.frame, NAME, self.region, ocr_fn=fn)
        x0, y0 = boxes[2][0], boxes[2][1]
        self.assertEqual((got.x, got.y), (x0 + 75.0, y0 + 37.5))

    def test_returns_none_when_absent(self):
        fn = fake_ocr([])
        self.assertIsNone(anchor.find_in_region(self.frame, NAME, self.region, ocr_fn=fn))


class TestBodyCenter(unittest.TestCase):

    def test_moves_up_from_name_tag(self):
        """名字牌画在角色脚下,身体在它上方(y 更小)。"""
        got = anchor.body_center(anchor.Anchor(1300.0, 880.0, 128), 90)
        self.assertEqual(got, (1300.0, 790.0))


if __name__ == '__main__':
    unittest.main()
