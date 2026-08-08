import unittest

from src.detect import facing


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


if __name__ == '__main__':
    unittest.main()
