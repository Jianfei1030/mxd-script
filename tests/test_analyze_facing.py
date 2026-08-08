"""analyze_facing.py 的两类测试:格式绑定 + scan 语义。

格式绑定:正则必须逐字对上 MapleFarmTask._log_decision / _maybe_capture_facing_template
写出的日志行。两边任何一方改动字段顺序/取值,这里的构造行就是绑定锚点 ——
构造行与任务代码各自独立漂移时,测试会红(而不是脚本静默报 0、A 判失败)。

scan 语义:判据 A 的分母、判据 B 的拍对判定都是「日志解析算法」,必须可测。
"""
import importlib.util
import os
import unittest

_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'analyze_facing.py')
_SPEC = importlib.util.spec_from_file_location('analyze_facing', _SCRIPT)
af = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(af)


def dec(src, f0, f1, obs, turn='-', seek='-', ts='2026-08-08 12:00:00,000'):
    """决策行 —— 字段与 MapleFarmTask._log_decision 的 f-string 逐字对应。

    f0/f1 传 None 表示信念未知(日志里是 '-'):观测未开启时整行没有
    实测=/分值= 后缀,这里的构造行也留不下它们,正则用 分值= 收尾。
    """
    f0s = f0 or '-'
    f1s = f1 or '-'
    return (f'{ts} DEBUG TaskExecutor MapleFarmTask:决策 src={src} '
            'body_x=1280 anchor_y=720 怪=0 区内=0(左0/右0) '
            '实测有怪=False 有怪=False 可打区内=0 可打=False '
            f'朝向={f0s}→{f1s} 转向={turn} 寻怪={seek} '
            f'可发键=True 实测={obs} 分值=0.86/0.39')


def cap(ts='2026-08-08 12:00:00,000'):
    """采集行 —— 与 _maybe_capture_facing_template 的 log_info 逐字对应。"""
    return f'{ts} INFO TaskExecutor MapleFarmTask:朝向模板已采集 方向=LEFT (寻怪走动确认 ≥40px)'


def div(dist, ts='2026-08-08 12:00:00,000'):
    """分歧行 —— 与 _log_decision 的朝向分歧块逐字对应。"""
    return (f'{ts} DEBUG TaskExecutor MapleFarmTask:朝向分歧 信念=LEFT 实测=RIGHT '
            f'分值=0.86/0.39 距上次攻击={dist:.2f}s 距上次受击=3.10s 距上次转向=1.55s')


class TestAnalyzeFacingRegex(unittest.TestCase):
    """正则与任务日志格式的绑定。"""

    def test_dec_matches_decision_line(self):
        m = af.DEC.search(dec('window', 'LEFT', 'RIGHT', 'L', turn='right'))
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ('window', 'LEFT', 'RIGHT', 'L'))

    def test_dec_matches_unknown_facing(self):
        m = af.DEC.search(dec('cached', None, None, '?'))
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ('cached', '-', '-', '?'))

    def test_div_matches_divergence_line(self):
        m = af.DIV.search(div(0.42))
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ('LEFT', 'RIGHT', '0.42'))

    def test_cap_matches_capture_line(self):
        self.assertIsNotNone(af.CAP.search(cap()))

    def test_ts_matches_timestamp_prefix(self):
        m = af.TS.match('2026-08-08 12:00:00,123 DEBUG TaskExecutor')
        self.assertEqual(m.group(1), '2026-08-08 12:00:00')


class TestAnalyzeFacingScan(unittest.TestCase):
    """scan 的判据语义:分母口径(A)、拍对判定(B)、分歧收集(D)。"""

    def test_a_denominator_starts_after_template_captured(self):
        """spec §5.4 A 的分母是「已有模板」的拍 —— 采模板之前的真命中拍不算,
        否则第一次寻怪走动确认之前的几十秒每一拍都是弃权,可用率被压低。"""
        st = af.scan([dec('window', None, None, '?'),   # 采模板之前
                      cap(),
                      dec('window', 'LEFT', 'LEFT', 'L')])
        self.assertEqual(st['fresh'], 1)
        self.assertEqual(st['answered'], 1)

    def test_a_denominator_fresh_sources_only(self):
        """cached/fallback 的锚点 ROI 整体错位,不算真命中(spec §5.4 口径)。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'L'),
                      dec('cached', 'LEFT', 'LEFT', 'R'),
                      dec('fallback', 'LEFT', 'LEFT', 'R')])
        self.assertEqual(st['fresh'], 1)
        self.assertEqual(st['answered'], 1)

    def test_b_pair_skipped_when_turn_landed(self):
        """转向 tap 落地:朝向=LEFT→RIGHT 信念在拍内翻转 → 这拍发过方向键,
        不许当「没发键」拍计入拍对(旧实现看 转向=,但它是"被决定"不是"被执行",
        且寻怪每拍长按却恒为 -)。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'RIGHT', 'L', turn='right'),
                      dec('window', 'RIGHT', 'RIGHT', 'L')])
        self.assertEqual(st['pairs'], 0)
        self.assertEqual(st['flips'], 0)

    def test_b_pair_skipped_when_seek_redirected(self):
        """寻怪换向:键在拍间按下,信念跨拍才翻 —— 只看拍内 f0==f1 会漏,
        边界(上一拍 f1 != 本拍 f0)不一致同样排除。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'L', seek='left'),
                      dec('window', 'RIGHT', 'RIGHT', 'L', seek='right')])
        self.assertEqual(st['pairs'], 0)

    def test_b_pair_counted_when_belief_stable(self):
        """信念稳定(含拍内、跨拍)且两拍都有答案 → 构成拍对,翻转算噪声。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'L'),
                      dec('window', 'LEFT', 'LEFT', 'R')])
        self.assertEqual(st['pairs'], 1)
        self.assertEqual(st['flips'], 1)

    def test_b_suppressed_turn_is_not_a_key(self):
        """被冷却挡住的转向:转向=right 写了但 _facing 没变 → 键没落地,
        这拍仍可计入拍对(旧实现按 转向= 把它当成发了键,漏掉了真正的噪声样本)。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'L', turn='right'),
                      dec('window', 'LEFT', 'LEFT', 'R')])
        self.assertEqual(st['pairs'], 1)
        self.assertEqual(st['flips'], 1)

    def test_b_abstain_frame_breaks_pair_chain(self):
        """弃权拍(实测=?)断开拍对链:相邻的两对答案不该隔着弃权拍配对。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'L'),
                      dec('window', 'LEFT', 'LEFT', '?'),
                      dec('window', 'LEFT', 'LEFT', 'R')])
        self.assertEqual(st['pairs'], 0)

    def test_divergences_collected(self):
        st = af.scan([cap(), div(0.42), div(2.51)])
        self.assertEqual(st['divergences'], [0.42, 2.51])

    def test_start_filter_skips_early_lines_but_keeps_template_state(self):
        """起始时间过滤只挡计数,不挡状态:模板在 start 之前就已采集,也要算。"""
        st = af.scan([cap('2026-08-08 09:00:00,000'),
                      dec('window', 'LEFT', 'LEFT', 'L', ts='2026-08-08 09:00:01,000'),
                      dec('window', 'LEFT', 'LEFT', 'L', ts='2026-08-08 10:00:01,000')],
                     start='09:30:00')
        self.assertEqual(st['fresh'], 1)
        self.assertEqual(st['answered'], 1)

    def test_empty_log_is_all_zeros(self):
        st = af.scan([])
        self.assertEqual(st['fresh'], 0)
        self.assertEqual(st['pairs'], 0)
        self.assertEqual(st['divergences'], [])


if __name__ == '__main__':
    unittest.main()
