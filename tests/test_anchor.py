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

    def test_accepts_truncated_suffix(self):
        """被宠物牌遮挡后只剩尾巴(实测 'ng咕咕'),长度过半,当作近似锚点收下——
        中心会右偏,但战斗中"有个大概位置"好过连续遮挡 10s+ 后整个退化到画面中心。"""
        fn = fake_ocr([['ng咕咕']])
        self.assertIsNotNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_rejects_too_short_suffix(self):
        """尾巴太短(如只剩 '咕咕' 2 字)信息量不够,容易撞上别的同尾缀玩家,丢弃。"""
        fn = fake_ocr([['咕咕']])
        self.assertIsNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_ignores_surrounding_whitespace(self):
        fn = fake_ocr([['  ' + NAME + ' ']])
        self.assertIsNotNone(anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80, ocr_fn=fn))

    def test_clamps_window_to_frame(self):
        """角色贴边时窗口会越界,裁剪不许产生空图或负坐标。"""
        fn = fake_ocr([[NAME]])
        got = anchor.find_in_window(self.frame, NAME, (30, 20), 240, 80, ocr_fn=fn)
        self.assertIsNotNone(got)

    def test_clamps_window_to_region(self):
        """快通道窗口超出蓝框(锚点搜索区)的部分必须被裁掉:窗口本为
        (1060,800)-(1540,960),蓝框 (1200,850)-(1400,950) 裁后
        局部框中心 (75, 37.5) 平移到 (1275, 887.5)。"""
        fn = fake_ocr([[NAME]])
        got = anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80,
                                    ocr_fn=fn, clamp_region=(1200, 850, 1400, 960))
        self.assertEqual((got.x, got.y), (1275.0, 887.5))

    def test_no_intersection_with_region_returns_none(self):
        """蓝框与窗口完全不相交(角色已跑出搜索区)→ 不快扫,直接无命中。"""
        fn = fake_ocr([[NAME]])
        got = anchor.find_in_window(self.frame, NAME, (1300, 880), 240, 80,
                                    ocr_fn=fn, clamp_region=(2000, 1000, 2560, 1200))
        self.assertIsNone(got)


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


class TestEnhanceForOcr(unittest.TestCase):

    def test_white_text_becomes_black_on_light(self):
        """白字黑描边 → 反转后应是黑字浅底,贴合 DB 训练分布。
        黑底上的白字(255):反转后字变黑(≈0)、底变白(≈255)。"""
        img = np.zeros((40, 200, 3), np.uint8)      # 黑底
        img[10:30, 20:60] = 255                      # 白字块
        out = anchor._enhance_for_ocr(img)
        self.assertEqual(out.shape, img.shape)       # 尺寸不变,坐标可换算
        self.assertLess(out[20, 40].mean(), 30)      # 原白字位置 → 变黑
        self.assertGreater(out[5, 5].mean(), 200)    # 原黑底位置 → 变浅

    def test_preserves_dimensions_for_coordinate_mapping(self):
        """任意尺寸输入,输出形状必须一致(OCR 命中框坐标依赖这点)。"""
        for h, w in [(240, 640), (80, 480), (1, 1)]:
            out = anchor._enhance_for_ocr(np.zeros((h, w, 3), np.uint8))
            self.assertEqual(out.shape, (h, w, 3))

    def test_disabled_flag_skips_preprocess(self):
        """开关关闭时 _scan 原样送图:构造一个会被增强改变的帧,关闭后 OCR 收到的
        应与原始一致(通过 fake_ocr 捕获入参验证)。"""
        frame = np.zeros((1440, 2560, 3), np.uint8)
        frame[880:910, 1200:1300] = 255              # 白字块
        seen = {}
        original = anchor.OCR_PREPROCESS_ENABLED
        try:
            anchor.OCR_PREPROCESS_ENABLED = False
            def capture(image):
                seen['crop'] = image.copy()
                return [[[[[10.0, 20.0], [140.0, 20.0], [140.0, 55.0], [10.0, 55.0]], (NAME, 0.99)]]]
            anchor.find_in_window(frame, NAME, (1300, 880), 240, 80, ocr_fn=capture)
            # 快通道窗口 (1060, 800)-(1540, 960):白字块应在窗口内
            crop = seen['crop']
            self.assertEqual(crop.shape[:2], (160, 480))
            self.assertGreater(crop[880 - 800 + 10, 1200 - 1060 + 10].mean(), 200)
        finally:
            anchor.OCR_PREPROCESS_ENABLED = original

    def test_enabled_flag_applies_preprocess(self):
        """开关打开时 _scan 送增强后的图:白字位置应反转为黑(与开关关闭对比)。"""
        frame = np.zeros((1440, 2560, 3), np.uint8)
        frame[880:910, 1200:1300] = 255
        seen = {}
        original = anchor.OCR_PREPROCESS_ENABLED
        try:
            anchor.OCR_PREPROCESS_ENABLED = True
            def capture(image):
                seen['crop'] = image.copy()
                return [[[[[10.0, 20.0], [140.0, 20.0], [140.0, 55.0], [10.0, 55.0]], (NAME, 0.99)]]]
            anchor.find_in_window(frame, NAME, (1300, 880), 240, 80, ocr_fn=capture)
            crop = seen['crop']
            self.assertLess(crop[880 - 800 + 10, 1200 - 1060 + 10].mean(), 30)
        finally:
            anchor.OCR_PREPROCESS_ENABLED = original


