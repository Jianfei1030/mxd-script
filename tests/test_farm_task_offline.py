import unittest
from unittest.mock import MagicMock, call, patch

import cv2

from src.detect.anchor import Anchor as MapleAnchor
from src.task.MapleFarmTask import (DEFAULT_CONFIG, TURN_TAP_SECONDS, MapleFarmTask)

FRAME = 'screenshots/test_frames/training_ground_full_2560x1440.png'
KEYS = {'攻击键': 'shift', '血药键': 'home', '蓝药键': 'insert',
        '回城卷键(可留空)': '', '拾取键': 'z', '宠物食物键(可留空)': 'q',
        '椅子键(可留空)': 'r', '左移键': 'left', '右移键': 'right'}


def make_task(**cfg_overrides):
    """config 直接取自模块级 DEFAULT_CONFIG,与 __init__ 同源,
    后续任务新增配置键/状态时本测试不再需要手工同步。"""
    task = MapleFarmTask.__new__(MapleFarmTask)  # 绕过框架 __init__
    task.config = {**DEFAULT_CONFIG, 'Buff键位': '', '药水耗尽保护': False, **cfg_overrides}
    task.info = {}
    task.capture_config = None
    task._reset_state()
    task.send_key = MagicMock()
    task.send_key_down = MagicMock()
    task.send_key_up = MagicMock()
    task.stop_farming = MagicMock()
    task.log_warning = MagicMock()
    task.log_error = MagicMock()
    task.log_info = MagicMock()
    task.find_mobs = MagicMock(return_value=[])
    task.get_global_config = MagicMock(return_value=dict(KEYS))
    return task


def run_with_frame(task, hp=None, mp=None, exp=None, now=100.0):
    """以存档帧驱动一次 run();hp/mp/exp 不为 None 时替换对应读数。
    now 可推进模拟时间(默认 100.0,与旧调用兼容)。"""
    frame_p = patch.object(MapleFarmTask, 'frame',
                           new=property(lambda self: cv2.imread(FRAME)))
    patches = [frame_p, patch('time.time', return_value=now)]
    if hp is not None:
        patches.append(patch('src.task.MapleFarmTask.bars.read_hp', return_value=hp))
    if mp is not None:
        patches.append(patch('src.task.MapleFarmTask.bars.read_mp', return_value=mp))
    if exp is not None:
        patches.append(patch('src.task.MapleFarmTask.bars.read_exp', return_value=exp))
    for p in patches:
        p.start()
    try:
        task.run()
    finally:
        for p in patches:
            p.stop()


