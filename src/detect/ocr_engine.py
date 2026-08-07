"""OCR 单例与结果解析。detect 下各模块共用一个模型实例,避免重复加载。"""
import math
from collections import namedtuple

_ocr_instance = None

REC_WIDTH_BUCKET = 64  # rec 输入宽度归桶粒度(见 bucket_wh_ratio)


def bucket_wh_ratio(max_wh_ratio, img_h, bucket=REC_WIDTH_BUCKET):
    """把 rec 输入宽度上取整到 bucket 的倍数,再换算回宽高比。

    只会变宽、不会变窄——多出来的部分本来就是 padding(见 predict_rec.py
    `padding_im[:, :, 0:resized_w] = resized_image`),识别结果不受影响。
    """
    raw_w = math.ceil(img_h * max_wh_ratio)   # 不用 int():截断会让归桶后比原始还窄
    bucket_w = int(math.ceil(raw_w / bucket) * bucket)
    return bucket_w / float(img_h)


def install_rec_width_bucketing(ocr, bucket=REC_WIDTH_BUCKET):
    """给 recognizer 的 resize_norm_img 套一层宽度归桶。

    2026-08-07"运行久了未响应"的根因与解:onnxocr 的 predict_rec.py 按批内最宽
    文字框算 max_wh_ratio,rec 张量宽度 `imgW = int(imgH * max_wh_ratio)` 因此
    随画面文字近乎连续变化;OpenVINO 每见一个新形状就编译一份内核**永久缓存**,
    实测约 25MB/形状且永不释放——实机 9 分钟私有内存 1.4GB→8.3GB,撞上系统提交
    上限(本机 50.4GB)后全系统换页,表现为 GUI 未响应。

    实测(150 张真实帧走 anchor.find_in_region,det 输入恒定 640x240):
      归桶前 3771.8MB(25.15MB/帧,仍在涨) → 归桶后 729.3MB(4.86MB/帧,
      第 125 帧后完全持平),形状数只剩 5 种,从无界变有界。
    上游 onnxocr 是嵌入式 Python 的 site-packages,重装即失效,所以补在这里。
    """
    rec = ocr.text_recognizer
    original = rec.resize_norm_img
    if getattr(original, '_width_bucketed', False):
        return  # 热重载/重复调用不叠加 wrapper
    img_h = rec.rec_image_shape[1]

    def bucketed(img, max_wh_ratio):
        return original(img, bucket_wh_ratio(max_wh_ratio, img_h, bucket))

    bucketed._width_bucketed = True
    rec.resize_norm_img = bucketed


def get_ocr():
    """惰性创建 onnxocr 实例(离线直读,不走框架 executor)。"""
    global _ocr_instance
    if _ocr_instance is None:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr
        _ocr_instance = ONNXPaddleOcr(use_angle_cls=False, use_det=True, use_rec=True, use_openvino=True)
        install_rec_width_bucketing(_ocr_instance)
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