class TestHasDarkBackground(unittest.TestCase):
    """模板匹配命中后验证暗底:名字牌有暗色半透明底框(暗底 ~40%),
    云/天空是纯亮色(无暗底)。此验证把误中的云/天空拒绝掉。"""

    def test_nameplate_with_dark_bg_passes(self):
        """命中点周围大片暗底(模拟名字牌暗色底框)→ 通过。"""
        frame = np.zeros((1440, 2560, 3), np.uint8)     # 全黑帧
        hit = anchor.AnchorHit(1280.0, 880.0, 130, '')
        self.assertTrue(anchor.has_dark_background(frame, hit))

    def test_bright_sky_without_dark_bg_rejected(self):
        """命中点周围纯亮(模拟云/天空)→ 拒绝。"""
        frame = np.full((1440, 2560, 3), 255, np.uint8)  # 全白帧
        hit = anchor.AnchorHit(1280.0, 880.0, 130, '')
        self.assertFalse(anchor.has_dark_background(frame, hit))

    def test_mixed_bg_below_ratio_rejected(self):
        """暗底占比低于阈值(30%)→ 拒绝。验证区域 240x70=16800 像素,
        只涂 20% 暗底,应低于 DARK_BG_MIN_RATIO。"""
        frame = np.full((1440, 2560, 3), 255, np.uint8)
        # 在命中点周围涂一小块暗色(仅约 20% 面积)
        for y in range(870, 885):
            for x in range(1240, 1280):
                frame[y, x] = 0
        hit = anchor.AnchorHit(1280.0, 880.0, 130, '')
        self.assertFalse(anchor.has_dark_background(frame, hit))

    def test_hit_near_edge_clamps_roi_without_error(self):
        """命中点贴边:ROI 被裁到帧内仍非空,不抛异常,按帧内内容判断。"""
        frame = np.zeros((1440, 2560, 3), np.uint8)
        hit = anchor.AnchorHit(10.0, 880.0, 130, '')  # 贴近左边界
        self.assertTrue(anchor.has_dark_background(frame, hit))