class TestFarmTaskOffline(unittest.TestCase):

    def test_full_hp_attacks_only(self):
        task = make_task(**{'攻击模式': '定频'})
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

    def test_working_potion_under_combat_not_stopped(self):
        """回归(连续打怪喝药无效误停):药水在起效但回血渐进(<1%/0.1s),
        战斗中 HP 徘徊在阈值下。旧代码按帧判定,5 帧(0.5s)就误停;
        修复后按 1s 窗口判定,每窗口喝一次,不应停任务。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False})
        # 10Hz 连续帧,HP 每 1s 涨 1.5%(药在起效但还没过阈值),持续 4 个窗口
        hp_schedule = [0.65] * 10 + [0.665] * 10 + [0.68] * 10 + [0.695] * 10
        for t, hp in enumerate(hp_schedule):
            run_with_frame(task, hp=hp, now=100.0 + t * 0.1)
        task.stop_farming.assert_not_called()
        # 每个窗口恰好喝一次,不 10Hz 连按
        self.assertEqual(task.send_key.call_args_list.count(call('home')), 4)

    def test_broken_potion_still_stops(self):
        """对照:药水真失效(HP 纹丝不动),喝 5 个窗口仍无起效 → 停任务。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False})
        for t in range(60):  # 6s,HP 恒 0.65
            run_with_frame(task, hp=0.65, now=100.0 + t * 0.1)
            if task.stop_farming.call_args_list:
                break
        task.stop_farming.assert_called_once_with('连续喝药无效')

    def test_first_drink_not_judged_ineffective(self):
        """血掉到阈值下的第一帧就喝药,但这一帧没有可对比的基线,
        不许记"无效"——药效还没出来,判了必误判。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False})
        run_with_frame(task, hp=0.60)
        self.assertIn(call('home'), task.send_key.call_args_list)
        self.assertEqual(task._hp_streak, 0)

    def test_potion_switch_off_never_drinks_hp(self):
        """关开关:HP 低于喝血阈值 → 不按血药键,也不触发无效检测停止。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False, '喝药开关': False})
        run_with_frame(task, hp=0.5)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('home', sent)
        task.stop_farming.assert_not_called()

    def test_potion_switch_off_never_drinks_mp(self):
        """关开关:MP 低于喝蓝阈值 → 不按蓝药键。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False, '喝药开关': False})
        run_with_frame(task, hp=0.9, mp=0.2)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('insert', sent)
        task.stop_farming.assert_not_called()

    def test_potion_switch_off_emergency_still_scrolls(self):
        """关开关 + HP 触保命血线:不按血药键,但回城卷与停任务照常。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False, '喝药开关': False})
        task.get_global_config = MagicMock(return_value={**KEYS, '回城卷键(可留空)': 't'})
        run_with_frame(task, hp=0.2)
        calls = task.send_key.call_args_list
        self.assertNotIn(call('home'), calls)
        self.assertIn(call('t', after_sleep=2), calls)
        task.stop_farming.assert_called_once_with('低血保命')

    def test_potion_switch_on_drinks_by_default(self):
        """默认(开关开):HP 低于阈值 → 照常喝药,行为不变。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False})
        run_with_frame(task, hp=0.5)
        self.assertIn(call('home'), task.send_key.call_args_list)
        task.stop_farming.assert_not_called()

    def test_potion_switch_off_on_toggle_resets_window_state(self):
        """开→关→开切换后,残留的喝药窗口状态不触发「连续喝药无效」误停。

        回归:关开关时 _hp_streak/_hp_at_press/_last_hp_potion_press 冻结,
        重新打开后第一次喝药用切换前的旧基线判定,HP 只降不涨必然累计无效次数,
        若切换前 streak 已接近上限则切换回来第一个有效药水立刻误停。
        修复后 off 状态完全无状态:切换回来第一次喝药走哨兵路径(只记基线,不判无效)。
        """
        task = make_task(**{'攻击模式': '定频', '走位开关': False})
        # 开状态把 streak 推到 4(差 1 触发停止)
        for t in range(100, 105):
            run_with_frame(task, hp=0.5, now=float(t))
        self.assertEqual(task._hp_streak, 4)
        # 关一帧:状态应被清空(修复点)
        task.config['喝药开关'] = False
        run_with_frame(task, hp=0.5, now=105.0)
        # 重新打开,第一次喝药不应误判无效
        task.config['喝药开关'] = True
        run_with_frame(task, hp=0.5, now=106.0)
        task.stop_farming.assert_not_called()

    def test_potion_switch_off_never_ocrs_slot(self):
        """关开关:不 OCR 快捷栏(药水耗尽保护整段跳过)。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False, '喝药开关': False,
                            '药水耗尽保护': True})
        with patch('src.task.MapleFarmTask.potions.read_slot_count') as ocr:
            run_with_frame(task, hp=0.9, mp=0.9, now=1000.0)
        ocr.assert_not_called()

    def test_detect_mode_attacks_when_mob_in_zone(self):
        task = make_task(**{'攻击模式': '检测'})
        mob = MagicMock(x=1200, y=700, width=60, height=50)  # 中心 (1230,725),在默认攻击区内
        task.find_mobs = MagicMock(return_value=[mob])
        run_with_frame(task)
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])  # 长按接管

    def test_detect_mode_idles_when_no_mob(self):
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[])
        run_with_frame(task)
        # 无怪停手省蓝:不按攻击键(闲置坐椅会按一次椅子键 r,见 TestSitChair)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('shift', sent)

    def test_detect_mode_idles_when_mob_outside_zone(self):
        task = make_task(**{'攻击模式': '检测'})
        far = MagicMock(x=10, y=10, width=60, height=50)  # 左上角,攻击区外且不同层
        task.find_mobs = MagicMock(return_value=[far])
        run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('shift', sent)  # 不按攻击键
        self.assertNotIn('left', sent)   # 不同层怪不追
        self.assertNotIn('right', sent)

    def test_detect_mode_turns_then_attacks_when_mob_behind(self):
        """怪在面朝反侧 → 先轻点方向键转向再攻击,并更新 _facing。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'LEFT'
        # 固定锚点:名字牌 (1280, 800) → 身体中心 (1280, 710),默认攻击区 x∈[980,1580]
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 中心 (1530, 725),在身体右侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertIn(call('right', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])  # 转向后长按攻击
        self.assertEqual(task._facing, 'RIGHT')

    def test_detect_mode_attacks_without_turn_when_facing_mob(self):
        """已面朝怪所在侧 → 不转向直接攻击,_facing 不变。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 右侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])
        self.assertEqual(task._facing, 'RIGHT')

    def test_detect_mode_unknown_facing_turns_to_mob_then_attacks(self):
        """朝向未知 → 按怪所在侧转向再攻击,自动确定基线朝向。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 右侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertIn(call('right', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])  # 转向后长按攻击
        self.assertEqual(task._facing, 'RIGHT')

    def test_detect_mode_turns_left_when_mob_on_left(self):
        """怪在左侧 → 按左转向再攻击。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=960, y=700, width=60, height=50)  # 中心 (990, 725),区内左侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertIn(call('left', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])  # 转向后长按攻击
        self.assertEqual(task._facing, 'LEFT')

    def test_turn_restarts_walk_countdown(self):
        """转向本身就是"活动":走位倒计时从头算——即使本拍到点也不走位,
        之后 120s 内不再走。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0  # 走位早已到点
        task._facing = 'LEFT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 右侧,需转向
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertEqual(task._last_walk, 100.0)  # 转向重置了计时
        walk_calls = [c for c in task.send_key.call_args_list if c.kwargs.get('down_time') == 0.4]
        self.assertEqual(walk_calls, [])  # 本拍不再走位

    def test_attack_without_turn_keeps_walk_timer(self):
        """已面朝怪 → 只攻击不转向,走位计时不受影响。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 右侧,不需转向
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertEqual(task._last_walk, -1000.0)  # 没转向就不重置

    def test_seek_walks_toward_same_floor_mob_outside_zone(self):
        """寻怪:同层怪在攻击区外 → 长按方向键朝怪走(按下不松),重置走位计时。
        (角色名留空 → 锚点 fallback 画面中心 (1280,720),怪脚底 730 差 10 ≤ 容差 60 → 同层)"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0  # 走位早已到点:若寻怪不重置,这里会触发防挂机走位
        task._facing = 'LEFT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=2000, y=680, width=60, height=50)  # 中心 (2030,705),脚底 (2030,730)
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertEqual(task.send_key_down.call_args_list, [call('right')])
        task.send_key_up.assert_not_called()
        self.assertEqual(task._seek_key, '右移键')
        self.assertEqual(task._seek_dir, 'right')
        self.assertEqual(task._facing, 'RIGHT')
        self.assertEqual(task._last_walk, 100.0)  # 寻怪=活动,防挂机走位顺延

    def test_seek_walks_left_toward_mob_on_left(self):
        """怪在左侧远处 → 长按左走。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=300, y=680, width=60, height=50)  # 中心 (330,705),脚底 (330,730)
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertIn(call('left'), task.send_key_down.call_args_list)
        self.assertEqual(task._seek_dir, 'left')
        self.assertEqual(task._facing, 'LEFT')

    def test_seek_ignores_other_floor_mob(self):
        """不同层的怪不追(脚底高度差超容差)→ 不动。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=2000, y=500, width=60, height=50)  # 脚底 (2030,550),差 170 > 60
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        task.send_key.assert_not_called()
        self.assertIsNone(task._seek_dir)

    def test_seek_switch_off_idles(self):
        """寻怪开关关 → 同层远怪也不动(不按方向键;闲置坐椅会按椅子键)。"""
        task = make_task(**{'攻击模式': '检测', '寻怪开关': False})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            mob = MagicMock(x=2000, y=680, width=60, height=50)
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)

    def test_seek_stops_when_mob_enters_zone(self):
        """寻怪途中怪从同侧进攻击区 → 停追,原地攻击(已面朝,不转向),松开方向键。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task)  # 第一拍:同层远怪 → 寻怪右走
            self.assertEqual(task._seek_dir, 'right')
            task.send_key.reset_mock()
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task, now=102.0)  # 第二拍(隔 2s ≥ 攻击间隔):怪从右侧进区
        self.assertIsNone(task._seek_dir)
        self.assertEqual(task.send_key.call_args_list, [])  # 攻击键走长按,不轻点
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])  # 接战立即长按
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])  # 松寻怪键
        self.assertIsNone(task._seek_key)

    def test_seek_refresh_switches_direction_at_interval(self):
        """寻怪激活时按独立刷新间隔(0.4s)重算方向,不必等攻击间隔(1.0s)。
        0.3s 时方向保持(刷新未到),0.5s 时怪换到另一侧 → 换向:松旧键按新键。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task)  # 完整拍:同层远怪右 → 寻怪右,长按右
            self.assertEqual(task._seek_dir, 'right')
            task.send_key_down.reset_mock()
            task.send_key_up.reset_mock()
            task.find_mobs = MagicMock(return_value=[MagicMock(x=300, y=680, width=60, height=50)])
            run_with_frame(task, now=100.3)  # 0.3s < 刷新间隔 0.4 → 方向保持
            self.assertEqual(task._seek_dir, 'right')
            self.assertEqual(task.send_key_down.call_args_list, [call('right')])  # 重按保持
            self.assertEqual(task.send_key_up.call_args_list, [])
            run_with_frame(task, now=100.5)  # 0.5s ≥ 刷新间隔 → 换向
        self.assertEqual(task._seek_dir, 'left')
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])   # 松旧键
        self.assertEqual(task.send_key_down.call_args_list, [call('right'), call('left')])

    def test_seek_refresh_engages_when_mob_enters_zone(self):
        """寻怪中怪进攻击区 → 刷新拍立即停追接战,不必等下一完整检测拍。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task)
            self.assertEqual(task._seek_dir, 'right')
            task.send_key.reset_mock()
            task.send_key_down.reset_mock()
            task.send_key_up.reset_mock()
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task, now=100.5)  # 刷新拍(完整拍 1.0s 未到)
        self.assertIsNone(task._seek_dir)
        self.assertEqual(task.send_key.call_args_list, [])  # 不轻点
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])  # 立即长按攻击
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])    # 松寻怪键

    def test_seek_refresh_holds_attack_regardless_of_interval(self):
        """接战不留空档:刷新拍怪进区时攻击长按立即接管——即使距上次攻击
        不到 攻击间隔(旧版这里等节流,会出现 1.5s 空打/发呆)。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=MapleAnchor(1280, 800, 130)):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task)
            self.assertEqual(task._seek_dir, 'right')
            task.send_key.reset_mock()
            task.send_key_down.reset_mock()
            task.send_key_up.reset_mock()
            task._last_attack = 100.4  # 0.1s 前攻击过,1.0s 节流未到
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task, now=100.5)
        self.assertIsNone(task._seek_dir)
        self.assertEqual(task.send_key_down.call_args_list, [call('shift')])  # 立即长按,不等节流
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])    # 松寻怪键

    def test_do_walk_unknown_facing_random_left_first(self):
        """朝向未知(自动+首次走位):随机一侧出、反方向回,采纳实际朝向为基线。"""
        task = make_task(**{'走位持续时间(秒)': 0.4})
        with patch('src.task.farm_logic.random.choice', return_value='left'):
            task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('left', down_time=0.4), call('right', down_time=0.4)])
        self.assertEqual(task._facing, 'RIGHT')  # 走完面朝第二段方向

    def test_do_walk_unknown_facing_random_right_first(self):
        task = make_task(**{'走位持续时间(秒)': 0.4})
        with patch('src.task.farm_logic.random.choice', return_value='right'):
            task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('right', down_time=0.4), call('left', down_time=0.4)])
        self.assertEqual(task._facing, 'LEFT')

    def test_do_walk_facing_left_walks_right_then_left(self):
        """朝向已知 LEFT → 先向右出、再向左回,结束时仍朝左(走位不翻转朝向)。"""
        task = make_task(**{'走位持续时间(秒)': 0.4})
        task._facing = 'LEFT'
        task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('right', down_time=0.4), call('left', down_time=0.4)])
        self.assertEqual(task._facing, 'LEFT')

    def test_do_walk_facing_right_walks_left_then_right(self):
        task = make_task(**{'走位持续时间(秒)': 0.4})
        task._facing = 'RIGHT'
        task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('left', down_time=0.4), call('right', down_time=0.4)])
        self.assertEqual(task._facing, 'RIGHT')

    def test_do_walk_config_left_overrides_tracked_facing(self):
        """配置 朝向=左 显式优先:即使已跟踪 RIGHT 也按左走位,并更新 _facing。"""
        task = make_task(**{'走位持续时间(秒)': 0.4, '朝向': '左'})
        task._facing = 'RIGHT'
        task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('right', down_time=0.4), call('left', down_time=0.4)])
        self.assertEqual(task._facing, 'LEFT')

    def test_do_walk_config_right_with_unknown_facing(self):
        """配置 朝向=右 + 从未走位过(_facing=None):按右走位,不依赖随机。"""
        task = make_task(**{'走位持续时间(秒)': 0.4, '朝向': '右'})
        task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('left', down_time=0.4), call('right', down_time=0.4)])
        self.assertEqual(task._facing, 'RIGHT')

    def test_walk_switch_off_never_walks(self):
        task = make_task(**{'走位开关': False, '攻击模式': '定频'})
        task._last_walk = -1000.0
        run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)

    def test_walk_fixed_mode_walks_when_due(self):
        task = make_task(**{'攻击模式': '定频', '走位持续时间(秒)': 0.4})
        task._last_walk = -1000.0
        with patch('src.task.farm_logic.random.choice', return_value='left'):
            run_with_frame(task)
        sent = [c for c in task.send_key.call_args_list if c.args and c.args[0] in ('left', 'right')]
        self.assertEqual(sent, [call('left', down_time=0.4), call('right', down_time=0.4)])
        self.assertEqual(task._last_walk, 100.0)  # run_with_frame 把 time.time() 固定在 100.0

    def test_walk_detect_mode_defers_when_mob_present(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0
        mob = MagicMock(x=1200, y=700, width=60, height=50)  # 中心在默认攻击区内
        task.find_mobs = MagicMock(return_value=[mob])
        run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertTrue(task._last_mob_present)
        self.assertEqual(task._last_walk, -1000.0)  # 未更新,顺延到下一次判定

    def test_walk_detect_mode_walks_when_no_mob(self):
        task = make_task(**{'攻击模式': '检测', '走位持续时间(秒)': 0.4})
        task._last_walk = -1000.0
        task.find_mobs = MagicMock(return_value=[])
        with patch('src.task.farm_logic.random.choice', return_value='right'):
            run_with_frame(task)
        sent = [c for c in task.send_key.call_args_list if c.args and c.args[0] in ('left', 'right')]
        self.assertEqual(sent, [call('right', down_time=0.4), call('left', down_time=0.4)])
        self.assertFalse(task._last_mob_present)
        self.assertEqual(task._last_walk, 100.0)

    def test_walk_not_due_yet_skips(self):
        task = make_task(**{'攻击模式': '定频'})
        task._last_walk = 99.0  # 100.0-99.0=1s < 默认 120s 间隔,未到
        run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertEqual(task._last_walk, 99.0)  # 未变

    def test_walk_detect_mode_no_walk_before_first_detection(self):
        """启动后一次检测都还没跑过(_last_mob_present 仍是初始值 None),
        即使到了走位时间点也不许走——没有新鲜的"有没有怪"判断就贸然移动,
        可能正好撞进怪堆。这里把 _last_detect 设成很接近 now,让本拍的检测
        本身也不触发(should_attack 判定攻击间隔未到),模拟"两次检测之间、
        且从未检测过"的窗口。

        注意用的是 _last_detect 不是 _last_attack:合并 feat/attack-zone-mob-gating 后,
        检测模式是否跑检测这一步单独用 _last_detect 节流(修了旧代码"无怪时 10Hz 每拍
        都重跑检测"的缺陷),_last_attack 现在只在真的发出攻击键那一刻才更新,不再
        control 是否跑检测——设 _last_attack 无法阻止这一拍触发检测。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0
        task._last_detect = 99.9  # 100.0-99.9=0.1s < 默认攻击间隔 1.5s,本拍不跑检测
        task.find_mobs = MagicMock()
        run_with_frame(task)
        task.find_mobs.assert_not_called()
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertIsNone(task._last_mob_present)


    def test_re_enable_resets_stall_timer(self):
        """停止(经验停滞)后通过框架 enable() 重新启用,不应立即再次停止。"""
        task = make_task(**{'攻击模式': '定频'})
        task._executor = MagicMock()  # enable() 通过 executor property 访问
        task._enabled = True
        # 模拟已经挂机很久,经验条无变化
        task._last_exp = 0.5
        task._last_exp_gain_time = -1000.0  # 远超 10 分钟上限
        run_with_frame(task, exp=0.5)
        task.stop_farming.assert_called_once()
        task.stop_farming.reset_mock()
        task.send_key.reset_mock()
        # 框架禁用后再启用(用户日常点开关)
        task._enabled = False
        task.enable()
        self.assertTrue(task._enabled)
        # 重新跑一帧:计时器已复位,不应秒停,且应继续攻击
        run_with_frame(task)
        task.stop_farming.assert_not_called()
        self.assertIn(call('shift'), task.send_key.call_args_list)


class TestSeekMove(unittest.TestCase):
    """寻怪长按移动(_do_seek_move 直接测,无帧依赖)。

    修复回归:旧版每拍按下又松开(按 0.1s),刷新拍的 OCR+YOLO 阻塞期间键没按住,
    追怪时走走停停"一下一下";改为长按(按下不松)后,检测阻塞不再打断行走。
    """

    def test_holds_key_never_released_while_chasing(self):
        """追怪中每拍重按保持、从不松开:两拍之间没有 key_up,不打断行走。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task._do_seek_move(task.config, KEYS)  # 下一拍:键保持,仅重按补发
        self.assertEqual(task.send_key_down.call_args_list, [call('right'), call('right')])
        task.send_key_up.assert_not_called()
        self.assertEqual(task._seek_key, '右移键')
        self.assertEqual(task._facing, 'RIGHT')

    def test_direction_flip_releases_old_holds_new(self):
        """换向(怪从另一侧靠近):先松旧键再按新键。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task._seek_dir = 'left'
        task._do_seek_move(task.config, KEYS)
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])
        self.assertEqual(task.send_key_down.call_args_list, [call('right'), call('left')])
        self.assertEqual(task._seek_key, '左移键')
        self.assertEqual(task._facing, 'LEFT')

    def test_seek_ends_releases_key(self):
        """怪进攻击区/无同层怪(_seek_dir 置 None)→ 松开按着的方向键。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task._seek_dir = None
        task._do_seek_move(task.config, KEYS)
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])
        self.assertIsNone(task._seek_key)

    def test_switch_off_releases_held_key(self):
        """追怪途中关掉寻怪开关 → 松开长按的方向键。"""
        task = make_task(**{'寻怪开关': False})
        task._seek_dir = 'right'
        task._seek_key = '右移键'
        task._do_seek_move(task.config, KEYS)
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])
        self.assertIsNone(task._seek_key)

    def test_switch_off_idle_does_nothing(self):
        task = make_task(**{'寻怪开关': False})
        task._do_seek_move(task.config, KEYS)
        task.send_key_down.assert_not_called()
        task.send_key_up.assert_not_called()

    def test_no_key_when_not_seeking(self):
        task = make_task()
        task._do_seek_move(task.config, KEYS)
        task.send_key_down.assert_not_called()
        task.send_key_up.assert_not_called()

    def test_executor_pause_releases_held_key(self):
        """F9 暂停(executor_paused 信号)时松开长按的方向键:
        暂停后 run() 不再被调用,不松键角色会一直走下去。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task._on_executor_paused(True)
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])
        self.assertIsNone(task._seek_key)
        # 恢复:下一拍重新按下
        task._do_seek_move(task.config, KEYS)
        self.assertEqual(task.send_key_down.call_args_list, [call('right'), call('right')])

    def test_pause_resume_signal_false_does_nothing(self):
        """暂停信号带 False(恢复)不松键。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task._on_executor_paused(False)
        task.send_key_up.assert_not_called()
        self.assertEqual(task._seek_key, '右移键')

    def test_disable_releases_held_key(self):
        """停任务(框架 disable)→ 松开长按的方向键,角色不会在任务停止后继续走。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task._executor = MagicMock()
        task.disable()
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])
        self.assertIsNone(task._seek_key)

    def test_release_failure_still_clears_state(self):
        """松键失败(窗口不可点/交互异常)不抛出、状态仍清空,避免停任务流程被卡死。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task.send_key_up = MagicMock(side_effect=RuntimeError('key up 失败'))
        task._on_executor_paused(True)  # 不应抛出
        self.assertIsNone(task._seek_key)


class TestPetFeed(unittest.TestCase):
    """喂宠物(_do_pet_feed 直接测,无帧依赖)。"""

    def test_feed_presses_key_when_due(self):
        """到 15 分钟 → 按宠物食物键,记录时刻。"""
        task = make_task()
        task._do_pet_feed(task.config, KEYS, 900.0)
        self.assertEqual(task.send_key.call_args_list, [call('q')])
        self.assertEqual(task._last_pet_feed, 900.0)

    def test_feed_not_due_skips(self):
        task = make_task()
        task._last_pet_feed = 899.0
        task._do_pet_feed(task.config, KEYS, 900.0)  # 距上次仅 1s < 900s
        task.send_key.assert_not_called()
        self.assertEqual(task._last_pet_feed, 899.0)

    def test_feed_switch_off_skips(self):
        task = make_task(**{'喂宠物开关': False})
        task._do_pet_feed(task.config, KEYS, 900.0)
        task.send_key.assert_not_called()

    def test_feed_unbound_key_keeps_pending(self):
        """宠物食物键留空(未绑定)→ 不按键也不推进计时:用户在设置页绑好键后
        立即补喂,不用再等一个完整间隔。"""
        task = make_task()
        keys = {**KEYS, '宠物食物键(可留空)': ''}
        task._do_pet_feed(task.config, keys, 900.0)
        task.send_key.assert_not_called()
        self.assertEqual(task._last_pet_feed, 0.0)


class TestAttackHold(unittest.TestCase):
    """检测模式攻击长按(_do_attack_hold 直接测,无帧依赖)。

    修复目标:旧版每 攻击间隔(秒) 轻点一下攻击键(20ms),动画放完就站着等
    下一拍 → "每次打完愣一下";长按后游戏按动画速度连续挥砍,不留空档。
    定频模式不在这里管(无"有没有怪"概念,仍按 攻击间隔 定时轻点)。
    """

    def test_holds_attack_never_released_while_mob_in_zone(self):
        """区内有怪 → 按下攻击键并保持,两拍之间不松键。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack_hold(task.config, KEYS)
        task._do_attack_hold(task.config, KEYS)  # 下一拍:保持 + 重按补发
        self.assertEqual(task.send_key_down.call_args_list, [call('shift'), call('shift')])
        task.send_key_up.assert_not_called()
        self.assertTrue(task._attack_held)

    def test_release_when_mob_leaves_zone(self):
        """怪离开攻击区(或打死)→ 松开攻击键。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack_hold(task.config, KEYS)
        task._last_mob_present = False
        task._do_attack_hold(task.config, KEYS)
        self.assertEqual(task.send_key_up.call_args_list, [call('shift')])
        self.assertFalse(task._attack_held)

    def test_not_held_before_first_detection(self):
        """启动后还没检测过(_last_mob_present 初始 None)→ 不按攻击键。"""
        task = make_task(**{'攻击模式': '检测'})
        task._do_attack_hold(task.config, KEYS)
        task.send_key_down.assert_not_called()
        task.send_key_up.assert_not_called()

    def test_fixed_mode_releases_held_attack(self):
        """挂机中从检测切到定频 → 松开长按的攻击键(定频仍走定时轻点)。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack_hold(task.config, KEYS)
        task.config['攻击模式'] = '定频'
        task._do_attack_hold(task.config, KEYS)
        self.assertEqual(task.send_key_up.call_args_list, [call('shift')])
        self.assertFalse(task._attack_held)

    def test_pause_releases_attack_key(self):
        """F9 全局暂停 → 松开长按;恢复后下一拍自动重新按下。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack_hold(task.config, KEYS)
        task._on_executor_paused(True)
        self.assertEqual(task.send_key_up.call_args_list, [call('shift')])
        self.assertFalse(task._attack_held)
        task._do_attack_hold(task.config, KEYS)  # 恢复:下一拍重新按下
        self.assertEqual(task.send_key_down.call_args_list, [call('shift'), call('shift')])

    def test_pause_resume_signal_false_does_nothing(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack_hold(task.config, KEYS)
        task.send_key_up.reset_mock()
        task._on_executor_paused(False)
        task.send_key_up.assert_not_called()
        self.assertTrue(task._attack_held)

    def test_disable_releases_attack_key(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack_hold(task.config, KEYS)
        task._executor = MagicMock()
        task.disable()
        self.assertEqual(task.send_key_up.call_args_list, [call('shift')])
        self.assertFalse(task._attack_held)

    def test_release_failure_still_clears_state(self):
        """松键失败(窗口不可点/交互异常)不抛出、状态仍清空,避免停任务流程被卡死。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack_hold(task.config, KEYS)
        task.send_key_up = MagicMock(side_effect=RuntimeError('key up 失败'))
        task._on_executor_paused(True)  # 不应抛出
        self.assertFalse(task._attack_held)


