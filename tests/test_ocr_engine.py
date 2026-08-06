import unittest

from src.detect import ocr_engine

# onnxocr 的真实返回形状:外层比直觉多包一层 [[ [多边形, (文本, 置信度)], ... ]]
# 实测样本(2026-08-06,map1_frame_0000 名字牌 ROI):
NESTED = [[
    [[[67.0, 10.0], [196.0, 10.0], [196.0, 43.0], [67.0, 43.0]], ('Yufeng咕咕', 0.996)],
    [[[10.0, 50.0], [180.0, 50.0], [180.0, 80.0], [10.0, 80.0]], ('新手冒险家勋章', 0.981)],
]]
FLAT = NESTED[0]


class TestReadTexts(unittest.TestCase):

    def test_nested_shape(self):
        hits = ocr_engine.read_texts(None, ocr_fn=lambda img: NESTED)
        self.assertEqual([h.text for h in hits], ['Yufeng咕咕', '新手冒险家勋章'])

    def test_flat_shape(self):
        """有的调用方已经拆过一层,两种形状都要吃下,不许再出现 potions 那种 TypeError。"""
        hits = ocr_engine.read_texts(None, ocr_fn=lambda img: FLAT)
        self.assertEqual([h.text for h in hits], ['Yufeng咕咕', '新手冒险家勋章'])

    def test_empty_inputs(self):
        for empty in ([[]], [], None):
            self.assertEqual(ocr_engine.read_texts(None, ocr_fn=lambda img: empty), [])

    def test_geometry(self):
        hit = ocr_engine.read_texts(None, ocr_fn=lambda img: NESTED)[0]
        self.assertEqual((hit.x0, hit.y0, hit.x1, hit.y1), (67, 10, 196, 43))
        self.assertEqual(hit.width, 129)
        self.assertEqual(hit.cx, 131.5)
        self.assertEqual(hit.cy, 26.5)

    def test_junk_lines_ignored(self):
        junk = [['not a line'], [[[0, 0]], ('缺置信度',)], None]
        self.assertEqual(ocr_engine.read_texts(None, ocr_fn=lambda img: junk), [])


if __name__ == '__main__':
    unittest.main()
