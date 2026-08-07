import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
import os

import cv2
import numpy as np

from src.detect import anchor
from src.detect.anchor import AnchorHit
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
    task.log_debug = MagicMock()
    task.find_mobs = MagicMock(return_value=[])
    task.get_global_config = MagicMock(return_value=dict(KEYS))
    return task


def _synthetic_frame():
    """合成 2560x1440 黑色帧:离线测试不依赖缺失的存档截图(见 FRAME)。
    黑帧的 HP/MP 读数 0.0 会误触发死亡判定,跑 run() 时需补 patch read_hp/read_mp/read_exp。"""
    return np.zeros((1440, 2560, 3), dtype=np.uint8)


def _load_frame():
    """存档帧缺失(CI/其他机器,gitignore 的截图不在本地)时退回合成帧;
    需要帧内容的测试(不 patch HP 的)仍依赖存档帧,只在有截图的机器上真跑。"""
    frame = cv2.imread(FRAME)
    return frame if frame is not None else _synthetic_frame()


def _make_nametag_template(w=130, h=28):
    """合成白字名字牌模板:黑底 + 三块互不相同的白字形,模拟 'Yufeng咕咕',二值化同实机
    (capture_template 的 blur+inRange——角落像素会被模糊滤掉,模板必须与帧走同一变换,
    贴回去才像素级一致、对齐处分数为 0)。竖切两片(0:65 / 65:130)时左右两片都带字形;
    字形互不相同,保证左半被盖后只有右半片能完美命中(相同矩形会互相误配)。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[6:22, 10:35] = 255   # 'Yuf':左偏宽块
    img[9:19, 45:72] = 255   # 'eng':中矮块(跨分片线,两片都留一点)
    img[4:24, 82:118] = 255  # '咕咕':右高块
    return anchor._to_white_binary(img)


def _frame_with_nametag(x, y, tmpl, occlude_left=False):
    """把模板(白字形)逐列贴到 (x, y) 当名字牌;occlude_left=True 时左半白像素不贴
    (模拟怪的名字牌盖住玩家名字牌左半,实测 OCR 只剩 'ng咕咕')。"""
    frame = np.zeros((1440, 2560, 3), dtype=np.uint8)
    h, w = tmpl.shape
    x0, y0 = x - w // 2, y - h // 2
    for dx in range(w):
        if occlude_left and dx < w // 2:
            continue
        ys = np.where(tmpl[:, dx] == 255)[0]
        if ys.size:
            frame[y0 + ys, x0 + dx] = 255
    return frame


def run_with_frame(task, hp=None, mp=None, exp=None, now=100.0):
    """以存档帧驱动一次 run();hp/mp/exp 不为 None 时替换对应读数。
    now 可推进模拟时间(默认 100.0,与旧调用兼容)。

    帧缺失(存档截图未入库,合成黑帧)时,未显式指定的 hp/mp 兜底为满血:
    黑帧读数 0.0 会误触发死亡判定提前 return,截断"攻击/转向/寻怪/走位"
    等行为测试(测试标准:环境缺失兜底,不允许假失败)。有真实帧时用真实读数。"""
    if not os.path.exists(FRAME):
        hp = 1.0 if hp is None else hp
        mp = 1.0 if mp is None else mp
    frame_p = patch.object(MapleFarmTask, 'frame',
                           new=property(lambda self: _load_frame()))
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
        self.assertIn(call('shift'), task.send_key.call_args_list)  # 轻点攻击(不再长按)

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
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 中心 (1530, 725),在身体右侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertIn(call('right', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertIn(call('shift'), task.send_key.call_args_list)  # 轻点攻击(不再长按)
        self.assertEqual(task._facing, 'RIGHT')

    def test_detect_mode_attacks_without_turn_when_facing_mob(self):
        """已面朝怪所在侧 → 不转向直接攻击,_facing 不变。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 右侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertIn(call('shift'), task.send_key.call_args_list)  # 轻点攻击(不再长按)
        self.assertEqual(task._facing, 'RIGHT')

    def test_detect_mode_unknown_facing_turns_to_mob_then_attacks(self):
        """朝向未知 → 按怪所在侧转向再攻击,自动确定基线朝向。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 右侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertIn(call('right', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertIn(call('shift'), task.send_key.call_args_list)  # 轻点攻击(不再长按)
        self.assertEqual(task._facing, 'RIGHT')

    def test_detect_mode_turns_left_when_mob_on_left(self):
        """怪在左侧 → 按左转向再攻击。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            mob = MagicMock(x=960, y=700, width=60, height=50)  # 中心 (990, 725),区内左侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        self.assertIn(call('left', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertIn(call('shift'), task.send_key.call_args_list)  # 轻点攻击(不再长按)
        self.assertEqual(task._facing, 'LEFT')

    def test_turn_restarts_walk_countdown(self):
        """转向本身就是"活动":走位倒计时从头算——即使本拍到点也不走位,
        之后 120s 内不再走。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_walk = -1000.0  # 走位早已到点
        task._facing = 'LEFT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
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
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
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
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
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
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
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
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            mob = MagicMock(x=2000, y=500, width=60, height=50)  # 脚底 (2030,550),差 170 > 60
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)
        # 断的是"不追"(不按方向键);闲置按椅子键是坐椅功能的预期行为,不该由本用例管
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertIsNone(task._seek_dir)

    def test_seek_switch_off_idles(self):
        """寻怪开关关 → 同层远怪也不动(不按方向键;闲置坐椅会按椅子键)。"""
        task = make_task(**{'攻击模式': '检测', '寻怪开关': False})
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
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
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task)  # 第一拍:同层远怪 → 寻怪右走
            self.assertEqual(task._seek_dir, 'right')
            task.send_key.reset_mock()
            # 第一拍寻怪长按的 send_key_down('right') 也要清掉,否则会被下面
            # "接战立即长按"的断言算进来(原来漏清,长按寻怪上线后本用例一直红)
            task.send_key_down.reset_mock()
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task, now=102.0)  # 第二拍(隔 2s ≥ 攻击间隔):怪从右侧进区
        self.assertIsNone(task._seek_dir)
        # 已面朝怪,不该有转向轻点;攻击轻点则应发生
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertIn(call('shift'), task.send_key.call_args_list)  # 轻点攻击(不再长按)
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])  # 松寻怪键
        self.assertIsNone(task._seek_key)

    def test_seek_refresh_switches_direction_at_interval(self):
        """寻怪激活时按独立刷新间隔(0.4s)重算方向,不必等攻击间隔(1.0s)。
        0.3s 时方向保持(刷新未到),0.5s 时怪换到另一侧 → 换向:松旧键按新键。"""
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
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
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task)
            self.assertEqual(task._seek_dir, 'right')
            task.send_key.reset_mock()
            task.send_key_down.reset_mock()
            task.send_key_up.reset_mock()
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task, now=100.5)  # 刷新拍(完整拍 1.0s 未到)
        self.assertIsNone(task._seek_dir)
        self.assertIn(call('shift'), task.send_key.call_args_list)  # 轻点攻击(不再长按)
        self.assertEqual(task.send_key_up.call_args_list, [call('right')])    # 松寻怪键

    def test_seek_refresh_attack_respects_interval(self):
        """接战的攻击轻点仍受 攻击间隔 节流。

        2026-08-07 改回轻点后的语义:旧版长按会在刷新拍立即接管、不受间隔限制,
        但长按期间游戏收不到新的按下边沿,被击退后就再也不起手(见 _do_attack)。
        现在按固定间隔轻点,刷新拍若距上次攻击不足间隔则这拍不点,下一拍补上。
        """
        task = make_task(**{'攻击模式': '检测'})
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task)
            self.assertEqual(task._seek_dir, 'right')
            task.send_key.reset_mock()
            task.send_key_up.reset_mock()
            task._last_attack = 100.4  # 0.1s 前攻击过,1.5s 间隔未到
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task, now=100.5)
            self.assertIsNone(task._seek_dir)
            self.assertNotIn(call('shift'), task.send_key.call_args_list)  # 间隔未到,不点
            self.assertEqual(task.send_key_up.call_args_list, [call('right')])  # 松寻怪键
            task.send_key.reset_mock()
            run_with_frame(task, now=102.0)   # 间隔已过 → 补上这一点
        self.assertIn(call('shift'), task.send_key.call_args_list)

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
        # 预置朝向 = 怪所在侧,让本拍不需要转向:转向轻点本身也会重置走位倒计时
        # (设计如此),不隔离掉就分不清 _last_walk 是"没走位"还是"被转向重置"
        task._facing = 'LEFT'
        mob = MagicMock(x=1200, y=700, width=60, height=50)  # 中心 (1230,725):区内,身体左侧
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
        run_with_frame(task, hp=0.9, mp=0.9, exp=0.5)
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


class TestExpStallGate(unittest.TestCase):
    """经验停滞守卫:一只怪都没有的时段不计入停滞。

    2026-08-07 用户提出的误停顾虑:空图/刷新间隙本来就没收益,不该被判"无效挂机"。
    但那次真实停机(03:45:30)不属于此列——8 分钟 698 拍里 `怪=0` 的拍数是 0,
    最少一拍也有 5 只、多数 9-11 只,即满地是怪却零收益,那正是守卫该抓的。
    定频模式不跑 YOLO、没有找怪信息,保持旧行为(照常计时)。
    """

    MOB = dict(x=1400, y=600, width=60, height=50)      # 中心 (1430,625):默认区内
    FAR_MOB = dict(x=2400, y=600, width=60, height=50)  # 区外,但"有怪"

    @staticmethod
    def _stalled_task(**cfg):
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 0.1, **cfg})
        task._last_exp = 0.5
        task._last_exp_gain_time = -1000.0   # 远超停滞上限
        return task

    def test_stops_when_mobs_present_but_no_exp(self):
        """满地是怪却零收益 → 该停(这正是 03:45:30 那次的情形)。"""
        task = self._stalled_task()
        task.find_mobs = MagicMock(return_value=[MagicMock(**self.MOB)])
        run_with_frame(task, hp=0.9, mp=0.9, exp=0.5)
        task.stop_farming.assert_called_once()

    def test_does_not_stop_when_no_mobs_at_all(self):
        """一只怪都没有 → 空图,不算无效挂机。"""
        task = self._stalled_task()
        task.find_mobs = MagicMock(return_value=[])
        run_with_frame(task, hp=0.9, mp=0.9, exp=0.5)
        task.stop_farming.assert_not_called()

    def test_far_mobs_still_count_as_available(self):
        """怪在攻击区外也算"有怪可打"(可以走过去),照常计停滞。"""
        task = self._stalled_task()
        task.find_mobs = MagicMock(return_value=[MagicMock(**self.FAR_MOB)])
        run_with_frame(task, hp=0.9, mp=0.9, exp=0.5)
        task.stop_farming.assert_called_once()

    def test_timer_resumes_from_scratch_after_mobless_period(self):
        """空图期间计时暂停:怪回来后不该立刻秒停,而是重新开始计时。"""
        task = self._stalled_task()
        task.find_mobs = MagicMock(return_value=[])
        run_with_frame(task, hp=0.9, mp=0.9, exp=0.5, now=1000.0)      # 空图,计时暂停
        task.stop_farming.assert_not_called()
        task.find_mobs = MagicMock(return_value=[MagicMock(**self.MOB)])
        task._last_detect = 0.0
        run_with_frame(task, hp=0.9, mp=0.9, exp=0.5, now=1001.0)      # 怪回来,才过 1 秒
        task.stop_farming.assert_not_called()

    def test_fixed_mode_keeps_old_behaviour(self):
        """定频模式没有找怪信息 → 保持旧行为,照常按停滞上限停。"""
        task = self._stalled_task(**{'攻击模式': '定频'})
        run_with_frame(task, hp=0.9, mp=0.9, exp=0.5)
        task.stop_farming.assert_called_once()


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


class TestAttackTap(unittest.TestCase):
    """检测模式攻击轻点(_do_attack 直接测,无帧依赖)。

    2026-08-07 从长按改回轻点(df9b020 曾改成"长按连挥")。长按期间只是每拍重复
    keyDown,游戏侧没有新的"按下"边沿:角色被怪击退打断施法后不会重新起手。
    实测(02:07-02:12 逐拍日志)最长一次按住 27 秒无一次松键,期间区内一直有怪;
    且挥砍中 body_x 跳变 >80px 的拍占 19%(其余状态 5%),即挥砍时频繁被击退。
    轻点每次都产生新的按下边沿,击退后下一拍即可重新起手。
    """

    def test_taps_attack_key_when_mob_in_zone(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_never_holds_attack_key(self):
        """核心回归:攻击键不许再走 send_key_down 长按。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        for i in range(5):
            task._do_attack(task.config, KEYS, now=100.0 + i * 2.0)
        task.send_key_down.assert_not_called()
        self.assertFalse(task._attack_held)

    def test_respects_attack_interval(self):
        """同一个 攻击间隔 内只点一次,不被 10Hz 主循环连点。"""
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 1.5})
        task._last_mob_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task._do_attack(task.config, KEYS, now=101.0)   # 未满 1.5s
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_taps_again_after_interval(self):
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 1.5})
        task._last_mob_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task._do_attack(task.config, KEYS, now=101.5)
        self.assertEqual(task.send_key.call_args_list, [call('shift'), call('shift')])

    def test_no_tap_before_first_detection(self):
        """启动后还没检测过(_last_mob_present 初始 None)→ 不按攻击键。"""
        task = make_task(**{'攻击模式': '检测'})
        task._do_attack(task.config, KEYS, now=100.0)
        task.send_key.assert_not_called()

    def test_no_tap_when_mob_gone(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = False
        task._do_attack(task.config, KEYS, now=100.0)
        task.send_key.assert_not_called()

    def test_fixed_mode_not_handled_here(self):
        """定频模式的定时轻点在 run() 里,本方法不重复按。"""
        task = make_task(**{'攻击模式': '定频'})
        task._last_mob_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task.send_key.assert_not_called()

    def test_pause_and_disable_do_not_touch_attack_key(self):
        """不再长按后,暂停/停任务无需松攻击键(方向键的松开另有用例覆盖)。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_mob_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task._on_executor_paused(True)
        self.assertNotIn(call('shift'), task.send_key_up.call_args_list)


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
        # 断的是"不攻击",不是"一个键都不按":坐椅功能(b0201da)之后闲置会按椅子键,
        # 那是预期行为。原来的 assert_not_called() 把两件事绑在一起,坐椅上线后一直红
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('shift', sent)
        task.send_key_down.assert_not_called()
        task.stop_farming.assert_not_called()

    def test_detection_is_throttled_when_idle(self):
        """无怪时不许每个 0.1s 触发都重跑检测(缺陷 B)。同一时刻连跑 5 次,只应检测 1 次。"""
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[])
        for _ in range(5):
            run_with_frame(task, hp=0.9, mp=0.9)  # 补 HP 读数:黑帧 0.0 会误触发死亡判定
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
        hit = AnchorHit(1400.0, 900.0, 128, 'Yufeng咕咕')
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(_synthetic_frame(), 100.0, task.config)
        self.assertEqual(source, 'window')
        self.assertEqual((got.x, got.y), (1400.0, 900.0))
        self.assertEqual(task._anchor, (1400.0, 900.0))

    def test_cached_anchor_when_both_channels_miss(self):
        """快通道失灵 + 慢通道被节流 + 锚点未过期 → 沿用上次锚点,不回退画面中心。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '锚点保鲜(秒)': 10})
        task._anchor = (1400.0, 900.0)
        task._anchor_time = 99.0        # 时间被固定在 100.0,锚点年龄 1s,未过期
        task._last_anchor_scan = 99.5   # 距上次扫描 0.5s < 锚点刷新间隔 2s,慢通道被节流
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None) as window, \
                patch('src.task.MapleFarmTask.anchor.find_in_region') as region:
            got, source = task._resolve_anchor(_synthetic_frame(), 100.0, task.config)
        self.assertEqual(source, 'cached')
        self.assertEqual((got.x, got.y), (1400.0, 900.0))
        window.assert_called_once()
        region.assert_not_called()

    def test_expired_anchor_falls_back_to_last_known_y(self):
        """锚点过期 → 回退到 (屏幕中心 x, 最后已知 y) 而非 (中心, 中心):
        名字牌 y 同平台极稳定(实测 887-888),保留 y 攻击区才能罩住脚下这层怪;
        纯屏幕中心 y=720 比实测层高 ~165px,怪全在区外(2026-08-06 实测"怪堆里坐下")。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '锚点保鲜(秒)': 5})
        task._anchor = (400.0, 887.0)
        task._anchor_time = 90.0  # run_with_frame 把 time.time() 固定在 100.0,已超 5s
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(_synthetic_frame(), 100.0, task.config)
        self.assertEqual(source, 'fallback')
        self.assertEqual(got.x, 1280.0)   # 水平仍回退屏幕中心(相机跟随角色)
        self.assertEqual(got.y, 887.0)    # 纵向保留最后已知层高

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
            run_with_frame(task, hp=0.9, mp=0.9)  # 不应抛出(补 HP 读数防黑帧误判死亡)
        window.assert_called_once()
        region.assert_called_once()
        task.stop_farming.assert_not_called()

    def test_find_mobs_exception_stops_attack_not_task(self):
        """YOLO 找怪抛异常时视为"没找到怪"——停手不放技能,但任务本身不能被停。"""
        task = make_task(**{'攻击模式': '检测', '角色名': ''})  # 角色名留空,聚焦测 find_mobs 异常
        task.find_mobs = MagicMock(side_effect=RuntimeError('模型炸了'))
        run_with_frame(task)  # 不应抛出
        # 同 test_no_mob_does_not_stop_task:只断"不攻击",坐椅键属预期
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('shift', sent)
        task.send_key_down.assert_not_called()
        task.stop_farming.assert_not_called()


class TestAnchorExtrapolation(unittest.TestCase):
    """寻怪中名字牌被怪遮挡(OCR 连续失败)时,攻击区必须外推跟随走动中的角色。

    回归:怪堆里"一直寻怪不攻击"——锚点冻结在旧位置,攻击区不跟随走动的角色,
    怪永远进不了攻击区,寻怪永不收敛(2026-08-06 实测日志:10s 未定位角色告警 ×124,
    期间反复"闲置坐椅")。用合成帧,不依赖缺失的存档截图。
    """

    def test_cached_anchor_extrapolates_with_seek_speed(self):
        """寻怪中 OCR 连续失败(锚点 3s 未更新)→ 按 配置外推速度 × 年龄 前移 x;
        快通道小窗也搜外推位置,名字牌一露头就能重新咬住。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 200})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = 'right'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None) as window, \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(source, 'cached')
        self.assertEqual(got.x, 1280 + 200 * 3)  # 3s × 配置速度
        self.assertEqual(got.y, 800.0)           # y 不推(同平台稳定)
        window.assert_called_once()
        self.assertEqual(window.call_args[0][2], (1280 + 600.0, 800.0))  # 小窗跟外推位置

    def test_cached_anchor_uses_measured_velocity_when_fresh(self):
        """近 2s 内有实测速度(低通后)→ 优先用它,而不是配置速度。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 200})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._anchor_vx = 120.0
        task._last_anchor_hit = 102.0  # 1s 前命中:实测速度仍可信
        task._seek_dir = 'right'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(got.x, 1280 + 120 * 3)

    def test_seek_left_extrapolates_negative(self):
        """朝左寻怪 → 按负方向外推(默认速度 250)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = 'left'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 101.0, task.config)
        self.assertEqual(got.x, 1280 - 250.0)

    def test_no_extrapolation_when_anchor_fresh(self):
        """锚点刚命中(年龄 < 0.5s)→ 不推,用原始值:外推对新鲜锚点只会引入误差。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 103.0  # now=103.0,年龄 0
        task._seek_dir = 'right'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(got.x, 1280.0)

    def test_no_extrapolation_when_not_seeking(self):
        """没在寻怪(站桩)→ 不外推:OCR 失败期间攻击区留在最后可信位置。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = None
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(got.x, 1280.0)

    def test_fallback_never_anchored_uses_centre(self):
        """从未锚定过(角色名刚填/首次)→ 回退仍是纯屏幕中心(原行为)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(source, 'fallback')
        self.assertEqual((got.x, got.y), (1280.0, 720.0))

    def test_velocity_learned_from_window_hit(self):
        """快通道命中 → 用位移/时间学习实测速度(低通,防单帧噪声)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        hit = AnchorHit(1300, 800, 130, 'Yufeng咕咕')
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            task._resolve_anchor(_synthetic_frame(), 101.0, task.config)
        self.assertEqual(task._anchor_vx, 0.7 * 20.0)  # v=20px/s,低通 0.7*20+0.3*0
        self.assertEqual(task._anchor, (1300.0, 800.0))
        self.assertEqual(task._last_anchor_hit, 101.0)

    def test_velocity_rejects_implausible_spikes(self):
        """跳变(>600px/s,如回退/误检)不许污染实测速度。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        hit = AnchorHit(2000, 800, 130, 'Yufeng咕咕')  # 720px/s 跳变
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            task._resolve_anchor(_synthetic_frame(), 101.0, task.config)
        self.assertEqual(task._anchor_vx, 0.0)

    def test_velocity_not_learned_on_platform_change(self):
        """平台切换(名字牌 y 突变)→ 不学速度:位移来自换层,不是行走。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        hit = AnchorHit(1300, 750, 130, 'Yufeng咕咕')  # y 变了 50px(换平台)
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            task._resolve_anchor(_synthetic_frame(), 101.0, task.config)
        self.assertEqual(task._anchor_vx, 0.0)

    def test_seek_with_occluded_nameplate_eventually_attacks(self):
        """回归(怪堆里"一直寻怪不攻击"):寻怪中名字牌一直被怪遮挡(快/慢通道全失败),
        角色向右走 0.5s 后攻击区外推跟上 → 怪进区 → 停追接战。
        旧代码攻击区冻在 (1280,800):怪中心 (1900,725) 永在 1200px 区外 → 永远寻怪不攻击。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '走位开关': False,
                            '攻击区宽(像素)': 1200})  # 用户实测配置宽度
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        mob = MagicMock(x=1850, y=650, width=100, height=150)  # 中心 (1900,725),脚底 (1900,800)
        task.find_mobs = MagicMock(return_value=[mob])
        frame_p = patch.object(MapleFarmTask, 'frame',
                               new=property(lambda self: _synthetic_frame()))
        frame_p.start()
        try:
            with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                    patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None), \
                    patch('src.task.MapleFarmTask.bars.read_hp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_mp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_exp', return_value=0.5), \
                    patch('time.time', return_value=100.0):
                task.run()  # 第一拍:怪在区外 → 寻怪右走
                self.assertEqual(task._seek_dir, 'right')
            with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                    patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None), \
                    patch('src.task.MapleFarmTask.bars.read_hp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_mp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_exp', return_value=0.5), \
                    patch('time.time', return_value=100.5):
                task.run()  # 0.5s 后:攻击区外推跟上 → 怪进区 → 接战
        finally:
            frame_p.stop()
        self.assertIsNone(task._seek_dir)
        self.assertIsNone(task._seek_key)
        self.assertIn(call('shift'), task.send_key.call_args_list)


class TestTemplateSplitMatch(unittest.TestCase):
    """模板分片匹配快通道(参考 MapleStoryAutoLevelUp 的 nametag split_width 方案)。

    怪/宠的名字牌会盖住玩家名字牌左半(实测 OCR 只剩 'ng咕咕'),锚点因此冻结,
    怪堆里一直寻怪不攻击。模板把名字牌二值化成"白字形",竖切两片分开匹配——
    盖住一片,另一片照样命中,且零 OCR 开销。模板由 OCR 完整命中时自动裁剪生成
    (零配置),并持久化,下次启动直接加载。
    """

    def test_split_match_finds_right_half_when_left_occluded(self):
        """核心:左半被盖 → 右半片完美命中,返回整牌中心(不是被盖的偏位)。"""
        tmpl = _make_nametag_template()
        frame = _frame_with_nametag(1400, 800, tmpl, occlude_left=True)
        hit = anchor.split_match(frame, tmpl, (1400, 800), 240, 80, 0.2)
        self.assertIsNotNone(hit)
        self.assertEqual((hit.x, hit.y), (1400.0, 800.0))

    def test_split_match_none_when_template_absent(self):
        """窗口里根本没有名字牌(黑帧)→ 不命中。"""
        tmpl = _make_nametag_template()
        hit = anchor.split_match(_synthetic_frame(), tmpl, (1400, 800), 240, 80, 0.2)
        self.assertIsNone(hit)

    def test_split_match_none_when_outside_window(self):
        """牌子在搜索窗外(±240×±80)→ 不命中:模板只认小窗,防全图误匹配。"""
        tmpl = _make_nametag_template()
        frame = _frame_with_nametag(1400, 800, tmpl)
        self.assertIsNone(anchor.split_match(frame, tmpl, (1000, 800), 240, 80, 0.2))
        # 1400 距窗心 400 > 240,牌子在窗外

    def test_template_channel_reanchors_after_ocr_failure(self):
        """OCR 快/慢通道全失败(被遮挡)+ 已有模板 → 模板通道直接命中新位置,
        锚点不再冻结,且同样学习实测速度(外推的优先依据)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._nametag_template = _make_nametag_template()
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 102.0
        frame = _frame_with_nametag(1400, 800, task._nametag_template)
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(frame, 103.0, task.config)
        self.assertEqual(source, 'template')
        self.assertEqual((got.x, got.y), (1400.0, 800.0))
        self.assertEqual(task._anchor, (1400.0, 800.0))
        self.assertEqual(task._anchor_vx, 0.7 * 120.0)  # dx=120, dt=1 → 低通学习

    def test_template_miss_falls_through_to_window_ocr(self):
        """模板没命中 → 落回 OCR 快通道(阶梯继续往下走,不许跳过)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._nametag_template = _make_nametag_template()
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 102.0
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None) as window, \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, source = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(source, 'cached')
        self.assertEqual(got.x, 1280.0)
        window.assert_called_once()

    def test_captured_on_full_ocr_hit(self):
        """OCR 完整命中 → 裁名字牌区域做白字二值化模板(存内存 + 落盘)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        tmpl = _make_nametag_template()
        frame = _frame_with_nametag(1400, 800, tmpl)
        hit = AnchorHit(1400.0, 800.0, 130, 'Yufeng咕咕')
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.save_template') as save:
            got, source = task._resolve_anchor(frame, 101.0, task.config)
        self.assertEqual(source, 'window')
        self.assertIsNotNone(task._nametag_template)
        self.assertGreater(np.count_nonzero(task._nametag_template), 0)
        save.assert_called_once()
        self.assertGreater(np.count_nonzero(save.call_args[0][0]), 0)  # 存的是白字形,不是黑底

    def test_suffix_hit_does_not_capture(self):
        """部分匹配('ng咕咕',被挡)→ 裁出来是残缺牌子,不配当模板。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        hit = AnchorHit(1400.0, 800.0, 130, 'ng咕咕')
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.save_template') as save:
            task._resolve_anchor(_synthetic_frame(), 101.0, task.config)
        self.assertIsNone(task._nametag_template)
        save.assert_not_called()

    def test_captured_on_full_ocr_hit_via_region_channel(self):
        """回归:慢通道(全区域扫描)完整命中也能裁模板——曾因调用点残留旧的 now 参数
        报 'takes 3 positional argument but 4 were given',慢通道命中永远进不了模板。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        tmpl = _make_nametag_template()
        frame = _frame_with_nametag(1400, 800, tmpl)
        hit = AnchorHit(1400.0, 800.0, 130, 'Yufeng咕咕')
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.save_template') as save:
            got, source = task._resolve_anchor(frame, 101.0, task.config)
        self.assertEqual(source, 'region')
        self.assertIsNotNone(task._nametag_template)
        self.assertGreater(np.count_nonzero(task._nametag_template), 0)
        save.assert_called_once()
        self.assertGreater(np.count_nonzero(save.call_args[0][0]), 0)

    def test_suffix_hit_does_not_capture_via_region_channel(self):
        """慢通道部分匹配(被挡)同样不裁模板。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕'})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        hit = AnchorHit(1400.0, 800.0, 130, 'ng咕咕')
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=hit), \
                patch('src.task.MapleFarmTask.anchor.save_template') as save:
            task._resolve_anchor(_synthetic_frame(), 101.0, task.config)
        self.assertIsNone(task._nametag_template)
        save.assert_not_called()

    def test_seek_occluded_with_template_recovers_and_attacks(self):
        """端到端回归(怪堆里"一直寻怪不攻击"的模板解法):寻怪中 OCR 全失败,
        模板分片找到名字牌真实位置 → 攻击区跟上 → 怪进区 → 停追接战。
        外推是兜底(速度猜不准);模板命中是"看得见",一帧就咬住,不再等外推。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '走位开关': False,
                            '攻击区宽(像素)': 1200})
        task._nametag_template = _make_nametag_template()
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = 'right'   # 正在寻怪(名字牌此前已被盖住,锚点冻结中)
        task._seek_key = '右移键'   # 方向键长按中(_seek_key 存配置名)
        mob = MagicMock(x=1850, y=650, width=100, height=150)  # 中心 (1900,725),脚底 (1900,800)
        task.find_mobs = MagicMock(return_value=[mob])
        frame_p = patch.object(MapleFarmTask, 'frame',
                               new=property(lambda self: _frame_with_nametag(
                                   1400, 800, self._nametag_template)))
        frame_p.start()
        try:
            with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                    patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None), \
                    patch('src.task.MapleFarmTask.bars.read_hp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_mp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_exp', return_value=0.5), \
                    patch('time.time', return_value=100.5):
                task.run()
        finally:
            frame_p.stop()
        self.assertIsNone(task._seek_dir)                # 怪进区 → 停追
        self.assertIsNone(task._seek_key)                # 松方向键
        self.assertEqual(task._anchor, (1400.0, 800.0))  # 模板咬住真实位置,不是外推
        self.assertIn(call('shift'), task.send_key.call_args_list)


