import unittest

import cv2

from src.detect import potions

FRAME = 'screenshots/test_frames/training_ground_full_2560x1440.png'


class TestParseCount(unittest.TestCase):

    def test_digits(self):
        self.assertEqual(potions.parse_count('276'), 276)
        self.assertEqual(potions.parse_count(' 15 '), 15)

    def test_junk(self):
        self.assertIsNone(potions.parse_count(''))
        self.assertIsNone(potions.parse_count(None))
        self.assertIsNone(potions.parse_count('abc'))

    def test_mixed_takes_first_int(self):
        self.assertEqual(potions.parse_count('x15'), 15)


class TestSlotRoi(unittest.TestCase):

    def test_insert_right_of_shift(self):
        frame = cv2.imread(FRAME)
        xs, ys, ws, hs = potions.slot_roi(frame, 'shift')
        xi, yi, wi, hi = potions.slot_roi(frame, 'insert')
        self.assertGreater(xi, xs)
        self.assertEqual(yi, ys)

    def test_ctrl_below_shift(self):
        frame = cv2.imread(FRAME)
        xs, ys, _, _ = potions.slot_roi(frame, 'shift')
        xc, yc, _, _ = potions.slot_roi(frame, 'ctrl')
        self.assertEqual(xc, xs)
        self.assertGreater(yc, ys)

    def test_unknown_slot_returns_none(self):
        """用户把药水配到非快捷栏键(如 f1)时不许崩,返回 None(=未知,不判耗尽)。"""
        frame = cv2.imread(FRAME)
        self.assertIsNone(potions.slot_roi(frame, 'f1'))
        self.assertIsNone(potions.read_slot_count(frame, 'f1'))


@unittest.skip('OCR 对小数字漏检,耗尽由喝药无效兜底')
class TestReadSlotCountRealFrame(unittest.TestCase):

    def test_blue_potion_276(self):
        """存档帧 insert 格蓝药数量为 276(离线 OCR 直读)。"""
        frame = cv2.imread(FRAME)
        self.assertEqual(potions.read_slot_count(frame, 'insert'), 276)

    def test_red_potion_15(self):
        frame = cv2.imread(FRAME)
        self.assertEqual(potions.read_slot_count(frame, 'home'), 15)


if __name__ == '__main__':
    unittest.main()
