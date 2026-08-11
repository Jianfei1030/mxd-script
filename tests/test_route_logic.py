import os
import tempfile
import unittest

import cv2
import numpy as np

from src.task import route_logic as rl


class TestColorTable(unittest.TestCase):

    def test_ten_colors_and_reverse_mapping(self):
        self.assertEqual(len(rl.COLOR_COMMANDS), 10)
        self.assertEqual(rl.COLOR_COMMANDS[(255, 0, 0)], 'left none none')
        self.assertEqual(rl.COLOR_COMMANDS[(255, 255, 0)], 'none none goal')
        self.assertEqual(rl.COMMAND_COLORS['none up none'], (127, 127, 127))


class TestLoadRoutes(unittest.TestCase):

    def _write_route(self, path, pixels):
        img = np.zeros((94, 122, 4), np.uint8)
        for (x, y, rgb) in pixels:
            img[y, x] = (rgb[2], rgb[1], rgb[0], 255)
        cv2.imwrite(path, img)

    def test_loads_segments_in_order_and_reports_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_route(os.path.join(d, 'route1.png'),
                              [(5, 5, (255, 0, 0)), (6, 5, (255, 0, 0))])
            self._write_route(os.path.join(d, 'route2.png'),
                              [(9, 9, (255, 255, 0)), (3, 3, (1, 2, 3))])  # 1,2,3=涂错
            segments, unknown = rl.load_routes(d)
            self.assertEqual(len(segments), 2)
            self.assertEqual(segments[0][(5, 5)], 'left none none')
            self.assertEqual(segments[1][(9, 9)], 'none none goal')
            self.assertEqual(len(unknown), 1)
            self.assertEqual(unknown[0][2], (1, 2, 3))

    def test_missing_dir_returns_empty(self):
        self.assertEqual(rl.load_routes('不存在的目录'), ([], []))


class TestNearestCommand(unittest.TestCase):

    def setUp(self):
        self.seg = {(10, 10): 'left none none', (20, 20): 'none up none', (90, 90): 'none none goal'}

    def test_picks_manhattan_nearest(self):
        hit = rl.nearest_command(self.seg, (12, 11), search_range=8)
        self.assertEqual(hit['command'], 'left none none')
        self.assertEqual(hit['pixel'], (10, 10))
        self.assertEqual(hit['distance'], 3)

    def test_out_of_range_returns_none(self):
        self.assertIsNone(rl.nearest_command(self.seg, (50, 50), search_range=8))

    def test_boundary_is_inclusive(self):
        hit = rl.nearest_command(self.seg, (18, 20), search_range=8)
        self.assertEqual(hit['command'], 'none up none')


class TestAdvanceSegment(unittest.TestCase):

    def test_goal_cycles(self):
        self.assertEqual(rl.advance_segment(0, 2, 'none none goal'), 1)
        self.assertEqual(rl.advance_segment(1, 2, 'none none goal'), 0)

    def test_non_goal_keeps(self):
        self.assertEqual(rl.advance_segment(1, 2, 'left none none'), 1)


if __name__ == '__main__':
    unittest.main()
