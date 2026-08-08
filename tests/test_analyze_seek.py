"""analyze_seek.py 与日志格式的绑定测试 + 判据算法测试。

样本行一律由 MapleFarmTask.decision_log_line 构造,不手抄格式 ——
谁改日志字段,这里的样本行跟着变,正则对不上立刻红(见
tests/test_analyze_facing.py 顶部关于 2026-08-08 假绑定的记录)。

判据定义在 docs/superpowers/specs/2026-08-08-seek-latency-design.md §5,
本文件只测「算法算得对不对」,不测通过线。
"""
import importlib.util
import os
import unittest

from src.task.MapleFarmTask import decision_log_line

_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'analyze_seek.py')
_SPEC = importlib.util.spec_from_file_location('analyze_seek', _SCRIPT)
aseek = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(aseek)


def line(sec, mobs=0, can_atk=False, seek='-', same_feet=0, same_center=0):
    """一条带时间戳的决策行。sec = 当天第几秒(测试只关心相对时间)。"""
    ts = f'2026-08-08 {sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d},000'
    body = decision_log_line(
        'window', 1280.0, 880.0,
        centres=[(0.0, 0.0)] * mobs, in_zone=[], left=0,
        same_feet=same_feet, same_center=same_center, near=None,
        raw_present=False, mob_present=False,
        attack_in=[], attack_present=can_atk,
        facing_before='LEFT', facing_now='LEFT', turn=None, seek_dir=seek,
        key_sendable=True, observed=None, obs_s=0.0, obs_flip=0.0)
    return f'{ts} DEBUG TaskExecutor MapleFarmTask:{body}'


class TestParse(unittest.TestCase):

    def test_parses_fields_written_by_the_real_formatter(self):
        rows = aseek.parse([line(10, mobs=3, can_atk=True, seek='right',
                                 same_feet=1, same_center=4)])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['mobs'], 3)
        self.assertTrue(r['can_atk'])
        self.assertEqual(r['seek'], 'right')
        self.assertEqual(r['same_feet'], 1)
        self.assertEqual(r['same_center'], 4)

    def test_ignores_non_decision_lines(self):
        self.assertEqual(aseek.parse(['2026-08-08 10:00:00,000 INFO x:随便什么']), [])

    def test_tolerates_older_log_generations(self):
        """老日志必须照样能算 —— 基线快照里就有两代格式。

        这两条样本**故意手抄**,是「禁止手抄格式」那条规矩的正当例外:
        它们是**历史**格式,今天的 decision_log_line 已经生不出来了,
        而 Step 5 复算基线要靠解析它们。判据 A-E 都不依赖纵向字段。
        """
        # 第一代:8eb39ce(朝向纠正)之前,连 实测=/分值= 尾巴都没有
        gen1 = ('2026-08-08 10:00:00,000 DEBUG TaskExecutor MapleFarmTask:'
                '决策 src=window body_x=1280 anchor_y=880 怪=3 区内=0(左0/右0) '
                '实测有怪=False 有怪=False 可打区内=0 可打=False '
                '朝向=LEFT→LEFT 转向=- 寻怪=left 可发键=True')
        # 第二代:有 实测=/分值=,但还没有 Task 1 的纵向字段
        gen2 = ('2026-08-08 15:00:00,000 DEBUG TaskExecutor MapleFarmTask:'
                '决策 src=window body_x=1280 anchor_y=880 怪=3 区内=0(左0/右0) '
                '实测有怪=False 有怪=False 可打区内=0 可打=True '
                '朝向=LEFT→LEFT 转向=- 寻怪=right 可发键=True 实测=? 分值=0.00/0.00')
        rows = aseek.parse([gen1, gen2])
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['seek'] for r in rows], ['left', 'right'])
        self.assertEqual([r['can_atk'] for r in rows], [False, True])
        self.assertEqual([r['mobs'] for r in rows], [3, 3])
        self.assertEqual([r['same_feet'] for r in rows], [None, None])


class TestSessionize(unittest.TestCase):

    def test_splits_on_long_gap(self):
        rows = aseek.parse([line(1), line(2), line(3), line(60), line(61), line(62)])
        self.assertEqual(len(aseek.sessionize(rows, gap=10.0, min_rows=2)), 2)


class TestMetrics(unittest.TestCase):

    def test_A_waits_from_stop_attacking_to_seek_start(self):
        # 第 1 秒还在打 → 第 2 秒停手且屏幕有怪(等待起算) → 第 5 秒才起步 = 3s
        rows = aseek.parse([line(1, mobs=2, can_atk=True),
                            line(2, mobs=2), line(3, mobs=2), line(4, mobs=2),
                            line(5, mobs=2, seek='left')])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['A_median'], 3.0, places=2)

    def test_A_ignores_stretches_with_no_mob_on_screen(self):
        # 屏幕上没怪,不追是对的,不该计进等待
        rows = aseek.parse([line(1, mobs=1, can_atk=True), line(2), line(3),
                            line(4, mobs=1), line(5, mobs=1, seek='left')])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['A_median'], 1.0, places=2)

    def test_B_counts_seek_segments_lasting_at_least_half_second(self):
        # 段一:第 1-3 秒在追(2s,算撑住);段二:第 5 秒一拍就断(0s,不算)
        rows = aseek.parse([line(1, mobs=1, seek='left'), line(2, mobs=1, seek='left'),
                            line(3, mobs=1, seek='left'), line(4, mobs=1),
                            line(5, mobs=1, seek='right'), line(6, mobs=1)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['B_ratio'], 0.5, places=3)

    def test_C_idle_ratio_counts_only_stretches_with_mobs_on_screen(self):
        # 10 秒里:第 2-6 秒空转且有怪(4s),第 7-8 秒空转但没怪(不计)
        rows = aseek.parse([line(1, mobs=1, can_atk=True)]
                           + [line(s, mobs=1) for s in range(2, 7)]
                           + [line(7), line(8)]
                           + [line(9, mobs=1, can_atk=True), line(11, mobs=1, can_atk=True)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['C_ratio'], 4.0 / 10.0, places=3)

    def test_D_is_share_of_attacking_ticks(self):
        rows = aseek.parse([line(1, can_atk=True), line(2), line(3, can_atk=True), line(4)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['D_ratio'], 0.5, places=3)

    def test_E_reports_tick_interval_tail(self):
        rows = aseek.parse([line(1), line(2), line(3), line(9)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['E_max'], 6.0, places=2)


if __name__ == '__main__':
    unittest.main()
