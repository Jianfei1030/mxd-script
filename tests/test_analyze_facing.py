"""analyze_facing.py 与日志格式的绑定测试 + scan 语义测试。

样本行一律由 MapleFarmTask 的格式函数构造(decision_log_line /
divergence_log_line / template_captured_line),不手抄格式 —— 谁改日志字段,
这里的样本行跟着变,正则对不上立刻红。2026-08-08 评审坐实过假绑定:
以前测试里手抄了一份格式,把 _log_decision 的 `实测=` 改名成 `观测=` 后
15 个「绑定」测试全过。现在格式只有一处(任务模块),测试只传数值。

scan 语义:判据 A 的分母、判据 B 的拍对判定都是「日志解析算法」,必须可测。
"""
import importlib.util
import os
import unittest

from src.task.MapleFarmTask import (
    decision_log_line, divergence_log_line, template_captured_line)

_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'analyze_facing.py')
_SPEC = importlib.util.spec_from_file_location('analyze_facing', _SCRIPT)
af = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(af)

TS = '2026-08-08 12:00:00,000'


def task_line(ts, line):
    """ok.Logger 的行前缀(框架格式,非本仓库日志字段)。"""
    return f'{ts} DEBUG TaskExecutor MapleFarmTask:{line}'


def dec(src, f0, f1, obs, turn='-', seek='-', ts=TS, key_sendable=True):
    """决策行 —— 格式来自 decision_log_line,这里只传数值(测试输入)。

    obs 传观测朝向长写 'LEFT'/'RIGHT'/None:真实接线里 _observe_facing 返回的
    就是长写,短写 L/R 是格式函数内部换算的(手抄格式的旧测试传短写,
    换到真实函数后这一层立即暴露)。"""
    return task_line(ts, decision_log_line(
        src, 1280.0, 720.0, centres=[], in_zone=[], left=0,
        raw_present=False, mob_present=False, attack_in=[], attack_present=False,
        facing_before=f0, facing_now=f1, turn=turn, seek_dir=seek,
        key_sendable=key_sendable, observed=obs, obs_s=0.86, obs_flip=0.39))


def cap(ts=TS):
    """采集行 —— 格式来自 template_captured_line。"""
    return task_line(ts, template_captured_line('LEFT', 40))


def div(dist, ts=TS):
    """分歧行 —— 格式来自 divergence_log_line。"""
    return task_line(ts, divergence_log_line('LEFT', 'RIGHT', 0.86, 0.39,
                                             dist, 3.10, 1.55))


class TestAnalyzeFacingRegex(unittest.TestCase):
    """正则与任务日志格式的绑定:样本行由格式函数生成,字段改名立刻红。"""

    def test_dec_matches_decision_line(self):
        m = af.DEC.search(dec('window', 'LEFT', 'RIGHT', 'LEFT', turn='right'))
        self.assertIsNotNone(m)
        self.assertEqual(m.groups(), ('window', 'LEFT', 'RIGHT', 'L'))

    def test_dec_matches_unknown_facing(self):
        m = af.DEC.search(dec('cached', None, None, None))
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
        st = af.scan([dec('window', None, None, None),   # 采模板之前
                      cap(),
                      dec('window', 'LEFT', 'LEFT', 'LEFT')])
        self.assertEqual(st['fresh'], 1)
        self.assertEqual(st['answered'], 1)

    def test_a_denominator_fresh_sources_only(self):
        """cached/fallback 的锚点 ROI 整体错位,不算真命中(spec §5.4 口径)。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'LEFT'),
                      dec('cached', 'LEFT', 'LEFT', 'RIGHT'),
                      dec('fallback', 'LEFT', 'LEFT', 'RIGHT')])
        self.assertEqual(st['fresh'], 1)
        self.assertEqual(st['answered'], 1)

    def test_b_pair_skipped_when_turn_landed(self):
        """转向 tap 落地:朝向=LEFT→RIGHT 信念在拍内翻转 → 这拍发过方向键,
        不许当「没发键」拍计入拍对(旧实现看 转向=,但它是"被决定"不是"被执行",
        且寻怪每拍长按却恒为 -)。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'RIGHT', 'LEFT', turn='right'),
                      dec('window', 'RIGHT', 'RIGHT', 'LEFT')])
        self.assertEqual(st['pairs'], 0)
        self.assertEqual(st['flips'], 0)

    def test_b_pair_skipped_when_seek_redirected(self):
        """寻怪换向:键在拍间按下,信念跨拍才翻 —— 只看拍内 f0==f1 会漏,
        边界(上一拍 f1 != 本拍 f0)不一致同样排除。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'LEFT', seek='left'),
                      dec('window', 'RIGHT', 'RIGHT', 'LEFT', seek='right')])
        self.assertEqual(st['pairs'], 0)

    def test_b_pair_counted_when_belief_stable(self):
        """信念稳定(含拍内、跨拍)且两拍都有答案 → 构成拍对,翻转算噪声。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'LEFT'),
                      dec('window', 'LEFT', 'LEFT', 'RIGHT')])
        self.assertEqual(st['pairs'], 1)
        self.assertEqual(st['flips'], 1)

    def test_b_suppressed_turn_is_not_a_key(self):
        """被冷却挡住的转向:转向=right 写了但 _facing 没变 → 键没落地,
        这拍仍可计入拍对(旧实现按 转向= 把它当成发了键,漏掉了真正的噪声样本)。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'LEFT', turn='right'),
                      dec('window', 'LEFT', 'LEFT', 'RIGHT')])
        self.assertEqual(st['pairs'], 1)
        self.assertEqual(st['flips'], 1)

    def test_b_abstain_frame_breaks_pair_chain(self):
        """弃权拍(实测=?)断开拍对链:相邻的两对答案不该隔着弃权拍配对。"""
        st = af.scan([cap(),
                      dec('window', 'LEFT', 'LEFT', 'LEFT'),
                      dec('window', 'LEFT', 'LEFT', None),
                      dec('window', 'LEFT', 'LEFT', 'RIGHT')])
        self.assertEqual(st['pairs'], 0)

    def test_divergences_collected(self):
        st = af.scan([cap(), div(0.42), div(2.51)])
        self.assertEqual(st['divergences'], [0.42, 2.51])

    def test_start_filter_skips_early_lines_but_keeps_template_state(self):
        """起始时间过滤只挡计数,不挡状态:模板在 start 之前就已采集,也要算。"""
        st = af.scan([cap('2026-08-08 09:00:00,000'),
                      dec('window', 'LEFT', 'LEFT', 'LEFT', ts='2026-08-08 09:00:01,000'),
                      dec('window', 'LEFT', 'LEFT', 'LEFT', ts='2026-08-08 10:00:01,000')],
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