class TestSitChair(unittest.TestCase):
    """坐椅(_do_sit_chair 直接测,无帧依赖)。

    检测模式、区内没怪且没在寻怪(真正站桩闲置)、离上次"忙"(攻击/寻怪/走位)
    超过 坐椅延迟 → 按一次椅子键坐下。坐下后再按一次椅子键会起身,所以同一轮
    闲置只按一次(_sitting 标记);起身不显式按键——怪进区/开始寻怪/走位时,
    长按的攻击键/方向键/走位按键本身会带角色站起来,下一轮闲置由 _mark_busy
    清标记后重新坐下。定频模式不坐:它按攻击间隔定时按键,坐下立刻被带起身。
    """

    def test_sits_when_idle_and_delay_elapsed(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = False
        task._seek_dir = None
        task._last_busy = 100.0
        task._do_sit_chair(task.config, KEYS, 105.0)  # 闲置 5s ≥ 延迟 3s
        self.assertEqual(task.send_key.call_args_list, [call('r')])
        self.assertTrue(task._sitting)

    def test_no_repress_while_sitting(self):
        """同一轮闲置只按一次椅子键——再按一次会起身。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = False
        task._last_busy = 100.0
        task._sitting = True
        task._do_sit_chair(task.config, KEYS, 105.0)
        task.send_key.assert_not_called()

    def test_no_sit_when_mob_in_zone(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_sit_chair(task.config, KEYS, 105.0)
        task.send_key.assert_not_called()
        self.assertFalse(task._sitting)

    def test_no_sit_while_seeking(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = False
        task._seek_dir = 'right'
        task._do_sit_chair(task.config, KEYS, 105.0)
        task.send_key.assert_not_called()

    def test_no_sit_before_delay(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = False
        task._last_busy = 104.5  # 闲置 0.5s < 3s
        task._do_sit_chair(task.config, KEYS, 105.0)
        task.send_key.assert_not_called()
        self.assertFalse(task._sitting)

    def test_no_sit_before_first_detection(self):
        """启动后还没检测过(_last_mob_present 仍是 None)→ 不坐——没有新鲜的
        "有没有怪"判断就贸然坐下,可能正好坐在怪脸上。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = None
        task._last_busy = 100.0
        task._do_sit_chair(task.config, KEYS, 105.0)
        task.send_key.assert_not_called()

    def test_fixed_mode_never_sits(self):
        task = make_task(**{'攻击模式': '定频'})
        task._last_mob_present = False
        task._last_busy = 100.0
        task._do_sit_chair(task.config, KEYS, 105.0)
        task.send_key.assert_not_called()

    def test_switch_off_skips(self):
        task = make_task(**{'攻击模式': '检测', '坐椅开关': False})
        task._last_mob_present = False
        task._last_busy = 100.0
        task._do_sit_chair(task.config, KEYS, 105.0)
        task.send_key.assert_not_called()

    def test_unbound_key_keeps_pending(self):
        """椅子键留空(未绑定)→ 不按键也不置坐椅标记:绑定后立即坐下,不用等
        下一轮"忙→闲"循环。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = False
        task._last_busy = 100.0
        keys = {**KEYS, '椅子键(可留空)': ''}
        task._do_sit_chair(task.config, keys, 105.0)
        task.send_key.assert_not_called()
        self.assertFalse(task._sitting)

    def test_mark_busy_clears_sitting(self):
        """接战/寻怪/走位 = 忙:清坐椅标记并重算延迟——刚坐下就接战时角色被
        长按的攻击键/方向键带起身,下一轮闲置必须重新按键坐下。"""
        task = make_task(**{'攻击模式': '检测'})
        task._sitting = True
        task._mark_busy(105.0)
        self.assertFalse(task._sitting)
        self.assertEqual(task._last_busy, 105.0)


class TestDetectModeAnchor(unittest.TestCase):

    def test_no_char_name_uses_screen_centre(self):
        """角色名留空 → 不跑 OCR,直接用屏幕中心当锚点。"""
        task = make_task(**{'攻击模式': '检测', '角色名': ''})
        with patch('src.task.MapleFarmTask.anchor.find_in_region') as scan:
            run_with_frame(task)
            scan.assert_not_called()

    def test_no_mob_does_not_stop_task(self):
        """用户明确要求:没怪只停手,任务继续跑。"""
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[])
        run_with_frame(task)
        task.send_key.assert_not_called()
        task.stop_farming.assert_not_called()

    def test_detection_is_throttled_when_idle(self):
        """无怪时不许每个 0.1s 触发都重跑检测(缺陷 B)。同一时刻连跑 5 次,只应检测 1 次。"""
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[])
        for _ in range(5):
            run_with_frame(task)
        self.assertEqual(task.find_mobs.call_count, 1)

    def test_window_hit_updates_anchor(self):
        """快通道命中后必须把锚点更新成新值。

        必须先播种旧锚点:_resolve_anchor 的快通道有 `if self._anchor is not None` 前置条件,
        新任务的 _anchor 是 None,不播种的话根本进不去快通道。旧值要与新值不同,
        否则断言分不清"更新了"和"本来就是这个值"。
        """
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1390.0, 905.0)
        task._anchor_time = 100.0
        hit = MapleAnchor(1400.0, 900.0, 128)
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            run_with_frame(task)
        self.assertEqual(task._anchor, (1400.0, 900.0))

    def test_cached_anchor_when_both_channels_miss(self):
        """快通道失灵 + 慢通道被节流 + 锚点未过期 → 沿用上次锚点,不回退画面中心。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '锚点保鲜(秒)': 10})
        task._anchor = (1400.0, 900.0)
        task._anchor_time = 99.0        # 时间被固定在 100.0,锚点年龄 1s,未过期
        task._last_anchor_scan = 99.5   # 距上次扫描 0.5s < 锚点刷新间隔 2s,慢通道被节流
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None) as window, \
                patch('src.task.MapleFarmTask.anchor.find_in_region') as region:
            got, source = task._resolve_anchor(cv2.imread(FRAME), 100.0, task.config)
        self.assertEqual(source, 'cached')
        self.assertEqual((got.x, got.y), (1400.0, 900.0))
        window.assert_called_once()
        region.assert_not_called()

    def test_expired_anchor_falls_back_to_centre(self):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '锚点保鲜(秒)': 5})
        task._anchor = (400.0, 400.0)
        task._anchor_time = 90.0  # run_with_frame 把 time.time() 固定在 100.0,已超 5s
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(cv2.imread(FRAME), 100.0, task.config)
        self.assertEqual(source, 'fallback')
        self.assertEqual((got.x, got.y), (1280.0, 720.0))

    def test_ocr_exception_does_not_stop_task(self):
        """快/慢通道 OCR 任一环节抛异常,只能当作"这一级没拿到锚点"处理,
        绝不能让异常冒泡出 run() —— 冒泡会被 TaskExecutor 的通用 except 抓住并 disable() 整个任务,
        连保命/喝药都停,违反"无怪只停手,任务继续跑"的核心契约。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1400.0, 900.0)
        task._anchor_time = 100.0
        task._last_anchor_scan = 0.0  # 确保慢通道也会被触发,两条通道都测到
        with patch('src.task.MapleFarmTask.anchor.find_in_window',
                   side_effect=RuntimeError('模型炸了')) as window, \
                patch('src.task.MapleFarmTask.anchor.find_in_region',
                     side_effect=RuntimeError('模型炸了')) as region:
            run_with_frame(task)  # 不应抛出
        window.assert_called_once()
        region.assert_called_once()
        task.stop_farming.assert_not_called()

    def test_find_mobs_exception_stops_attack_not_task(self):
        """YOLO 找怪抛异常时视为"没找到怪"——停手不放技能,但任务本身不能被停。"""
        task = make_task(**{'攻击模式': '检测', '角色名': ''})  # 角色名留空,聚焦测 find_mobs 异常
        task.find_mobs = MagicMock(side_effect=RuntimeError('模型炸了'))
        run_with_frame(task)  # 不应抛出
        task.send_key.assert_not_called()
        task.stop_farming.assert_not_called()


if __name__ == '__main__':
    unittest.main()
