import os
import unittest

import cv2

from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect

MODEL = 'assets/mob_model/mob.onnx'


@unittest.skipUnless(os.path.exists(MODEL), 'YOLO 模型未训练(Task 10),跳过')
class TestYolo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.detector = OpenVinoYolo8Detect(weights=MODEL)

    def test_detects_mobs_in_annotated_frame(self):
        """从 dataset/images/val 取一张有标注的帧,检出数应与标注数接近。"""
        import glob
        labeled = [p for p in glob.glob('dataset/labels/val/*.txt') if os.path.getsize(p) > 0]
        self.assertTrue(labeled, 'val 集无正样本标注')
        txt = sorted(labeled)[0]
        frame = cv2.imread(txt.replace('labels', 'images').replace('.txt', '.png'))
        expected = sum(1 for _ in open(txt, encoding='utf-8'))
        boxes = self.detector.detect(frame, threshold=0.5, label=0)
        self.assertGreaterEqual(len(boxes), max(1, expected - 1),
                                f'标注 {expected} 只,仅检出 {len(boxes)} 只')

    def test_empty_frame_no_mob(self):
        import glob
        empty = [p for p in glob.glob('dataset/labels/val/*.txt') if os.path.getsize(p) == 0]
        if not empty:
            self.skipTest('val 集无负样本')
        frame = cv2.imread(sorted(empty)[0].replace('labels', 'images').replace('.txt', '.png'))
        boxes = self.detector.detect(frame, threshold=0.5, label=0)
        self.assertEqual(len(boxes), 0, f'负样本误报 {len(boxes)} 个')


if __name__ == '__main__':
    unittest.main()
