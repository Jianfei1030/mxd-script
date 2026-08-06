import unittest
from unittest.mock import MagicMock, call, patch

import cv2

from src.detect.anchor import Anchor as MapleAnchor
from src.task.MapleFarmTask import DEFAULT_CONFIG, MapleFarmTask

FRAME = 'screenshots/test_frames/training_ground_full_2560x1440.png'
KEYS = {'攻击键': 'shift', '血药键': 'home', '蓝药键': 'insert',
        '回城卷键(可留空)': '', '拾取键': 'z', '左移键': 'left', '右移键': 'right'}


def make_task(**cfg_overrides):
    """config 直接取自模块级 DEFAULT_CONFIG,与 __init__ 同源,
    后续任务新增配置键/状态时本测试不再需要手工同步。"""
    task = MapleFarmTask.__new__(MapleFarmTask)  # 绕过框架 __init__
    task.config = {**DEFAULT_CONFIG, 'Buff键位': '', '药水耗尽保护': False, **cfg_overrides}
    task.info = {}
    task.capture_config = None
    task._reset_state()
    task.send_key = MagicMock()
    task.stop_farming = MagicMock()
    task.log_warning = MagicMock()
    task.log_error = MagicMock()
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

    def test_do_walk_left_first(self):
        task = make_task(**{'走位持续时间(秒)': 0.4})
        with patch('src.task.MapleFarmTask.random.choice', return_value='左移键'):
            task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('left', down_time=0.4), call('right', down_time=0.4)])

    def test_do_walk_right_first(self):
        task = make_task(**{'走位持续时间(秒)': 0.4})
        with patch('src.task.MapleFarmTask.random.choice', return_value='右移键'):
            task._do_walk(KEYS)
        self.assertEqual(task.send_key.call_args_list,
                         [call('right', down_time=0.4), call('left', down_time=0.4)])

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
        with patch('src.task.MapleFarmTask.random.choice', return_value='左移键'):
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
        with patch('src.task.MapleFarmTask.random.choice', return_value='右移键'):
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
