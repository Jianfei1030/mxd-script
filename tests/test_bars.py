import unittest

import cv2
import numpy as np

from src.detect import bars

FRAME = 'screenshots/test_frames/training_ground_full_2560x1440.png'


def make_bar(fill, w=200, h=26, color=(0, 0, 220)):
    img = np.full((h, w, 3), (20, 20, 20), np.uint8)
    if fill > 0:
        img[:, :max(1, int(w * fill))] = color
    return img


class TestBarsSynthetic(unittest.TestCase):
    FULL = (0.0, 0.0, 1.0, 1.0)

    def test_full(self):
        self.assertAlmostEqual(bars.read_bar_percent(make_bar(1.0), self.FULL, bars.RED), 1.0, delta=0.03)

    def test_half(self):
        self.assertAlmostEqual(bars.read_bar_percent(make_bar(0.5), self.FULL, bars.RED), 0.5, delta=0.03)

    def test_empty(self):
        self.assertAlmostEqual(bars.read_bar_percent(make_bar(0.0), self.FULL, bars.RED), 0.0, delta=0.03)


class TestBarsRealFrame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = cv2.imread(FRAME)
        assert cls.frame is not None, f'存档帧缺失: {FRAME}'

    def test_hp_full(self):
        self.assertGreaterEqual(bars.read_hp(self.frame), 0.95)

    def test_mp_full(self):
        self.assertGreaterEqual(bars.read_mp(self.frame), 0.95)

    def test_exp(self):
        self.assertAlmostEqual(bars.read_exp(self.frame), 0.706, delta=0.05)


if __name__ == '__main__':
    unittest.main()
