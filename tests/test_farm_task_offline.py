import unittest
from unittest.mock import MagicMock, call, patch

import cv2

from src.task.MapleFarmTask import DEFAULT_CONFIG, MapleFarmTask

FRAME = 'screenshots/test_frames/training_ground_full_2560x1440.png'
KEYS = {'攻击键': 'shift', '血药键': 'home', '蓝药键': 'insert',
        '回城卷键(可留空)': '', '拾取键': 'z'}


def make_task(**cfg_overrides):
    """config 直接取自模块级 DEFAULT_CONFIG,与 __init__ 同源,
    后续任务新增配置键/状态时本测试不再需要手工同步。"""
    task = MapleFarmTask.__new__(MapleFarmTask)  # 绕过框架 __init__
    task.config = {**DEFAULT_CONFIG, 'Buff键位': '', '药水耗尽保护': False, **cfg_overrides}
    task._reset_state()
    task.send_key = MagicMock()
    task.stop_farming = MagicMock()
    task.log_warning = MagicMock()
    task.get_global_config = MagicMock(return_value=dict(KEYS))
    return task


def run_with_frame(task, hp=None):
    """以存档帧驱动一次 run();hp 不为 None 时替换血条读数。"""
    frame_p = patch.object(MapleFarmTask, 'frame',
                           new=property(lambda self: cv2.imread(FRAME)))
    patches = [frame_p, patch('time.time', return_value=100.0)]
    if hp is not None:
        patches.append(patch('src.task.MapleFarmTask.bars.read_hp', return_value=hp))
    for p in patches:
        p.start()
    try:
        task.run()
    finally:
        for p in patches:
            p.stop()


class TestFarmTaskOffline(unittest.TestCase):

    def test_full_hp_attacks_only(self):
        task = make_task()
        run_with_frame(task)
        self.assertIn(call('shift'), task.send_key.call_args_list)
        task.stop_farming.assert_not_called()

    def test_low_hp_no_scroll_potions_then_stops(self):
        task = make_task()
        run_with_frame(task, hp=0.2)
        self.assertIn(call('home'), task.send_key.call_args_list)  # 先喝血
        task.stop_farming.assert_called_once()                      # 再停(未配回城卷)

    def test_low_hp_with_scroll_potions_scrolls_stops(self):
        task = make_task()
        task.get_global_config = MagicMock(return_value={**KEYS, '回城卷键(可留空)': 't'})
        run_with_frame(task, hp=0.2)
        calls = task.send_key.call_args_list
        self.assertIn(call('home'), calls)                          # 先喝血
        self.assertIn(call('t', after_sleep=2), calls)              # 再回城
        self.assertLess(calls.index(call('home')), calls.index(call('t', after_sleep=2)))
        task.stop_farming.assert_called_once()

    def test_dead_three_frames_stops(self):
        task = make_task(**{'死亡确认帧数': 3})
        for _ in range(3):
            run_with_frame(task, hp=0.0)
        task.stop_farming.assert_called_once()

    def test_dead_counter_resets_on_recovery(self):
        task = make_task(**{'死亡确认帧数': 3})
        run_with_frame(task, hp=0.0)
        run_with_frame(task, hp=0.0)
        run_with_frame(task, hp=0.9)   # 回血,计数清零
        run_with_frame(task, hp=0.0)
        task.stop_farming.assert_not_called()

    def test_detect_mode_attacks_when_mob_in_zone(self):
        task = make_task(**{'攻击模式': '检测'})
        mob = MagicMock(x=1200, y=700, width=60, height=50)  # 中心 (1230,725),在默认攻击区内
        task.find_mobs = MagicMock(return_value=[mob])
        run_with_frame(task)
        self.assertIn(call('shift'), task.send_key.call_args_list)

    def test_detect_mode_idles_when_no_mob(self):
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[])
        run_with_frame(task)
        task.send_key.assert_not_called()  # 无怪停手省蓝

    def test_detect_mode_idles_when_mob_outside_zone(self):
        task = make_task(**{'攻击模式': '检测'})
        far = MagicMock(x=10, y=10, width=60, height=50)  # 左上角,攻击区外
        task.find_mobs = MagicMock(return_value=[far])
        run_with_frame(task)
        task.send_key.assert_not_called()


if __name__ == '__main__':
    unittest.main()