class TestTurnAfterSeek(unittest.TestCase):
    """回归:寻怪中怪从背后进攻击区 → "转向但不攻击"。

    根因(2026-08-06 实测):接战转向的 0.05s 方向键轻点发生时,寻怪长按的方向键
    还按着——角色刚转过去 50ms,寻怪键又把朝向带回原方向;攻击键长按落下时角色
    面朝背对怪的方向,挥砍全打空,看起来就是"转向但不攻击"。而且寻怪键的 keyup
    在攻击键 keydown 之后才发。修复:接战分支先松寻怪键,再轻点转向。
    """

    def test_turn_after_seek_releases_direction_key_before_tap(self):
        """怪从背后进区:松寻怪键必须发生在转向轻点之前,攻击键按下时不再残留方向键。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '走位开关': False,
                            '攻击区宽(像素)': 1200})
        task._anchor = (1400.0, 800.0)
        task._anchor_time = 100.0
        task._facing = 'RIGHT'
        task._seek_dir = 'right'   # 正在向右寻怪
        task._seek_key = '右移键'   # 右方向键长按中(_seek_key 存配置名,见 _do_seek_move)
        mob = MagicMock(x=1050, y=650, width=100, height=150)  # 中心 (1100,725):背后进区
        task.find_mobs = MagicMock(return_value=[mob])
        # 共享父 mock 记录跨 mock 的调用顺序(松键 vs 转向轻点 vs 攻击长按)
        parent = MagicMock()
        task.send_key_up = parent.send_key_up
        task.send_key = parent.send_key
        task.send_key_down = parent.send_key_down
        frame_p = patch.object(MapleFarmTask, 'frame',
                               new=property(lambda self: _synthetic_frame()))
        frame_p.start()
        try:
            with patch('src.task.MapleFarmTask.anchor.find_in_window',
                       return_value=AnchorHit(1400.0, 800.0, 130, 'Yufeng咕咕')), \
                    patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None), \
                    patch('src.task.MapleFarmTask.bars.read_hp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_mp', return_value=0.9), \
                    patch('src.task.MapleFarmTask.bars.read_exp', return_value=0.5), \
                    patch('time.time', return_value=100.5):
                task.run()
        finally:
            frame_p.stop()
        calls = parent.method_calls
        # 顺序:松右键 → 轻点左键(转向)→ 轻点攻击键;攻击时不得有方向键残留
        up_idx = calls.index(call.send_key_up('right'))
        tap_idx = next(i for i, c in enumerate(calls)
                       if c == call.send_key('left', down_time=TURN_TAP_SECONDS))
        atk_idx = calls.index(call.send_key('shift'))
        self.assertLess(up_idx, tap_idx)   # 先松寻怪键,转向才不会被"还在走"吞掉
        self.assertLess(tap_idx, atk_idx)  # 攻击轻点在转向轻点完成之后
        self.assertIsNone(task._seek_dir)
        self.assertIsNone(task._seek_key)


class TestBoxesEnabled(unittest.TestCase):

    def test_no_app_returns_false(self):
        """og.app 未设置(默认 None,离线/无 GUI)→ False,不抛异常。"""
        task = make_task()
        self.assertFalse(task._boxes_enabled())

    def test_app_without_use_overlay_key_returns_false(self):
        """ok_config 里没有 use_overlay 键 → 按默认值 False。"""
        from ok import og
        task = make_task()
        with patch.object(og, 'app', SimpleNamespace(ok_config={})):
            self.assertFalse(task._boxes_enabled())

    def test_use_overlay_true_returns_true(self):
        """GUI「启用标记框」开着(use_overlay=True)→ True。"""
        from ok import og
        task = make_task()
        with patch.object(og, 'app', SimpleNamespace(ok_config={'use_overlay': True})):
            self.assertTrue(task._boxes_enabled())

    def test_use_overlay_false_returns_false(self):
        from ok import og
        task = make_task()
        with patch.object(og, 'app', SimpleNamespace(ok_config={'use_overlay': False})):
            self.assertFalse(task._boxes_enabled())


class TestDebugOverlay(unittest.TestCase):

    def test_boxes_enabled_draws_with_current_state(self):
        """检测模式一拍跑完(_detect_and_act 被触发)且开关开 → 调一次 _draw_debug,
        参数是这一拍算出的 body/zone/mob_present,不是重新检测的。"""
        task = make_task(**{'角色名': ''})  # 角色名空 → anchor 走 fallback,body=画面中心
        task._boxes_enabled = MagicMock(return_value=True)
        with patch.object(MapleFarmTask, '_draw_debug') as draw, \
                patch.object(MapleFarmTask, '_clear_debug') as clear:
            run_with_frame(task, hp=0.9, mp=0.9)
            draw.assert_called_once()
            clear.assert_not_called()
            _, kwargs = draw.call_args
            self.assertEqual(kwargs['mob_present'], False)  # find_mobs 默认 mock 返回 []
            self.assertEqual(kwargs['mobs'], [])

    def test_boxes_disabled_clears_not_draws(self):
        """开关关 → 不画,且因为之前没画过(_debug_drawn 初始 False)也不必调用清除。"""
        task = make_task(**{'角色名': ''})
        task._boxes_enabled = MagicMock(return_value=False)
        with patch.object(MapleFarmTask, '_draw_debug') as draw, \
                patch.object(MapleFarmTask, '_clear_debug') as clear:
            run_with_frame(task, hp=0.9, mp=0.9)
            draw.assert_not_called()
            clear.assert_called_once()

    def test_clear_debug_noop_when_never_drawn(self):
        """_clear_debug 本身:没画过时不碰 overlay(不调用 get_overlay_view)。"""
        task = make_task()
        task.get_overlay_view = MagicMock()
        task._clear_debug()
        task.get_overlay_view.assert_not_called()

    def test_clear_debug_calls_overlay_when_drawn(self):
        """_clear_debug 本身:画过之后清 → 调 clear_draw('maple_farm_debug') 并复位标记。"""
        task = make_task()
        overlay = MagicMock()
        task.get_overlay_view = MagicMock(return_value=overlay)
        task._debug_drawn = True
        task._clear_debug()
        overlay.clear_draw.assert_called_once_with('maple_farm_debug')
        self.assertFalse(task._debug_drawn)

    def test_draw_debug_calls_overlay_draw(self):
        """_draw_debug 本身:调用 overlay.draw,key 固定 'maple_farm_debug',并置标记。"""
        task = make_task()
        overlay = MagicMock()
        task.get_overlay_view = MagicMock(return_value=overlay)
        task._draw_debug(task.config, body=(1280, 700), zone=(1000, 600, 1500, 800),
                         mobs=[], mob_present=False)
        overlay.draw.assert_called_once()
        args, _ = overlay.draw.call_args
        self.assertEqual(args[0], 'maple_farm_debug')
        self.assertTrue(callable(args[1]))
        self.assertTrue(task._debug_drawn)

    def test_draw_debug_paint_closure_runs_with_mobs(self):
        """回归(2026-08-07 实测日志 13870 条 warning):脚底点曾写成
        drawPoint(rect(fx, fy, 1, 1))——QRectF 传给只收 QPointF 的 drawPoint,
        paint 闭包每帧抛 TypeError,被 OverlayWidget.paint_custom 吞掉,第一个怪
        的脚底点之后的绘制(后续怪物框)全部中断。
        这里把 paint 闭包对着真 QPainter 跑一遍(NoTextPainter 仅把 drawText 变
        no-op——沙箱无字体渲染,drawText 会崩进程;drawRect/drawPoint 走真 Qt),
        有怪时必须不抛异常。"""
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QImage, QPainter

        class NoTextPainter:
            """drawText 变 no-op(本机无字体时会崩进程),其余透传真 QPainter。"""

            def __init__(self, painter):
                self._p = painter

            def drawText(self, *args, **kwargs):
                pass

            def __getattr__(self, name):
                return getattr(self._p, name)

        class FakeWidget:
            def frame_ratio(self):
                return 1.0

        mob = SimpleNamespace(x=100, y=200, width=80, height=120)
        task = make_task()
        overlay = MagicMock()
        task.get_overlay_view = MagicMock(return_value=overlay)
        task._draw_debug(task.config, body=(1280, 700), zone=(1000, 600, 1500, 800),
                         mobs=[mob], mob_present=True)
        callback = overlay.draw.call_args.args[1]

        img = QImage(2560, 1440, QImage.Format_RGB32)
        img.fill(0)
        painter = QPainter(img)
        try:
            callback(NoTextPainter(painter), FakeWidget())  # 修复前这里抛 TypeError
        finally:
            painter.end()

    def test_draw_debug_noop_when_no_overlay(self):
        """无 GUI(get_overlay_view 返回 None)→ 不抛异常,不置标记。"""
        task = make_task()
        task.get_overlay_view = MagicMock(return_value=None)
        task._draw_debug(task.config, body=(1280, 700), zone=(1000, 600, 1500, 800),
                         mobs=[], mob_present=False)
        self.assertFalse(task._debug_drawn)

    def test_switch_to_fixed_rate_clears_previous_overlay(self):
        """之前检测模式画过 → 切到定频模式 → run() 里清一次。"""
        task = make_task(**{'攻击模式': '定频'})
        task._debug_drawn = True
        with patch.object(MapleFarmTask, '_clear_debug') as clear:
            def fake_clear():
                task._debug_drawn = False
            clear.side_effect = fake_clear
            run_with_frame(task, hp=0.9, mp=0.9)
            clear.assert_called_once()

    def test_fixed_rate_mode_no_clear_when_never_drawn(self):
        """定频模式、从没画过 → 不必调用清除(_debug_drawn 恒 False 时是 no-op,
        这里直接断言真实 _clear_debug 不触发 get_overlay_view)。"""
        task = make_task(**{'攻击模式': '定频'})
        task.get_overlay_view = MagicMock()
        run_with_frame(task, hp=0.9, mp=0.9)
        task.get_overlay_view.assert_not_called()

    def test_disable_clears_debug_overlay(self):
        """MapleFarmTask.disable() 真正执行(不是 mock 掉),但 super().disable()
        (MRO 上下一个是 TriggerTask.disable)打桩掉——make_task 是裸 __new__ 出来的,
        没有框架其余状态,真跑 TriggerTask.disable 会因为缺属性炸掉,与本测试无关。"""
        from ok.task.task import TriggerTask
        task = make_task()
        overlay = MagicMock()
        task.get_overlay_view = MagicMock(return_value=overlay)
        task._debug_drawn = True
        with patch.object(TriggerTask, 'disable'):
            MapleFarmTask.disable(task)
        overlay.clear_draw.assert_called_once_with('maple_farm_debug')


class TestAttackDebounceAndTurnCooldown(unittest.TestCase):
    """一拍漏检不松攻击键;冷却内不许反向转向。

    几何:DEFAULT_CONFIG['角色名'] 为空 → 锚点恒为画面中心 (1280,720),
    身体 (1280,630),默认攻击区 x∈[980,1580] y∈[530,730]。
    攻击间隔压到 0.1 秒,好让相邻两次 run() 都真跑完整检测拍。
    """

    RIGHT_MOB = dict(x=1400, y=600, width=60, height=50)   # 中心 (1430,625) 区内偏右
    LEFT_MOB = dict(x=1050, y=600, width=60, height=50)    # 中心 (1080,625) 区内偏左

    @staticmethod
    def _task(**cfg):
        return make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 0.1, **cfg})

    @staticmethod
    def _tick(task, mobs, now):
        task.find_mobs = MagicMock(return_value=[MagicMock(**m) for m in mobs])
        run_with_frame(task, now=now)

    def test_attack_continues_through_single_missed_detection(self):
        """漏检一拍(YOLO recall 0.886 + 攻击特效遮挡)不该停手。"""
        task = self._task(**{'丢怪保持(秒)': 1.0})
        self._tick(task, [self.RIGHT_MOB], now=100.0)
        task.send_key.reset_mock()
        self._tick(task, [], now=100.5)          # 保持窗内的空拍
        self.assertIn(call('shift'), task.send_key.call_args_list)

    def test_attack_stops_after_grace_expires(self):
        task = self._task(**{'丢怪保持(秒)': 1.0})
        self._tick(task, [self.RIGHT_MOB], now=100.0)
        task.send_key.reset_mock()
        self._tick(task, [], now=101.5)          # 超出保持窗
        self.assertNotIn(call('shift'), task.send_key.call_args_list)

    def test_no_seek_during_grace(self):
        """保持窗内不许改去寻怪:刚打的目标只是漏检一拍,走开就更打不到了。"""
        task = self._task(**{'丢怪保持(秒)': 1.0})
        self._tick(task, [self.RIGHT_MOB], now=100.0)
        # 区外同层远怪(中心 2030,705;脚底 730 与锚点 720 同层)
        self._tick(task, [dict(x=2000, y=680, width=60, height=50)], now=100.5)
        self.assertIsNone(task._seek_dir)

    def test_grace_zero_stops_immediately(self):
        task = self._task(**{'丢怪保持(秒)': 0})
        self._tick(task, [self.RIGHT_MOB], now=100.0)
        task.send_key.reset_mock()
        self._tick(task, [], now=100.5)
        self.assertNotIn(call('shift'), task.send_key.call_args_list)

    def test_reverse_turn_blocked_within_cooldown(self):
        """区内那只怪换边(实测每次转向时区内恰好 1 只)→ 冷却内不许跟着翻。"""
        task = self._task(**{'转向冷却(秒)': 1.5})
        task._facing = 'LEFT'
        self._tick(task, [self.RIGHT_MOB], now=100.0)   # 转向 right
        self.assertEqual(task._facing, 'RIGHT')
        task.send_key.reset_mock()
        self._tick(task, [self.LEFT_MOB], now=101.0)    # 1.0s < 冷却 1.5s
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('left', sent)
        self.assertEqual(task._facing, 'RIGHT')         # 没转成就不许改朝向

    def test_turn_allowed_after_cooldown(self):
        task = self._task(**{'转向冷却(秒)': 1.5})
        task._facing = 'LEFT'
        self._tick(task, [self.RIGHT_MOB], now=100.0)
        task.send_key.reset_mock()
        self._tick(task, [self.LEFT_MOB], now=102.0)    # 2.0s ≥ 冷却
        self.assertIn(call('left', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertEqual(task._facing, 'LEFT')


class TestDecisionLog(unittest.TestCase):
    """每个检测拍的决策日志(默认关,排查时才开)。

    2026-08-07 排查"左右转向不攻击"时,日志里没有任何逐拍决策数据,只能靠 2 秒一张的
    录制帧离线重放去推——而翻转发生在 0.1-0.7 秒尺度,那把尺子量不出来。补上这条
    日志,实机挂机两分钟就能直接看出是哪个分支在翻、翻的时候观测是什么。

    几何提醒:DEFAULT_CONFIG['角色名'] 是空串,_resolve_anchor 直接回退画面中心,
    锚点恒为 (1280, 720) → 身体 (1280, 630),攻击区 x∈[980,1580] y∈[530,730]。
    """

    @staticmethod
    def _log_lines(task):
        return [c.args[0] for c in task.log_debug.call_args_list
                if c.args and str(c.args[0]).startswith('决策')]

    def test_no_decision_log_by_default(self):
        task = make_task(**{'攻击模式': '检测'})
        task.find_mobs = MagicMock(return_value=[MagicMock(x=1400, y=600, width=60, height=50)])
        run_with_frame(task)
        self.assertEqual(self._log_lines(task), [])

    def test_logs_attack_tick_with_turn(self):
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task._facing = 'LEFT'
        task.find_mobs = MagicMock(  # 中心 (1430,625):区内,身体右侧
            return_value=[MagicMock(x=1400, y=600, width=60, height=50)])
        run_with_frame(task)
        lines = self._log_lines(task)
        self.assertEqual(len(lines), 1)
        self.assertIn('有怪=True', lines[0])
        self.assertIn('转向=right', lines[0])

    def test_logs_seek_tick_with_direction(self):
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task.find_mobs = MagicMock(  # 中心 (2030,705):区外;脚底 730,与锚点 720 同层
            return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
        run_with_frame(task)
        lines = self._log_lines(task)
        self.assertEqual(len(lines), 1)
        self.assertIn('有怪=False', lines[0])
        self.assertIn('寻怪=right', lines[0])

    def test_logs_in_zone_side_counts(self):
        """区内左右各有几只——判断"目标是否会在两侧之间跳"的关键数据。"""
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task._facing = 'RIGHT'
        task.find_mobs = MagicMock(return_value=[
            MagicMock(x=1400, y=600, width=60, height=50),   # 中心 (1430,625) 右
            MagicMock(x=1050, y=600, width=60, height=50),   # 中心 (1080,625) 左
        ])
        run_with_frame(task)
        self.assertIn('区内=2(左1/右1)', self._log_lines(task)[0])

    def test_logs_anchor_source_and_sendability(self):
        """锚点来自哪条通道 + 按键此刻能否送出:两个都是排查必需的上下文。"""
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task._executor = SimpleNamespace(
            interaction=SimpleNamespace(clickable=lambda: False))
        task.find_mobs = MagicMock(return_value=[MagicMock(x=1400, y=600, width=60, height=50)])
        run_with_frame(task)
        line = self._log_lines(task)[0]
        self.assertIn('src=fallback', line)   # 角色名为空 → 回退画面中心
        self.assertIn('可发键=False', line)


class TestFacingWriteGuard(unittest.TestCase):
    """按键送不进游戏时,不许把 _facing 改成"已转向"。

    pydirect 的 send_key/send_key_down 在窗口不在前台时只 log 一条 ERROR 就 return
    (ok/device/interaction_methods/pydirect.py:34),而 BaseTask.send_key 照样返回
    True——任务层看不出失败。旧代码在 send_key 之后无条件写 self._facing,于是
    "以为已转向、实际没转",此后 turn_direction 认为朝向正确一直返回 None,
    角色背对着怪按住攻击键且无法自愈。日志实测有 can't click on left/right 记录。
    """

    @staticmethod
    def _task(clickable, **cfg):
        task = make_task(**cfg)
        # executor 是只读 property(ok/task/task.py:111),包的是 _executor
        task._executor = SimpleNamespace(
            interaction=SimpleNamespace(clickable=lambda: clickable))
        return task

    def _run_with_mob_on_right(self, task):
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            mob = MagicMock(x=1500, y=700, width=60, height=50)  # 中心 (1530,725),区内右侧
            task.find_mobs = MagicMock(return_value=[mob])
            run_with_frame(task)

    def test_facing_not_updated_when_window_not_foreground(self):
        task = self._task(False, **{'攻击模式': '检测'})
        task._facing = 'LEFT'
        self._run_with_mob_on_right(task)
        self.assertEqual(task._facing, 'LEFT')  # 转向没送出去,朝向信念不许前进

    def test_turn_key_not_sent_when_window_not_foreground(self):
        task = self._task(False, **{'攻击模式': '检测'})
        task._facing = 'LEFT'
        self._run_with_mob_on_right(task)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('right', sent)

    def test_facing_updated_when_window_is_foreground(self):
        task = self._task(True, **{'攻击模式': '检测'})
        task._facing = 'LEFT'
        self._run_with_mob_on_right(task)
        self.assertIn(call('right', down_time=TURN_TAP_SECONDS), task.send_key.call_args_list)
        self.assertEqual(task._facing, 'RIGHT')

    def test_turn_retried_next_tick_after_foreground_restored(self):
        """失焦拍不改 _facing,是为了下一拍能自动补上转向(自愈)。"""
        task = self._task(False, **{'攻击模式': '检测'})
        task._facing = 'LEFT'
        self._run_with_mob_on_right(task)
        self.assertEqual(task._facing, 'LEFT')  # 失焦这拍:朝向必须原地不动
        task._executor.interaction.clickable = lambda: True
        task._last_detect = 0.0  # 放行下一个检测拍
        self._run_with_mob_on_right(task)
        # 恢复前台后这一拍才真正把转向补上(整轮只送出一次)
        turns = [c for c in task.send_key.call_args_list
                 if c.args and c.args[0] in ('left', 'right')]
        self.assertEqual(turns, [call('right', down_time=TURN_TAP_SECONDS)])
        self.assertEqual(task._facing, 'RIGHT')

    def test_seek_move_does_not_update_facing_when_not_sendable(self):
        task = self._task(False, **{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._seek_dir = 'left'
        task._do_seek_move(task.config, KEYS)
        self.assertEqual(task._facing, 'RIGHT')

    def test_seek_move_updates_facing_when_sendable(self):
        task = self._task(True, **{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._seek_dir = 'left'
        task._do_seek_move(task.config, KEYS)
        self.assertEqual(task._facing, 'LEFT')

    def test_missing_executor_treated_as_sendable(self):
        """裸构造的任务(无 executor)必须按"能发"处理,不改变既有行为。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'LEFT'
        self._run_with_mob_on_right(task)
        self.assertEqual(task._facing, 'RIGHT')


