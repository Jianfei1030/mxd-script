# -*- coding: utf-8 -*-
"""analyze_turn 的解析与统计绑定。

格式绑定必须调 decision_log_line 真实构造样本行 —— 手抄格式字符串是假绑定
(2026-08-08 评审坐实过,commit 9016133)。
"""
import importlib.util
import os
import unittest

from src.task.MapleFarmTask import decision_log_line

# scripts/ 不是包(没有 __init__.py),按 tests/test_analyze_seek.py 同款方式加载
_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'analyze_turn.py')
_SPEC = importlib.util.spec_from_file_location('analyze_turn', _SCRIPT)
analyze_turn = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analyze_turn)


def line(ts, facing_before, facing_now, turn):
    """用真实格式函数造一条带时间戳前缀的决策行。"""
    body = decision_log_line(
        source='window', body_x=1280, anchor_y=800, centres=[], in_zone=[], left=0,
        same_feet=0, same_center=0, near=None,
        raw_present=False, mob_present=False, attack_in=[], attack_present=False,
        facing_before=facing_before, facing_now=facing_now, turn=turn,
        seek_dir=None, key_sendable=True, observed=None, obs_s=0.0, obs_flip=0.0)
    return f'2026-08-09 {ts} DEBUG TaskExecutor MapleFarmTask:{body}\n'


class TestAnalyzeTurn(unittest.TestCase):

    def test_settled_latency_is_turn_to_first_stable_new_facing_beat(self):
        """转向拍 → 第一个 朝向=新→新 且没再转向的拍,延迟取两者时间差。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'RIGHT', None),
            line('10:00:00,700', 'RIGHT', 'LEFT', 'left'),    # 转向拍
            line('10:00:00,800', 'LEFT', 'LEFT', None),       # 结算拍
        ])
        self.assertEqual(out['turns'], 1)
        self.assertEqual(out['outcome']['settled'], 1)
        self.assertAlmostEqual(out['latencies'][0], 0.1, places=3)

    def test_re_turn_before_settling_is_not_counted_as_latency(self):
        """结算前又转了一次 → 记 re_turned,不污染延迟分布。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),
            line('10:00:00,300', 'LEFT', 'RIGHT', 'right'),
        ])
        self.assertEqual(out['outcome']['re_turned'], 1)
        self.assertEqual(out['latencies'], [])

    def test_corrected_back_by_observer(self):
        """结算前信念被纠正回旧朝向 → 记 corrected_back。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),
            line('10:00:00,300', 'LEFT', 'RIGHT', None),
        ])
        self.assertEqual(out['outcome']['corrected_back'], 1)
        self.assertEqual(out['latencies'], [])

    def test_gap_is_turn_beat_to_the_very_next_beat(self):
        """gaps 量的是节拍本身,与结算与否无关 —— 它才是 攻击间隔 的直接证据。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),
            line('10:00:00,706', 'LEFT', 'LEFT', None),
        ])
        self.assertAlmostEqual(out['gaps'][0], 0.706, places=3)

    def test_non_decision_lines_ignored(self):
        out = analyze_turn.scan([
            '2026-08-09 10:00:00,000 INFO TaskExecutor MapleFarmTask:随便一行\n',
            line('10:00:01,000', 'RIGHT', 'RIGHT', None),
        ])
        self.assertEqual(out['beats'], 1)
        self.assertEqual(out['turns'], 0)

    def test_turn_at_end_of_log_is_truncated_not_never_settled(self):
        """日志最后一拍正好是转向拍:后面没有拍可看,不是「40 拍没结算」。

        2026-08-09 实测:08-08 那条 never_settled:1 就是文件末尾的转向拍
        (索引 26364 = 最后一拍),被 for...else 的 else 误判成没结算。
        """
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),
        ])
        self.assertEqual(out['turns'], 1)
        self.assertEqual(out['outcome']['truncated'], 1)
        self.assertEqual(out['outcome']['never_settled'], 0)
        self.assertEqual(out['latencies'], [])

    def test_short_tail_without_settle_is_truncated(self):
        """转向后只剩 <40 拍就到底、且没结算 → truncated,不是 never_settled。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),      # 转向拍(new=LEFT)
            line('10:00:00,100', 'RIGHT', 'LEFT', None),        # f1==new 但 f0!=new:不结算,继续
            line('10:00:00,200', 'RIGHT', 'LEFT', None),        # 日志到此结束,尾长 2 < 40
        ])
        self.assertEqual(out['outcome']['truncated'], 1)
        self.assertEqual(out['outcome']['never_settled'], 0)

    def test_full_lookahead_without_settle_is_never_settled(self):
        """完整 40 拍窗口内没结算 → 仍是 never_settled(护栏,修复不能误伤它)。"""
        rows = [line('10:00:00,000', 'RIGHT', 'LEFT', 'left')]
        for k in range(1, 45):                                  # 转向后 44 拍 ≥ 40
            rows.append(line(f'10:00:{k:02d},000', 'RIGHT', 'LEFT', None))
        out = analyze_turn.scan(rows)
        self.assertEqual(out['outcome']['never_settled'], 1)
        self.assertEqual(out['outcome']['truncated'], 0)


if __name__ == '__main__':
    unittest.main()