class TestSplitMatchVerifyDark(unittest.TestCase):
    """split_match(verify_dark=True):命中后验证暗底,云/天空误匹配被拒绝。"""

    def _make_template(self, text_w=120, text_h=24):
        """白字二值化模板:黑底上的白色横条,宽 120 高 24。"""
        tmpl = np.zeros((text_h + 8, text_w + 8), np.uint8)
        tmpl[4:4 + text_h, 4:4 + text_w] = 255
        return tmpl

    def test_match_on_dark_bg_passes_verification(self):
        """模板在暗底区域命中 → verify_dark=True 仍返回命中。"""
        frame = np.zeros((1440, 2560, 3), np.uint8)     # 全黑帧(名字牌暗底)
        frame[850:880, 1210:1340] = 255                  # 白字条(模板内容)
        tmpl = self._make_template()
        hit = anchor.split_match(frame, tmpl, (1280, 880), 240, 80, 0.3,
                                 verify_dark=True)
        self.assertIsNotNone(hit)

    def test_match_on_bright_bg_rejected_by_verification(self):
        """模板在纯亮背景命中(模拟云/天空)→ verify_dark=True 拒绝。"""
        frame = np.full((1440, 2560, 3), 255, np.uint8)  # 全白帧(云/天空)
        tmpl = self._make_template()
        # 白字模板在全白帧上也能匹配(白对白差 0),但暗底验证必须拒绝
        hit = anchor.split_match(frame, tmpl, (1280, 880), 240, 80, 0.3,
                                 verify_dark=True)
        self.assertIsNone(hit)

    def test_verify_dark_false_keeps_old_behavior(self):
        """verify_dark=False(旧行为):纯亮背景上的匹配不被拒绝。"""
        frame = np.full((1440, 2560, 3), 255, np.uint8)
        tmpl = self._make_template()
        hit = anchor.split_match(frame, tmpl, (1280, 880), 240, 80, 0.3,
                                 verify_dark=False)
        self.assertIsNotNone(hit)

    def test_clamps_window_to_region(self):
        """模板匹配窗口超出蓝框的部分必须被裁掉。窗口本为 (1040,800)-(1520,960),
        蓝框 (1100,830)-(1340,900) 裁后从 (1100,830) 起检 —— 白字条在 1210:1340,
        仍在裁后窗口内,命中坐标按裁后窗口原点换算(≈1270x,884y)。"""
        frame = np.zeros((1440, 2560, 3), np.uint8)
        frame[850:880, 1210:1340] = 255
        tmpl = self._make_template()
        hit = anchor.split_match(frame, tmpl, (1280, 880), 240, 80, 0.3,
                                 clamp_region=(1100, 830, 1340, 900))
        self.assertIsNotNone(hit)
        self.assertGreaterEqual(hit.x, 1100)
        self.assertLessEqual(hit.x, 1340)
        self.assertGreaterEqual(hit.y, 830)
        self.assertLessEqual(hit.y, 900)

    def test_no_intersection_with_region_returns_none(self):
        """蓝框与窗口完全不相交 → 无命中(不越界找)。"""
        frame = np.zeros((1440, 2560, 3), np.uint8)
        frame[850:880, 1210:1340] = 255
        tmpl = self._make_template()
        hit = anchor.split_match(frame, tmpl, (1280, 880), 240, 80, 0.3,
                                 clamp_region=(1800, 1000, 2200, 1200))
        self.assertIsNone(hit)


class TestMatchesPrefixSuffix(unittest.TestCase):
    """_matches 遮挡匹配:宠物/怪可挡名字任意侧,OCR 可能只读出部分文本。

    2026-08-10 视觉模型验收确认:白色雪人宠物挡名字右侧 → OCR 读前缀
    ('端侧大'/'端侧'),旧实现只认后缀导致 58% 通过率。新实现前缀/后缀/
    粘连任一匹配即收。
    """

    def setUp(self):
        self.target = '端侧大模型'

    def test_exact(self):
        self.assertTrue(anchor._matches('端侧大模型', self.target))

    def test_prefix_full(self):
        """宠物挡右侧 2-3 字,OCR 读前缀。"""
        self.assertTrue(anchor._matches('端侧大', self.target))
        self.assertTrue(anchor._matches('端侧', self.target))

    def test_suffix_full(self):
        """怪/邻牌挡前半,OCR 读尾巴。"""
        self.assertTrue(anchor._matches('大模型', self.target))
        self.assertTrue(anchor._matches('模型', self.target))

    def test_glued_suffix(self):
        """名字牌与 CV 标签粘连,OCR 读 '端侧大模型CV'(text 以 target 开头)。"""
        self.assertTrue(anchor._matches('端侧大模型CV', self.target))

    def test_glued_prefix(self):
        """CV 标签在前,OCR 读 'CV端侧大模型'(text 以 target 结尾)。"""
        self.assertTrue(anchor._matches('CV端侧大模型', self.target))

    def test_too_short_rejected(self):
        """被挡得只剩 1 字,信息量不够,丢弃。"""
        self.assertFalse(anchor._matches('端', self.target))
        self.assertFalse(anchor._matches('型', self.target))

    def test_unrelated_glue_rejected(self):
        """完全无关的粘连(邻玩家牌子),与 target 无公共前后缀,排除。"""
        self.assertFalse(anchor._matches('小白雪人ifeng咕咕', self.target))
        self.assertFalse(anchor._matches('等级1端侧CV', self.target))


if __name__ == '__main__':
    unittest.main()
