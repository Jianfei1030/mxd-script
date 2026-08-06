import unittest

import cv2
import numpy as np

from src.detect import anchor


def make_frame(nametag_pos, nametag_size=(130, 30)):
    """全黑 2560x1440 帧,在 nametag_pos 放白块模拟名字牌。"""
    frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
    x, y = nametag_pos
    w, h = nametag_size
    frame[y:y + h, x:x + w] = 255
    return frame


def make_ocr_fn(target_text, frame, call_log):
    """假 OCR:扫 crop 里最大白块,面积接近名字牌则返回 (box, (target_text, 0.9))。
    target_text 可为 None → 返回粘连/截断文本,用于判据测试。"""
    def ocr_fn(crop):
        call_log.append(crop.shape)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = (gray > 128).astype(np.uint8)
        if mask.sum() < 500:  # 无白块
            return []
        ys, xs = np.where(mask)
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if target_text is None:
            return [(box, ('粘连文本比名字长很多', 0.9))]
        return [(box, (target_text, 0.9))]
    return ocr_fn


class TestAnchorOffline(unittest.TestCase):

    def test_fast_channel_hit(self):
        """快通道:prev_anchor 附近有名字牌 → 命中,只调 1 次 OCR。"""
        frame = make_frame((1100, 860))
        log = []
        ocr = make_ocr_fn('Yufeng咕咕', frame, log)
        hit = anchor.find_anchor(frame, 'Yufeng咕咕', prev_anchor=(1160, 870), ocr_fn=ocr)
        self.assertIsNotNone(hit)
        # 名字牌中心 = (1100+65, 860+15) = (1165, 875)
        self.assertAlmostEqual(hit[0], 1165, delta=2)
        self.assertAlmostEqual(hit[1], 875, delta=2)
        self.assertEqual(len(log), 1)  # 快通道一次命中,不落慢通道

    def test_slow_channel_when_fast_misses(self):
        """快通道窗内无牌 → 落慢通道中央区命中。"""
        frame = make_frame((1100, 860))
        log = []
        ocr = make_ocr_fn('Yufeng咕咕', frame, log)
        hit = anchor.find_anchor(frame, 'Yufeng咕咕', prev_anchor=(100, 100), ocr_fn=ocr)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit[0], 1165, delta=2)
        self.assertGreaterEqual(len(log), 2)  # 快通道失败 + 慢通道分块

    def test_empty_name_no_ocr(self):
        """角色名留空 → None,不调 OCR。"""
        frame = make_frame((1100, 860))
        log = []
        ocr = make_ocr_fn('Yufeng咕咕', frame, log)
        hit = anchor.find_anchor(frame, '', prev_anchor=(1160, 870), ocr_fn=ocr)
        self.assertIsNone(hit)
        self.assertEqual(len(log), 0)

    def test_no_nametag_returns_none(self):
        frame = np.zeros((1440, 2560, 3), dtype=np.uint8)  # 无白块
        log = []
        ocr = make_ocr_fn('Yufeng咕咕', frame, log)
        hit = anchor.find_anchor(frame, 'Yufeng咕咕', prev_anchor=(1160, 870), ocr_fn=ocr)
        self.assertIsNone(hit)

    def test_concatenated_text_rejected(self):
        """粘连(更长)文本必须被完全匹配判据挡掉 → None。"""
        frame = make_frame((1100, 860))
        log = []
        ocr = make_ocr_fn(None, frame, log)  # 返回粘连文本
        hit = anchor.find_anchor(frame, 'Yufeng咕咕', prev_anchor=(1160, 870), ocr_fn=ocr)
        self.assertIsNone(hit)

    def test_out_of_frame_window_clamped(self):
        """prev_anchor 在角落:小窗越界被裁剪,不崩溃。"""
        frame = make_frame((1100, 860))
        log = []
        ocr = make_ocr_fn('Yufeng咕咕', frame, log)
        hit = anchor.find_anchor(frame, 'Yufeng咕咕', prev_anchor=(0, 0), ocr_fn=ocr)
        self.assertIsNotNone(hit)  # 慢通道兜底命中


if __name__ == '__main__':
    unittest.main()
