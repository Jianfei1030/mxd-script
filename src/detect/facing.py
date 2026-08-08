"""角色朝向观测:用头+肩模板与其水平镜像各匹配一次,谁分高就朝哪边。

只读观测器 —— 结果只进日志,不写回 `_facing`、不参与任何决策(spec §3.4)。
造它的原因见 spec §1:`_facing` 是纯信念,项目在它上面改了四轮,三条记为无效、
一条实测有害,共同点是没有尺子。

可行性与阈值出自 2026-08-07 附录 A 的 24 帧实测:20/24 命中、0 误判、4 弃权
(弃权全是宠物「小白雪人」挡住或角色被 ROI 切边),胜出分中位 0.883、差值中位
0.411,命中帧胜出分最低 0.78 而弃权帧最高 0.45 —— 裕度很大,阈值不要动。
弃权是这个仪器最值钱的性质:宁可不答,不许答错。
"""

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
