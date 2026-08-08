import unittest

import numpy as np

from src.detect import anchor, facing


class TestFacingDecide(unittest.TestCase):
    """判据照抄 2026-08-07 附录 A:max(s,s_flip) >= 0.70 且 |s-s_flip| >= 0.20。

    不测阈值的精确边界:0.70/0.20 在 IEEE754 下的边界断言会随字面量写法漂移
    (2026-08-07 spec §7.1 已经在 hp_drop 上踩过同样的坑)。只测明确在两侧的值。
    """

    def test_same_direction_as_template(self):
        # 附录 A 的典型命中:胜出分 0.88、差值 0.41
        self.assertEqual(facing.decide(0.88, 0.47, 'RIGHT'), 'RIGHT')
        self.assertEqual(facing.decide(0.88, 0.47, 'LEFT'), 'LEFT')

    def test_opposite_direction_to_template(self):
        self.assertEqual(facing.decide(0.47, 0.88, 'RIGHT'), 'LEFT')
        self.assertEqual(facing.decide(0.47, 0.88, 'LEFT'), 'RIGHT')

    def test_abstain_when_score_too_low(self):
        """两边都不像:宠物挡住/切边。附录 A 的 4 个弃权帧就长这样(最高 0.45)。"""
        self.assertIsNone(facing.decide(0.45, 0.40, 'RIGHT'))

    def test_abstain_when_margin_too_small(self):
        """分高但两边差不多:分不出朝向,宁可不答也不答错。"""
        self.assertIsNone(facing.decide(0.85, 0.80, 'RIGHT'))

    def test_abstain_on_bad_template_facing(self):
        """模板朝向未知/非法 → 弃权,不猜。"""
        self.assertIsNone(facing.decide(0.88, 0.47, None))
        self.assertIsNone(facing.decide(0.88, 0.47, 'UP'))


class TestFacingRoi(unittest.TestCase):

    def _frame(self, h=1440, w=2560):
        return np.zeros((h, w, 3), dtype=np.uint8)

    def test_roi_box_geometry(self):
        """照抄附录 A.1:x ±90,y 从 a.y-160 到 a.y-20,共 180x140。"""
        a = anchor.Anchor(1280.0, 880.0, 130)
        box = facing.roi_box(self._frame().shape, a)
        self.assertEqual(box, (1190, 720, 1370, 860))
        x0, y0, x1, y1 = box
        self.assertEqual((x1 - x0, y1 - y0), (180, 140))

    def test_roi_box_none_when_clipped_at_edge(self):
        """角色贴屏幕边缘 → ROI 会被切,宁可不观测也不要半张脸(附录 A 的 #0
        就是切边弃权)。返回 None,不抛。"""
        self.assertIsNone(facing.roi_box(self._frame().shape,
                                         anchor.Anchor(20.0, 880.0, 130)))
        self.assertIsNone(facing.roi_box(self._frame().shape,
                                         anchor.Anchor(1280.0, 100.0, 130)))

    def test_crop_roi_returns_grayscale(self):
        a = anchor.Anchor(1280.0, 880.0, 130)
        roi = facing.crop_roi(self._frame(), a)
        self.assertEqual(roi.shape, (140, 180))   # 灰度,无通道维

    def test_scores_detects_mirror(self):
        """构造一个左右不对称的图案:原图应当明显赢过镜像。"""
        roi = np.zeros((140, 180), dtype=np.uint8)
        roi[40:100, 60:70] = 255      # 竖条偏左
        roi[40:50, 60:120] = 255      # 顶部横条向右伸 = 左右不对称
        tmpl = roi[35:105, 55:125].copy()
        s, s_flip = facing.scores(roi, tmpl)
        self.assertGreater(s, 0.9)
        self.assertGreater(s - s_flip, facing.FACING_MARGIN_MIN)

    def test_observe_end_to_end(self):
        roi_src = np.zeros((1440, 2560, 3), dtype=np.uint8)
        a = anchor.Anchor(1280.0, 880.0, 130)
        # 在 ROI 位置画同一个不对称图案
        roi_src[760:820, 1250:1260] = 255
        roi_src[760:770, 1250:1310] = 255
        tmpl = facing.crop_roi(roi_src, a)[35:105, 55:125].copy()
        got, s, s_flip = facing.observe(roi_src, a, tmpl, 'RIGHT')
        self.assertEqual(got, 'RIGHT')
        self.assertGreater(s, s_flip)

    def test_observe_abstains_without_template(self):
        a = anchor.Anchor(1280.0, 880.0, 130)
        self.assertEqual(facing.observe(self._frame(), a, None, 'RIGHT'),
                         (None, 0.0, 0.0))

    def test_observe_abstains_at_edge(self):
        a = anchor.Anchor(20.0, 880.0, 130)
        tmpl = np.zeros((70, 70), dtype=np.uint8)
        self.assertEqual(facing.observe(self._frame(), a, tmpl, 'RIGHT'),
                         (None, 0.0, 0.0))

    def test_observe_abstains_when_template_larger_than_roi(self):
        """模板比 ROI 大 → matchTemplate 会抛,必须提前挡住。"""
        a = anchor.Anchor(1280.0, 880.0, 130)
        tmpl = np.zeros((200, 200), dtype=np.uint8)
        self.assertEqual(facing.observe(self._frame(), a, tmpl, 'RIGHT'),
                         (None, 0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
