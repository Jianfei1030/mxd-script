"""OCR 单例与结果解析。detect 下各模块共用一个模型实例,避免重复加载。"""
from collections import namedtuple

_ocr_instance = None


def get_ocr():
    """惰性创建 onnxocr 实例(离线直读,不走框架 executor)。"""
    global _ocr_instance
    if _ocr_instance is None:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        _ocr_instance = ONNXPaddleOcr(use_angle_cls=False, use_det=True, use_rec=True, use_openvino=True)
    return _ocr_instance


def prewarm():
    """任务启用时预热模型(加载秒级),避免首次调用卡住 10Hz 触发循环。"""
    get_ocr()


class TextHit(namedtuple('TextHit', 'text conf x0 y0 x1 y1')):
    """一条 OCR 文本及其外接框(像素,相对送进去的那张图)。"""

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    @property
    def width(self):
        return self.x1 - self.x0


def _is_line(item):
    """一行 OCR 结果形如 [四点多边形, (文本, 置信度)]。"""
    return (isinstance(item, (list, tuple)) and len(item) == 2
            and isinstance(item[1], (list, tuple)) and len(item[1]) == 2
            and isinstance(item[1][0], str))


def read_texts(image, ocr_fn=None):
    """跑 OCR 并拍平成 [TextHit]。

    onnxocr 的 ocr() 返回 [[line, line, ...]] —— 比直觉多包一层。这里两种形状都吃,
    免得调用方各自踩坑(potions.py 曾因此在 2 行以上时抛 TypeError)。
    ocr_fn 可注入,离线测试不加载模型。
    """
    if ocr_fn is None:
        ocr_fn = lambda img: get_ocr().ocr(img)
    lines = []
    for item in ocr_fn(image) or []:
        if _is_line(item):
            lines.append(item)
        elif isinstance(item, (list, tuple)):
            lines.extend(x for x in item if _is_line(x))
    hits = []
    for poly, (text, conf) in lines:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        hits.append(TextHit(text, float(conf), int(min(xs)), int(min(ys)),
                            int(max(xs)), int(max(ys))))
    return hits
