import unittest
from unittest.mock import MagicMock, patch

import cv2

from src.task.WarriorDebugTask import DEFAULT_CONFIG, WarriorDebugTask

FRAME = 'screenshots/test_frames/training_ground_full_2560x1440.png'


def make_task(**cfg_overrides):
    task = WarriorDebugTask.__new__(WarriorDebugTask)
    task.config = {**DEFAULT_CONFIG, **cfg_overrides}
    task.info = {}
    task.capture_config = None
    task._app = None  # 无 GUI:get_overlay_view 返回 None,安全降级
    task._reset_state()
    task.send_key = MagicMock()
    task.stop_farming = MagicMock()
    task.log_warning = MagicMock()
    task.log_info = MagicMock()
    task.get_global_config = MagicMock(return_value={})
    return task


def run_with_frame(task, mobs=None):
    """以存档帧驱动一次 run();mobs 不为 None 时替换 find_mobs 返回值。"""
    frame_p = patch.object(WarriorDebugTask, 'frame',
                           new=property(lambda self: cv2.imread(FRAME)))
    patches = [frame_p, patch('time.time', return_value=100.0)]
    if mobs is not None:
        patches.append(patch.object(WarriorDebugTask, 'find_mobs', return_value=mobs))
    else:
        patches.append(patch.object(WarriorDebugTask, 'find_mobs', return_value=[]))
    for p in patches:
        p.start()
    try:
        task.run()
    finally:
        for p in patches:
            p.stop()


class Box:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


class TestWarriorDebugOffline(unittest.TestCase):

    def test_switch_off_does_nothing(self):
        """调试开关关 → 不定位、不画框。"""
        task = make_task(**{'调试开关': False, '角色名': 'Yufeng咕咕'})
        with patch.object(WarriorDebugTask, '_draw_debug') as draw:
            run_with_frame(task)
            draw.assert_not_called()

    def test_no_character_name_requests_config(self):
        """角色名空 → 提示填写,不定位。"""
        task = make_task(**{'调试开关': True, '角色名': ''})
        with patch('src.task.WarriorDebugTask.anchor.find_anchor') as find:
            run_with_frame(task)
            find.assert_not_called()
            self.assertIsNone(task._anchor)

    def test_first_run_locate_anchor_and_draw(self):
        """首次:锚点定位成功 → 画框(带 mobs=[])并记录锚点。"""
        task = make_task(**{'调试开关': True, '角色名': 'Yufeng咕咕'})
        with patch('src.task.WarriorDebugTask.anchor.find_anchor', return_value=(1200, 700)):
            with patch.object(WarriorDebugTask, '_draw_debug') as draw:
                run_with_frame(task)
                draw.assert_called_once()
                _, kwargs = draw.call_args
                self.assertEqual(kwargs['mobs'], [])
                self.assertEqual(kwargs['facing'], 'RIGHT')  # 默认朝向
        self.assertEqual(task._anchor, (1200, 700))

    def test_anchor_miss_requests_visible(self):
        """首次定位失败 → 提示未找到名字牌,不画框。"""
        task = make_task(**{'调试开关': True, '角色名': 'Yufeng咕咕'})
        with patch('src.task.WarriorDebugTask.anchor.find_anchor', return_value=None):
            with patch.object(WarriorDebugTask, '_draw_debug') as draw:
                run_with_frame(task)
                draw.assert_not_called()
        self.assertIsNone(task._anchor)

    def test_mob_in_zone_turns_red(self):
        """怪脚底入攻击区 → in_zone=True(变色)。"""
        task = make_task(**{'调试开关': True, '角色名': 'Yufeng咕咕'})
        task._anchor = (1280, 700)
        task._facing = 'RIGHT'
        # 身体中心 = (1280, 790);攻击区 RIGHT 120px 高 200 → x∈[1280,1400] y∈[690,890]
        mob = Box(1300, 700, 40, 40)  # 脚底 (1320, 740) 在区内
        with patch.object(WarriorDebugTask, '_draw_debug') as draw:
            run_with_frame(task, mobs=[mob])
            _, kwargs = draw.call_args
            self.assertTrue(kwargs['in_zone'])

    def test_mob_outside_zone_stays_blue(self):
        """怪在攻击区外(含背面)→ in_zone=False。"""
        task = make_task(**{'调试开关': True, '角色名': 'Yufeng咕咕'})
        task._anchor = (1280, 700)
        task._facing = 'RIGHT'
        mob = Box(1000, 700, 40, 40)  # 脚底 (1020, 740) 在区外(背后)
        with patch.object(WarriorDebugTask, '_draw_debug') as draw:
            run_with_frame(task, mobs=[mob])
            _, kwargs = draw.call_args
            self.assertFalse(kwargs['in_zone'])

    def test_facing_auto_follows_anchor_movement(self):
        """自动朝向:锚点右移 → RIGHT;左移 → LEFT。"""
        task = make_task(**{'调试开关': True, '角色名': 'Yufeng咕咕', '朝向': '自动'})
        task._anchor = (1280, 700)
        task._facing = 'LEFT'
        # 右移 30px → 翻转 RIGHT
        self.assertEqual(task._auto_facing((1310, 700)), 'RIGHT')
        # 左移 30px → 翻转 LEFT
        self.assertEqual(task._auto_facing((1250, 700)), 'LEFT')
        # 小位移(噪声)→ 保持
        self.assertEqual(task._auto_facing((1283, 700)), 'LEFT')

    def test_throttle_skips_second_run(self):
        """刷新间隔内第二次 run 跳过(节流)。"""
        task = make_task(**{'调试开关': True, '角色名': 'Yufeng咕咕', '调试刷新间隔(秒)': 0.3})
        task._anchor = (1280, 700)
        task._last_draw = 100.0  # now=100.0,间隔未到 → 跳过
        with patch.object(WarriorDebugTask, '_draw_debug') as draw:
            run_with_frame(task)
            draw.assert_not_called()


if __name__ == '__main__':
    unittest.main()