class TestKnockbackReset(unittest.TestCase):
    """受击(被怪打)后朝向信念失效处理。

    2026-08-07 实测:冒险岛被怪碰到会往远离怪物的方向击退并翻转朝向来面对怪物。
    _facing 是盲写信念,击退是唯一破坏源——受击后置 None + 重置转向冷却,
    下一检测拍 attack_turn_direction(None,...) 按最近怪定向重建朝向。
    对"击退翻不翻朝向"两种机制同时正确:翻了你补 tap 是纠错;没翻,朝怪 tap
    50ms 是 no-op(已面朝该侧按方向键零代价)。
    """

    def test_hp_drop_resets_facing_and_turn_cooldown(self):
        """掉血超阈值 → 朝向置 None + 转向冷却重置(0.0 哨兵天然放行)。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'LEFT'
        task._last_turn = 99.9  # 0.1s 前刚转过向,1.5s 冷却未过
        run_with_frame(task, hp=0.5)   # 第一拍:只记基线,不触发
        self.assertEqual(task._prev_hp, 0.5)
        self.assertEqual(task._facing, 'LEFT')  # 没受击,朝向不动
        run_with_frame(task, hp=0.3)   # 掉血 20% → 受击
        self.assertIsNone(task._facing)          # 朝向失效
        self.assertEqual(task._last_turn, 0.0)   # 冷却重置,下拍可立即补转向

    def test_small_hp_drop_keeps_facing(self):
        """微小掉血(≤2%,读数噪声)→ 不算受击,朝向不动。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        run_with_frame(task, hp=0.5)
        run_with_frame(task, hp=0.49)
        self.assertEqual(task._facing, 'RIGHT')

    def test_hp_rise_keeps_facing(self):
        """回血(喝药/自然恢复)→ 不算受击。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        run_with_frame(task, hp=0.3)
        run_with_frame(task, hp=0.6)
        self.assertEqual(task._facing, 'RIGHT')

    def test_facing_unknown_next_detect_turns_to_nearest_mob(self):
        """受击后朝向未知 → 下一检测拍按最近怪定向补转向(闭环自愈)。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'LEFT'
        run_with_frame(task, hp=0.5)   # 基线
        task._facing = None            # 模拟受击置未知(上例已验证触发路径)
        task._last_turn = 0.0
        task._last_detect = 0.0        # 放行检测拍
        task.find_mobs = MagicMock(
            return_value=[MagicMock(x=1500, y=700, width=60, height=50)])
        run_with_frame(task, hp=0.5)
        # fallback 锚点 → 身体 (1280, 630);怪中心 (1530, 725) 在区内右侧
        self.assertIn(call('right', down_time=TURN_TAP_SECONDS),
                      task.send_key.call_args_list)
        self.assertEqual(task._facing, 'RIGHT')

    @staticmethod
    def _hit_lines(task):
        return [c.args[0] for c in task.log_debug.call_args_list
                if c.args and str(c.args[0]).startswith('受击')]

    def test_no_hit_log_by_default(self):
        """决策日志开关默认关 → 受击不写日志(10Hz 主循环下不能默认刷屏)。"""
        task = make_task(**{'攻击模式': '检测'})
        run_with_frame(task, hp=0.5)
        run_with_frame(task, hp=0.3)
        self.assertIsNone(task._facing)          # 机制照常生效
        self.assertEqual(self._hit_lines(task), [])

    def test_hit_log_records_hp_and_facing_before_reset(self):
        """开关打开 → 每次受击写一行,含掉血前后与「作废前」的朝向。

        朝向必须是作废前的值:置 None 之后再取就永远是 '-',这行日志也就
        回答不了"这次受击把哪个朝向打没了",实机排查时等于没写。
        """
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task._facing = 'LEFT'
        run_with_frame(task, hp=0.5)   # 基线拍,不算受击
        self.assertEqual(self._hit_lines(task), [])
        run_with_frame(task, hp=0.3)
        lines = self._hit_lines(task)
        self.assertEqual(len(lines), 1)
        self.assertIn('50.0%', lines[0])
        self.assertIn('30.0%', lines[0])
        self.assertIn('LEFT', lines[0])   # 作废前的朝向,不是 '-'

    def test_no_hit_log_when_drop_below_threshold(self):
        """微小掉血不算受击 → 不写日志(否则读数噪声会把日志刷满)。"""
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task._facing = 'LEFT'
        run_with_frame(task, hp=0.50)
        run_with_frame(task, hp=0.49)
        self.assertEqual(self._hit_lines(task), [])


if __name__ == '__main__':
    unittest.main()
