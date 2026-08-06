"""名字牌锚点的真机回归。数据源 dataset/images/train 未入库,缺失则 skip。

判据来自 spec §7.2,基线为 2026-08-06 实测(40 帧):
干净锚点 22/40、y ∈ [738, 888]、扫描中位 118ms / 最大 235ms。
"""
import glob
import os
import time
import unittest

import cv2

from src.detect import anchor, ocr_engine

DATASET = os.path.join('dataset', 'images', 'train')
NAME = os.environ.get('OK_MXD_CHAR_NAME', 'Yufeng咕咕')
FRAME_COUNT = 40


def frame_files():
    return sorted(glob.glob(os.path.join(DATASET, '*.png')))[:FRAME_COUNT]


@unittest.skipUnless(len(frame_files()) >= FRAME_COUNT,
                     f'需要 {FRAME_COUNT} 张 {DATASET} 帧(未入库)')
class TestAnchorOnRealFrames(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # 模型惰性加载是秒级的,不先预热的话第一帧的计时会把加载算进去,判据 D 必挂
        ocr_engine.prewarm()
        cls.results = []
        for path in frame_files():
            frame = cv2.imread(path)
            h, w = frame.shape[:2]
            region = anchor.search_region(w, h, 0.30, 0.30)
            start = time.time()
            hit = anchor.find_in_region(frame, NAME, region)
            cls.results.append((os.path.basename(path), hit, (time.time() - start) * 1000))

    def test_a_clean_hit_rate(self):
        """判据 A:干净锚点命中 >= 20/40(实测基线 22/40)。"""
        hits = [r for r in self.results if r[1] is not None]
        self.assertGreaterEqual(len(hits), 20, f'只命中 {len(hits)}/{len(self.results)}')

    def test_b_anchor_y_in_expected_band(self):
        """判据 B:命中帧的锚点 y 全部落在 [700, 950](实测 738-888)。"""
        for name, hit, _ in self.results:
            if hit is not None:
                self.assertTrue(700 <= hit.y <= 950, f'{name} 锚点 y={hit.y} 越界')

    def test_c_no_merged_boxes(self):
        """判据 C:不许返回粘连框(宽 > 160px)。干净名字牌实测 120-130px。"""
        for name, hit, _ in self.results:
            if hit is not None:
                self.assertLessEqual(hit.width, 160, f'{name} 框宽 {hit.width} 像粘连')

    def test_d_scan_latency(self):
        """判据 D:单帧扫描 <= 400ms(实测中位 118、最大 235)。"""
        worst = max(r[2] for r in self.results)
        self.assertLessEqual(worst, 400, f'最慢 {worst:.0f}ms')


if __name__ == '__main__':
    unittest.main()
