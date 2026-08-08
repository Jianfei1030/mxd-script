"""角色朝向观测:用头+肩模板与其水平镜像各匹配一次,谁分高就朝哪边。

只读观测器 —— 结果只进日志,不写回 `_facing`、不参与任何决策(spec §3.4)。
造它的原因见 spec §1:`_facing` 是纯信念,项目在它上面改了四轮,三条记为无效、
一条实测有害,共同点是没有尺子。

可行性与阈值出自 2026-08-07 附录 A 的 24 帧实测:20/24 命中、0 误判、4 弃权
(弃权全是宠物「小白雪人」挡住或角色被 ROI 切边),胜出分中位 0.883、差值中位
0.411,命中帧胜出分最低 0.78 而弃权帧最高 0.45 —— 裕度很大,阈值不要动。
弃权是这个仪器最值钱的性质:宁可不答,不许答错。
"""

import cv2
import numpy as np

FACING_SCORE_MIN = 0.70   # 胜出分下界:低于此说明两边都不像(挡住/切边)
FACING_MARGIN_MIN = 0.20  # 两分差值下界:低于此说明分不出朝向


def decide(s, s_flip, template_facing):
    """(模板分, 镜像分, 模板自身朝向) → 'LEFT' / 'RIGHT' / None(弃权)。

    s > s_flip → 与模板同向;否则反向。模板朝向未知/非法一律弃权,不猜。
    """
    if template_facing not in ('LEFT', 'RIGHT'):
        return None
    if max(s, s_flip) < FACING_SCORE_MIN:
        return None
    if abs(s - s_flip) < FACING_MARGIN_MIN:
        return None
    same = s > s_flip
    if same:
        return template_facing
    return 'RIGHT' if template_facing == 'LEFT' else 'LEFT'


ROI_HALF_W = 90     # ROI 半宽:x ∈ [a.x-90, a.x+90]
ROI_TOP_DY = 160    # ROI 上沿:a.y - 160(名字牌画在脚下,角色在牌子上方)
ROI_BOTTOM_DY = 20  # ROI 下沿:a.y - 20(把名字牌本身排除掉)


def roi_box(frame_shape, anchor_obj):
    """朝向 ROI (x0, y0, x1, y1),照抄附录 A.1 的 180x140。

    被画面边缘切到 → 返回 None。宁可不观测,也不要拿半张角色去匹配:
    附录 A 的 #0 弃权帧就是切边造成的,而切了边的 ROI 会让分数不可比。
    """
    h, w = frame_shape[:2]
    x0 = int(anchor_obj.x) - ROI_HALF_W
    x1 = int(anchor_obj.x) + ROI_HALF_W
    y0 = int(anchor_obj.y) - ROI_TOP_DY
    y1 = int(anchor_obj.y) - ROI_BOTTOM_DY
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    return x0, y0, x1, y1


def crop_roi(frame, anchor_obj):
    """按 roi_box 裁出灰度 ROI;越界 → None。"""
    box = roi_box(frame.shape, anchor_obj)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    return cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)


def scores(roi_gray, template):
    """(模板分, 镜像分):各跑一次 TM_CCOEFF_NORMED 取最大值。

    镜像用 cv2.flip(template, 1) —— 角色朝向翻转在图像上就是水平镜像,
    所以同一个模板能同时当两个方向的判据,不需要两套模板(附录 A.1)。
    """
    s = float(cv2.matchTemplate(roi_gray, template, cv2.TM_CCOEFF_NORMED).max())
    flipped = cv2.flip(template, 1)
    s_flip = float(cv2.matchTemplate(roi_gray, flipped, cv2.TM_CCOEFF_NORMED).max())
    return s, s_flip


def observe(frame, anchor_obj, template, template_facing):
    """一次朝向观测 → (朝向, s, s_flip)。朝向为 None 表示弃权。

    没模板 / ROI 越界 / 模板比 ROI 大 → (None, 0.0, 0.0)。
    调用方必须保证 anchor_obj 是**本拍真命中**的(source in window/region/template):
    cached/fallback 的锚点会让 ROI 整体错位,裁出来是草地和宠物脸(附录 A.3)。
    """
    if template is None:
        return None, 0.0, 0.0
    roi = crop_roi(frame, anchor_obj)
    if roi is None:
        return None, 0.0, 0.0
    if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
        return None, 0.0, 0.0
    s, s_flip = scores(roi, template)
    return decide(s, s_flip, template_facing), s, s_flip
