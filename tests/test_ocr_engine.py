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


class TestRecWidthBucketing(unittest.TestCase):
    """rec 输入宽度归桶——2026-08-07"运行久了未响应"的解。

    onnxocr/predict_rec.py 用批内最宽文字框算 max_wh_ratio,rec 张量宽度
    `imgW = int(imgH * max_wh_ratio)` 因此近乎连续变化;OpenVINO 每见一个新形状
    就编译一份内核永久缓存(实测约 25MB/形状,永不释放),实机 9 分钟涨到 8.3GB,
    撞上系统提交上限后全系统换页 = 未响应。归桶把形状数从上千塌缩到个位数。
    """

    IMG_H = 48  # rec_image_shape = (3, 48, 320)

    def _width(self, ratio):
        return int(self.IMG_H * ratio)

    def test_rounds_width_up_to_bucket_multiple(self):
        ratio = ocr_engine.bucket_wh_ratio(400 / self.IMG_H, self.IMG_H, bucket=64)
        self.assertEqual(self._width(ratio), 448)  # 400 → 上取整到 64 的倍数

    def test_exact_multiple_is_left_alone(self):
        """已经落在桶上就不该再撑宽:多余的 padding 是纯浪费。"""
        ratio = ocr_engine.bucket_wh_ratio(384 / self.IMG_H, self.IMG_H, bucket=64)
        self.assertEqual(self._width(ratio), 384)

    def test_never_narrows(self):
        """只许变宽。变窄会截断文字 = 改变识别结果,这是本修法的正确性底线。"""
        for raw_w in range(320, 1200, 7):
            ratio = ocr_engine.bucket_wh_ratio(raw_w / self.IMG_H, self.IMG_H, bucket=64)
            self.assertGreaterEqual(self._width(ratio), raw_w, f'raw_w={raw_w} 被截窄了')

    def test_collapses_many_widths_to_few_shapes(self):
        """真正要的性质:上千种宽度塌缩成个位数形状。"""
        raw_widths = range(320, 1200)
        bucketed = {self._width(ocr_engine.bucket_wh_ratio(w / self.IMG_H, self.IMG_H, bucket=64))
                    for w in raw_widths}
        self.assertLessEqual(len(bucketed), 16)
        self.assertGreater(len(raw_widths), 800)  # 输入确实是上千种

    def test_install_wraps_recognizer(self):
        """装载后 recognizer 收到的必须是归桶过的 ratio(不加载真模型)。"""
        seen = []

        class FakeRec:
            rec_image_shape = (3, 48, 320)

            def resize_norm_img(self, img, max_wh_ratio):
                seen.append(max_wh_ratio)
                return 'norm'

        class FakeOcr:
            def __init__(self):
                self.text_recognizer = FakeRec()

        ocr = FakeOcr()
        ocr_engine.install_rec_width_bucketing(ocr, bucket=64)
        result = ocr.text_recognizer.resize_norm_img('img', 400 / self.IMG_H)

        self.assertEqual(result, 'norm')  # 原函数的返回值要原样透传
        self.assertEqual(len(seen), 1)
        self.assertEqual(int(self.IMG_H * seen[0]), 448)

    def test_install_is_idempotent(self):
        """热重载/重复调用不该叠加多层 wrapper。"""
        class FakeRec:
            rec_image_shape = (3, 48, 320)

            def resize_norm_img(self, img, max_wh_ratio):
                return max_wh_ratio

        class FakeOcr:
            def __init__(self):
                self.text_recognizer = FakeRec()

        ocr = FakeOcr()
        ocr_engine.install_rec_width_bucketing(ocr, bucket=64)
        first = ocr.text_recognizer.resize_norm_img
        ocr_engine.install_rec_width_bucketing(ocr, bucket=64)
        self.assertIs(ocr.text_recognizer.resize_norm_img, first)


if __name__ == '__main__':
    unittest.main()
