# -*- coding: utf-8 -*-
"""analyze_anchor 的判据算术与决策行格式绑定。

样本行必须用 decision_log_line 构造(2026-08-08 评审坐实过手抄格式的假绑定,
见 MapleFarmTask.py:93 docstring):格式一改,本文件立刻红。
"""
import unittest

from scripts.analyze_anchor import parse, sessionize, loss_episodes, metrics
from src.task.MapleFarmTask import decision_log_line


def _line(ts, source, can_atk):
    """带时间戳前缀的完整日志行。除 src/可打 外全部字段取任意合法值。"""
    body = decision_log_line(source, 1230.0, 866.0, [(1.0, 2.0)] * 3, [1.0], 1,
                             0, 1, None, True, True, [1.0], can_atk,
                             'LEFT', 'LEFT', None, None, True, None, 0.0, 0.0)
    return f'{ts} DEBUG TaskExecutor MapleFarmTask:{body}\n'


def _ts(sec, ms=0):
    return f'2026-08-09 12:{sec // 60:02d}:{sec % 60:02d},{ms:03d}'


class TestParse(unittest.TestCase):

    def test_parse_extracts_src_and_can_atk(self):
        rows = parse([_line(_ts(0), 'template', True),
                      _line(_ts(1), 'cached', False),
                      'not a decision line\n'])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['src'], 'template')
        self.assertTrue(rows[0]['can_atk'])
        self.assertEqual(rows[1]['src'], 'cached')
        self.assertFalse(rows[1]['can_atk'])
        self.assertAlmostEqual(rows[1]['t'] - rows[0]['t'], 1.0)

    def test_parse_accepts_yolo_source(self):
        # 新来源标签 src=yolo 是普通值,不许被正则漏掉
        rows = parse([_line(_ts(0), 'yolo', True)])
        self.assertEqual(rows[0]['src'], 'yolo')


class TestEpisodes(unittest.TestCase):

    def _rows(self, srcs, dt=0.5):
        return [dict(t=100.0 + i * dt, src=s, can_atk=False)
                for i, s in enumerate(srcs)]

    def test_loss_episode_spans_from_first_lost_to_recovery(self):
        # template cached cached template → 一段,时长 2 拍 * 0.5s = 1.0
        eps = loss_episodes([self._rows(
            ['template', 'cached', 'cached', 'template'])])
        self.assertEqual(len(eps), 1)
        self.assertAlmostEqual(eps[0], 1.0)

    def test_fallback_counts_as_lost_and_tail_open_episode_dropped(self):
        # 段尾还在丢(没有恢复拍) → 时长未知,不计
        eps = loss_episodes([self._rows(
            ['window', 'fallback', 'cached'])])
        self.assertEqual(eps, [])

    def test_yolo_counts_as_real_position(self):
        eps = loss_episodes([self._rows(
            ['cached', 'yolo', 'cached', 'template'])])
        # yolo 是真实观测:第一段在 yolo 拍恢复(0.5s),第二段在 template 拍恢复(0.5s)
        self.assertEqual(len(eps), 2)
        for e in eps:
            self.assertAlmostEqual(e, 0.5)


class TestMetrics(unittest.TestCase):

    def test_metrics_on_synthetic_session(self):
        # 30 拍 × 0.5s:6 拍 cached(3+3 两段,各 1.5s),24 拍 template;可打前 15 拍 True
        srcs = (['template'] * 8 + ['cached'] * 3 + ['template'] * 8
                + ['cached'] * 3 + ['template'] * 8)
        rows = [dict(t=100.0 + i * 0.5, src=s, can_atk=i < 15)
                for i, s in enumerate(srcs)]
        m = metrics(sessionize(rows))
        self.assertEqual(m['ticks'], 30)
        self.assertAlmostEqual(m['A_lost_ratio'], 6 / 30)
        self.assertAlmostEqual(m['B_p90'], 1.5)
        self.assertAlmostEqual(m['C_per_hour'], 0.0)  # 两段都 < 3s
        self.assertAlmostEqual(m['D_ratio'], 15 / 30)
        self.assertAlmostEqual(m['E_median'], 0.5)

    def test_sessionize_splits_on_gap(self):
        rows = ([dict(t=100.0 + i * 0.5, src='template', can_atk=True)
                 for i in range(25)]
                + [dict(t=200.0 + i * 0.5, src='template', can_atk=True)
                   for i in range(25)])
        self.assertEqual(len(sessionize(rows)), 2)


if __name__ == '__main__':
    unittest.main()
