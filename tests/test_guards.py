import unittest

import numpy as np

from src.detect import guards


class TestGuards(unittest.TestCase):

    def test_identical_frames_frozen(self):
        img = np.random.randint(0, 255, (360, 640, 3), dtype=np.uint8)
        sig = guards.signature(img)
        self.assertTrue(guards.frame_frozen(sig, sig))

    def test_different_frames_not_frozen(self):
        a = np.zeros((360, 640, 3), dtype=np.uint8)
        b = np.full((360, 640, 3), 255, dtype=np.uint8)
        self.assertFalse(guards.frame_frozen(guards.signature(a), guards.signature(b)))

    def test_small_change_still_frozen(self):
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        img2 = img.copy()
        img2[0:2, 0:2] = 30  # 微小扰动
        self.assertTrue(guards.frame_frozen(guards.signature(img), guards.signature(img2)))


if __name__ == '__main__':
    unittest.main()
