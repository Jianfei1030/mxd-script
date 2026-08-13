import re
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
import os

import cv2
import numpy as np

from src.detect import anchor
from src.detect.anchor import AnchorHit
from src.task import farm_logic
from src.task.MapleFarmTask import (DEFAULT_CONFIG, TURN_TAP_SECONDS, MapleFarmTask)

FRAME = 'screenshots/test_frames/training_ground_full_2560x1440.png'
KEYS = {'攻击键': 'shift', '血药键': 'home', '蓝药键': 'insert',
        '回城卷键(可留空)': '', '拾取键': 'z', '宠物食物键(可留空)': 'q',
        '椅子键(可留空)': 'r', '左移键': 'left', '右移键': 'right',
        '副攻击键(可留空)': ''}


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
    task.find_all = MagicMock(return_value=[])
    task.get_global_config = MagicMock(return_value=dict(KEYS))
    task._executor = SimpleNamespace(interaction=MagicMock(), sleep=MagicMock())
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
        # 显式群体(对称):该用例测改动前的接敌语义(转向+当拍攻击),不测有向攻击区
        task = make_task(**{'攻击模式': '检测', '攻击区形状': '群体(对称)'})
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
        # 显式群体(对称):该用例测改动前的接敌语义(转向+当拍攻击),不测有向攻击区
        task = make_task(**{'攻击模式': '检测', '攻击区形状': '群体(对称)'})
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

    def test_detect_cadence_drops_to_idle_when_attack_zone_empty_past_grace(self):
        """攻击区空过 寻怪起步宽限 后,下一拍必须按空闲档排,不能还按攻击间隔等。

        分支门(seek_hold)用 寻怪起步宽限(0.3s) 判「该起步寻怪了」,节拍门却收
        _last_attack_present —— 它由 丢怪保持(1.0s) 去抖。两者不同源时存在一种拍:
        攻击区其实早就空了、分支已走寻怪路径,可打= 仍被去抖撑着 True,于是下一拍
        按 攻击间隔 排,起步寻怪白等一个攻击拍(spec §3.1/§3.2 衔接漏洞)。
        2026-08-08 实弹:这种拍占 5.6%(444/7896),其后拍间隔中位 0.708s。

        三拍:在打 → 怪跳到异层(分支走寻怪但没目标,可打仍被撑着) → 同层怪出现。
        第三拍距上一拍 0.35s ≥ 空闲刷新间隔,该跑检测并起步寻怪。
        """
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 0.7})
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task)                      # 100.0 在打:怪在攻击区
            self.assertTrue(task._last_attack_present)
            # 100.7 怪跳到异层远处:分支走寻怪(宽限已过)但找不到同层怪,
            # 可打= 仍被 丢怪保持 撑着 True —— 这就是中招拍
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=500, width=60, height=50)])
            run_with_frame(task, now=100.7)
            self.assertTrue(task._last_attack_present)   # 去抖撑着(这是前提,不是被测行为)
            self.assertIsNone(task._seek_dir)
            # 101.05 同层怪出现:距上一检测拍 0.35s ≥ 空闲刷新间隔 0.3s → 该起步寻怪
            task.find_mobs = MagicMock(return_value=[MagicMock(x=2000, y=680, width=60, height=50)])
            run_with_frame(task, now=101.05)
        self.assertEqual(task._seek_dir, 'right')

    def test_detect_cadence_stays_at_attack_rate_while_mob_in_zone(self):
        """稳态在打时节拍仍是 攻击间隔,不因上一条的短宽限塌成空闲档(§3.1 负载不回归)。

        断 _last_detect:它只在真跑检测拍时被写。变异验证:把 _detect_attacking
        恒置 False(等价于按 now 现算导致攻击档塌陷),本用例转红。
        """
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 0.7})
        # 稳态前提:面朝右、怪在右侧 → 首拍不转向。转向落地会作废检测节拍
        # (2026-08-09 计划 Task 2 的意图),首拍转向的话断言量的就不是"稳态节拍"
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            task.find_mobs = MagicMock(return_value=[MagicMock(x=1300, y=700, width=60, height=50)])
            run_with_frame(task)                        # 100.0 检测拍
            self.assertEqual(task._last_detect, 100.0)
            run_with_frame(task, now=100.35)            # 0.35s < 攻击间隔 → 不跑检测
            self.assertEqual(task._last_detect, 100.0)
            run_with_frame(task, now=100.75)            # ≥ 攻击间隔 → 跑
            self.assertEqual(task._last_detect, 100.75)

    def test_turn_invalidates_detect_cadence(self):
        """转向落地 → 作废检测节拍,下一拍不再按 攻击间隔 等。

        攻击区是按本拍转向**之前**的朝向算的(:583 的 spec §5.1 注释,本计划
        不推翻),新朝向要下一拍才生效;而转向只发生在接战分支,那一拍
        _detect_attacking 常被 寻怪起步宽限 撑着 True → 下一拍按 攻击间隔 排,
        攻击区因此要等 0.7s 才翻过去。2026-08-08 实弹:端到端延迟 p90=0.627s、
        p99=1.103s,转向拍到下一拍的间隔 p90=0.706s(正好一个攻击间隔)。

        寻怪起步宽限 调到 1.0 是为了把「节拍仍在攻击档」这个前提坐实
        (默认 0.3 时 100.7 已出宽限,会退化成空闲档,测不到最坏情况)。
        变异验证:删掉实现里的 `self._last_detect = 0.0`,本用例转红。
        """
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 0.7,
                            '寻怪起步宽限(秒)': 1.0})
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            # 100.0 面朝右、右侧有怪:在打
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=1500, y=700, width=60, height=50)])
            run_with_frame(task)
            self.assertTrue(task._last_attack_present)   # 前提
            # 100.7 怪换到左侧:发左转向。此拍 _detect_attacking 仍被 1.0s 宽限撑着,
            # 攻击区还锚在右半边(本拍决策照旧,这是设计)
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=960, y=700, width=60, height=50)])
            run_with_frame(task, now=100.7)
            self.assertEqual(task._facing, 'LEFT')
            self.assertTrue(task._detect_attacking)      # 前提:节拍仍在攻击档
            # 100.8 距上一拍仅 0.1s < 攻击间隔 —— 修复前这一拍根本不跑检测
            run_with_frame(task, now=100.8)
        self.assertEqual(task._last_detect, 100.8)       # 检测拍真的跑了
        self.assertTrue(task._last_attack_present)       # 攻击区已翻到左半边,罩住了怪

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
        暂停后 run() 不再被调用,不松键角色会一直走下去。
        2026-08-10 修复:暂停回调走 interaction 轻量路径(不走 send_key_up →
        reset_scene → check_enabled 的 sleep(1) 阻塞链,那是 F9 暂停后 GUI
        未响应的根因),所以断言 interaction.send_key_up 而不是 task.send_key_up。"""
        task = make_task()
        task._seek_dir = 'right'
        task._do_seek_move(task.config, KEYS)
        task._on_executor_paused(True)
        task._executor.interaction.send_key_up.assert_called_once_with('right')
        self.assertIsNone(task._seek_key)
        # 恢复:下一拍重新按下
        task._do_seek_move(task.config, KEYS)
        self.assertEqual(task.send_key_down.call_args_list, [call('right'), call('right')])

    def test_executor_pause_uses_light_path_not_send_key_up(self):
        """暂停回调必须走轻量路径:send_key_up → reset_scene → check_enabled 在
        paused=True 时触发 executor.sleep(1),在 GUI 主线程跑满 1 秒 = GUI 未响应。
        task.send_key_up 不该被暂停回调调用。"""
        task = make_task()
        task._seek_dir = 'right'
        task._seek_key = '右移键'
        task._do_seek_move(task.config, KEYS)
        task._on_executor_paused(True)
        task.send_key_up.assert_not_called()

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
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_never_holds_attack_key(self):
        """核心回归:攻击键不许再走 send_key_down 长按。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_attack_present = True
        for i in range(5):
            task._do_attack(task.config, KEYS, now=100.0 + i * 2.0)
        task.send_key_down.assert_not_called()
        self.assertFalse(task._attack_held)

    def test_respects_attack_interval(self):
        """同一个 攻击间隔 内只点一次,不被 10Hz 主循环连点。"""
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task._do_attack(task.config, KEYS, now=101.0)   # 未满 1.5s
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_taps_again_after_interval(self):
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task._do_attack(task.config, KEYS, now=101.5)
        self.assertEqual(task.send_key.call_args_list, [call('shift'), call('shift')])

    def test_no_tap_before_first_detection(self):
        """启动后还没检测过(_last_attack_present 初始 None)→ 不按攻击键。"""
        task = make_task(**{'攻击模式': '检测'})
        task._do_attack(task.config, KEYS, now=100.0)
        task.send_key.assert_not_called()

    def test_no_tap_when_mob_gone(self):
        task = make_task(**{'攻击模式': '检测'})
        task._last_attack_present = False
        task._do_attack(task.config, KEYS, now=100.0)
        task.send_key.assert_not_called()

    def test_fixed_mode_not_handled_here(self):
        """定频模式的定时轻点在 run() 里,本方法不重复按。"""
        task = make_task(**{'攻击模式': '定频'})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task.send_key.assert_not_called()

    def test_pause_and_disable_do_not_touch_attack_key(self):
        """不再长按后,暂停/停任务无需松攻击键(方向键的松开另有用例覆盖)。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        task._on_executor_paused(True)
        self.assertNotIn(call('shift'), task.send_key_up.call_args_list)

    def test_pad_step_fires_when_recently_attacking(self):
        """攻击间隔内(有攻击记录)→垫步触发(2秒禁垫步条件放行)。"""
        task = make_task(**{'攻击模式': '检测', '攻击前垫步开关': True, '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._last_zone = ((980, 530, 1580, 730))
        task._last_centres = [(1100, 640)]
        task._last_body_x = 1280
        # _last_attack=98.5 → now=100 差 1.5s = 间隔(should_attack 放行),且 1.5<2(垫步放行)
        task._last_attack = 98.5
        task._do_attack(task.config, KEYS, now=100.0)
        # 应该有攻击键 + 垫步方向键共 2 次 send_key
        self.assertEqual(task.send_key.call_count, 2)
        first_call_key = task.send_key.call_args_list[0][0][0]
        self.assertIn(first_call_key, ('left', 'right'))  # 先垫步
        second_call_key = task.send_key.call_args_list[1][0][0]
        self.assertEqual(second_call_key, 'shift')  # 后攻击

    def test_pad_step_skipped_when_idle_2s(self):
        """2秒没攻击(空闲/寻怪中)→不触发垫步,只按攻击键。"""
        task = make_task(**{'攻击模式': '检测', '攻击前垫步开关': True, '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._last_zone = ((980, 530, 1580, 730))
        task._last_centres = [(1100, 640)]
        task._last_body_x = 1280
        task._last_attack = 97.0  # 3秒前 → now - last_attack = 3 > 2
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_count, 1)
        self.assertEqual(task.send_key.call_args_list[0][0][0], 'shift')

    def test_pad_step_fires_on_first_attack(self):
        """首次攻击(_last_attack=0.0哨兵)→垫步仍触发(哨兵特殊处理)。"""
        task = make_task(**{'攻击模式': '检测', '攻击前垫步开关': True, '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._last_zone = ((980, 530, 1580, 730))
        task._last_centres = [(1500, 640)]
        task._last_body_x = 1280
        # _last_attack 保持默认 0.0（哨兵，从未攻击过）
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_count, 2)

    def test_double_attack_off_by_default(self):
        """二连击默认关闭:只按攻击键,不按副攻击键。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_double_attack_fires_both_keys_back_to_back(self):
        """二连击开启 + 副攻击键已绑定:先攻击键、立即副攻击键,两键相邻。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True})
        task._last_attack_present = True
        task._do_attack(task.config, keys, now=100.0)
        self.assertEqual(task.send_key.call_args_list,
                         [call('shift'), call('x')])

    def test_double_attack_skipped_when_subkey_empty(self):
        """二连击开启但副攻击键留空 → 视为关闭,只按攻击键(同群攻键约定)。"""
        task = make_task(**{'攻击模式': '检测', '二连击开关': True})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_double_attack_skips_pad_step(self):
        """二连击开启时跳过攻击前垫步:方向键不许插入攻击-副攻击之间。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True,
                            '攻击前垫步开关': True, '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._last_zone = ((980, 530, 1580, 730))
        task._last_centres = [(1100, 640)]
        task._last_body_x = 1280
        task._last_attack = 98.5  # 垫步条件本应放行(1.5s<2s)
        task._do_attack(task.config, keys, now=100.0)
        self.assertEqual(task.send_key.call_args_list,
                         [call('shift'), call('x')])
        # 无任何方向键插入
        for c in task.send_key.call_args_list:
            self.assertNotIn(c.args[0], ('left', 'right'))

    def test_double_attack_respects_attack_interval(self):
        """二连击共用 攻击间隔 节拍:同一间隔内只发一轮,不连发。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True,
                            '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._do_attack(task.config, keys, now=100.0)
        task.send_key.reset_mock()
        task._do_attack(task.config, keys, now=101.0)  # 未满 1.5s
        task.send_key.assert_not_called()

    def test_double_attack_aoe_path_unaffected(self):
        """群攻路径零改动:区内怪数达阈值时只按群攻键,不做二连击。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x',
                             '群攻键(可留空)': 'a'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True,
                            '群攻怪数阈值': 2})
        task._last_zone_count = 3
        task._last_zone_count_time = 100.0
        task._last_attack = 0.0
        task._do_attack(task.config, keys, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('a')])

    def test_double_attack_sleeps_between_hits(self):
        """二连击两下之间 sleep 攻击间隔(秒):零间隔时第二下被游戏输入采样吞掉。
        间隔直接取「攻击间隔(秒)」配置,不另设 hardcode。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True,
                            '攻击间隔(秒)': 0.2})
        task._last_attack_present = True
        task._do_attack(task.config, keys, now=100.0)
        # 先攻击键 → sleep(0.2) → 副攻击键
        self.assertEqual(task.send_key.call_args_list,
                         [call('shift'), call('x')])
        task._executor.sleep.assert_called_once_with(0.2)

    def test_double_attack_sleep_uses_attack_interval_default(self):
        """二连击间隔 = 攻击间隔默认值(1.5s),不是独立 hardcode 值。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True})
        task._last_attack_present = True
        task._do_attack(task.config, keys, now=100.0)
        task._executor.sleep.assert_called_once_with(1.5)


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
        task._last_identity_hit = 99.9  # 身份新鲜:身份复验(§3.7)会绕过常规节流,
                                        # 断言"慢通道没被调用"必须先把这个维度钉住
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
        self.assertEqual(got.x, 1280 + 500.0)                     # 600 → 钳 500
        self.assertEqual(got.y, 800.0)           # y 不推(同平台稳定)
        window.assert_called_once()
        self.assertEqual(window.call_args[0][2], (1280 + 500.0, 800.0))  # 小窗跟外推位置

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

    def test_reverse_learned_vx_does_not_escape(self):
        """回归(08-10 19:56 钳位铁证):学到 +vx(击退向右)但寻怪向左 →
        外推不许往右逃,退回配置速度×寻怪方向。
        速度取 150:150*3=450 < 500 不触帽——这条只测方向,与
        test_extrapolation_capped_at_max_dx 职责分离。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 150})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._anchor_vx = 75.0           # 击退残余(向右)
        task._last_anchor_hit = 102.0    # 实测速度仍新鲜
        task._seek_dir = 'left'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(got.x, 1280 - 150 * 3)  # 830;旧逻辑会给 1280+75*3=1505

    def test_extrapolation_capped_at_max_dx(self):
        """丢锚期外推位移封顶 ±500(拆振荡回路,08-10 21:18 外推↔寻怪反馈):
        年龄再大,位移也不超 2s 行走量。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 250})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = 'right'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 108.0, task.config)
        self.assertEqual(got.x, 1280 + 500.0)  # 250*8=2000 → 钳 500

    def test_extrapolation_clamped_to_frame_edge(self):
        """封顶与帧边界 [0,2560] 的复合(spec §6):锚点在 x=100、寻怪 left →
        dx 钳 -500 后 x=-400,再钳到 0,绝不出负坐标。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 250})
        task._anchor = (100.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = 'left'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 106.0, task.config)
        self.assertEqual(got.x, 0.0)

    def test_oscillation_bounded_when_seek_flips(self):
        """回归(spec §6 振荡剧本,08-10 21:18):丢锚期寻怪方向每拍翻转,
        相邻 cached 拍 |Δbody_x| ≤ 2×500=1000(旧逻辑外推位移随年龄无界,
        实测单拍跳 ±1250px+,门中心跟着瞬移,YOLO 关联被主动压死)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 250})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        xs = []
        for i, d in enumerate(['right', 'left', 'right', 'left']):
            task._seek_dir = d
            with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                    patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
                got, source = task._resolve_anchor(_synthetic_frame(), 106.0 + i, task.config)
            self.assertEqual(source, 'cached')
            xs.append(got.x)
        self.assertTrue(all(abs(b - a) <= 1000 for a, b in zip(xs, xs[1:])),
                        xs)


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
        # 显式群体(对称):该用例测改动前的接敌语义(当拍转向+当拍攻击),不测有向攻击区
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', '走位开关': False,
                            '攻击区宽(像素)': 1200, '攻击区形状': '群体(对称)'})
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
                         attack_area=(1000, 600, 1500, 800), mobs=[], mob_present=False,
                         attack_present=False)
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
                         attack_area=(1000, 600, 1500, 800), mobs=[mob], mob_present=True,
                         attack_present=True)
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
                         attack_area=(1000, 600, 1500, 800), mobs=[], mob_present=False,
                         attack_present=False)
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

    def test_overlay_draws_the_zone_that_takes_effect_after_the_turn(self):
        """转向那一拍,悬浮窗画的是转向**之后**生效的攻击区。

        决策仍用转向前的 attack_area(spec §5.1,Task 2 也没动它),
        但画框若跟着用它,悬浮窗就永远比角色朝向慢一拍,排查时会把
        「节拍慢」误读成「转了但攻击区没跟上」。
        变异验证:把 draw_area 改回 attack_area,本用例转红。
        """
        task = make_task(**{'攻击模式': '检测'})   # 默认 单体(面朝)
        task._facing = 'RIGHT'
        task._boxes_enabled = MagicMock(return_value=True)
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')), \
                patch.object(MapleFarmTask, '_draw_debug') as draw:
            # 怪在左侧、面朝右 → 本拍发左转向
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=960, y=700, width=60, height=50)])
            run_with_frame(task)
        self.assertEqual(task._facing, 'LEFT')
        draw.assert_called_once()
        _, kwargs = draw.call_args
        # 左半区:右边界 = 身体 x(1280)。修复前画的是右半区,左边界才是 1280
        self.assertEqual(kwargs['attack_area'][2], 1280)

    def test_overlay_group_shape_unaffected_by_turn(self):
        """群体(对称)下攻击区就是整个接敌区,转向不该把它砍成一半。"""
        task = make_task(**{'攻击模式': '检测', '攻击区形状': '群体(对称)'})
        task._facing = 'RIGHT'
        task._boxes_enabled = MagicMock(return_value=True)
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')), \
                patch.object(MapleFarmTask, '_draw_debug') as draw:
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=960, y=700, width=60, height=50)])
            run_with_frame(task)
        _, kwargs = draw.call_args
        self.assertEqual(kwargs['attack_area'], kwargs['zone'])


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
        """保持窗内不许改去寻怪:刚打的目标只是漏检一拍,走开就更打不到了。

        2026-08-08 起「保持窗」改用 寻怪起步宽限(0.3s) 而非 丢怪保持(1.0s):
        单帧漏检(节拍 0.1s)仍在窗内被挡住,不会一拍漏检就迈腿;
        0.3s 之后即允许起步(spec §3.2)。"""
        task = self._task(**{'丢怪保持(秒)': 1.0, '寻怪起步宽限(秒)': 0.3})
        self._tick(task, [self.RIGHT_MOB], now=100.0)
        # 区外同层远怪(中心 2030,705;脚底 730 与锚点 720 同层)
        self._tick(task, [dict(x=2000, y=680, width=60, height=50)], now=100.2)
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

    def test_hp_drop_keeps_facing_and_resets_turn_cooldown(self):
        """掉血超阈值 → 转向冷却重置,但**朝向保留**。

        2026-08-08 改:此用例原先断言 `_facing is None`(受击作废朝向)。那行清空
        已经删掉——它的唯一前提「受击可能让朝向失效」被观测数据证伪(52 个分歧
        事件里受击后 0.5s 内一次都没有),而清空的代价是确定的:facing_half_zone
        在 None 时退化成整个对称区,实测 19 拍朝背后开火。见
        docs/superpowers/specs/2026-08-08-facing-correction-design.md §2.2/§2.3。
        `_last_turn = 0.0` 未动,仍在本用例的断言里。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'LEFT'
        task._last_turn = 99.9  # 0.1s 前刚转过向,1.5s 冷却未过
        run_with_frame(task, hp=0.5)   # 第一拍:只记基线,不触发
        self.assertEqual(task._prev_hp, 0.5)
        self.assertEqual(task._facing, 'LEFT')  # 没受击,朝向不动
        run_with_frame(task, hp=0.3)   # 掉血 20% → 受击
        self.assertEqual(task._facing, 'LEFT')   # 受击不作废朝向
        self.assertEqual(task._last_turn, 0.0)   # 冷却仍重置,下拍可立即补转向

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


class TestAttackZoneShapeConfig(unittest.TestCase):
    """攻击区形状配置项。群体(对称)是安全退路,必须逐键等同于改动前行为。"""

    def test_default_is_directional(self):
        """默认单体:用户技能是魔法箭(面朝向直线),对称区从建模上就错。"""
        self.assertEqual(DEFAULT_CONFIG['攻击区形状'], '单体(面朝)')

    def test_registered_as_drop_down(self):
        """GUI 里必须是下拉,不能是自由文本框——手打错一个字就静默退回对称区。"""
        task = make_task()
        task.config_type = {}
        MapleFarmTask._register_config_types(task)
        self.assertEqual(task.config_type['攻击区形状'],
                         {'type': 'drop_down', 'options': ['单体(面朝)', '群体(对称)']})


class TestDirectionalAttackZone(unittest.TestCase):
    """有向攻击区:「能不能打到」与「要不要转向」分开判(spec §4)。

    几何:角色名为空 → 锚点回退画面中心 (1280, 720) → 身体 (1280, 630);
    默认 攻击区宽=600 高=200 → 接敌区 x∈[980,1580] y∈[530,730]。
    面朝右的攻击区 = x∈[1280,1580];面朝左 = x∈[980,1280]。
    怪框 (x, y, w, h) 的中心 = (x + w/2, y + h/2)。
    """

    LEFT_MOB = dict(x=1020, y=605, width=60, height=50)    # 中心 (1050, 630) 在左半区
    RIGHT_MOB = dict(x=1450, y=605, width=60, height=50)   # 中心 (1480, 630) 在右半区

    @staticmethod
    def _attacked(task, keys):
        return call(keys['攻击键']) in task.send_key.call_args_list

    def _run(self, task, mob):
        task.find_mobs = MagicMock(return_value=[MagicMock(**mob)])
        run_with_frame(task)

    def test_directional_attacks_mob_on_facing_side(self):
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        self._run(task, self.RIGHT_MOB)
        self.assertTrue(task._last_attack_present)
        self.assertTrue(self._attacked(task, KEYS))

    def test_directional_does_not_attack_mob_behind_while_turn_on_cooldown(self):
        """核心回归(spec §1):面朝右、怪只在左、转向冷却未过 → 一定不按攻击键。

        改动前:mob_present 来自对称区 → True → _do_attack 照按 → 面朝右打左边的怪。
        转向冷却 1.5s 比攻击间隔还长,这个窗口一点都不罕见。
        """
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._last_turn = 99.9          # run_with_frame 默认 now=100.0,即 0.1s 前刚转过向
        self._run(task, self.LEFT_MOB)
        self.assertTrue(task._last_mob_present)      # 接敌区有怪:不寻怪、不坐椅
        self.assertFalse(task._last_attack_present)  # 攻击区没怪
        self.assertFalse(self._attacked(task, KEYS))

    def test_turn_this_tick_still_no_attack_until_next_tick(self):
        """冷却已过 → 本拍转向,但本拍仍不攻击;下一拍朝向已对才攻击。

        攻击区用的是本拍转向「之前」的朝向——用转向后的新 _facing 立刻判定,
        等于又一次相信"我按了键所以已经转过去了"这个盲写信念,而那正是
        这一系列 bug 的来源(spec §5.1)。
        """
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._last_turn = 0.0           # 哨兵:冷却天然放行
        self._run(task, self.LEFT_MOB)
        self.assertIn(call(KEYS['左移键'], down_time=TURN_TAP_SECONDS),
                      task.send_key.call_args_list)
        self.assertFalse(self._attacked(task, KEYS))
        self.assertEqual(task._facing, 'LEFT')

        task.send_key.reset_mock()
        task._last_attack = 0.0         # 放行攻击间隔
        task._last_detect = 0.0         # 放行检测拍
        self._run(task, self.LEFT_MOB)
        self.assertTrue(self._attacked(task, KEYS))

    def test_unknown_facing_falls_back_to_symmetric(self):
        """朝向未知 → 攻击区 = 整个接敌区(spec §4.3),不制造挂死风险。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = None
        self._run(task, self.LEFT_MOB)
        self.assertTrue(task._last_attack_present)

    def test_aoe_shape_is_key_for_key_identical_to_symmetric(self):
        """群体(对称)必须逐键等同于改动前:安全退路。"""
        task = make_task(**{'攻击模式': '检测', '攻击区形状': '群体(对称)'})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        self._run(task, self.LEFT_MOB)
        self.assertTrue(task._last_attack_present)
        self.assertTrue(self._attacked(task, KEYS))

    def test_mob_behind_does_not_trigger_seek(self):
        """怪在背侧走「转向」分支而不是「寻怪」分支——接敌区仍然有怪。"""
        task = make_task(**{'攻击模式': '检测'})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        self._run(task, self.LEFT_MOB)
        self.assertIsNone(task._seek_dir)

    def test_sit_still_driven_by_engage_zone(self):
        """坐椅/走位/忙判定问的是「附近有没有怪」,不是「打不打得到」——
        怪在背侧(打不到但就在旁边)时不许坐下。直接把 _last_mob_present
        换成有向的会一起改坏这三者,本例守住其中最容易观察的坐椅。"""
        task = make_task(**{'攻击模式': '检测', '坐椅开关': True, '坐椅延迟(秒)': 0.0})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        self._run(task, self.LEFT_MOB)
        self.assertFalse(task._last_attack_present)   # 确实打不到
        self.assertNotIn(call(KEYS['椅子键(可留空)']), task.send_key.call_args_list)
        self.assertTrue(task._last_busy > 0)          # 但算「忙」,走位倒计时重算

    def test_attack_debounce_is_independent(self):
        """攻击区自己一路去抖:漏检一拍,丢怪保持 内仍算能打
        (YOLO 单帧 recall 0.886,且角色自己的攻击特效会遮挡目标)。"""
        task = make_task(**{'攻击模式': '检测', '丢怪保持(秒)': 1.0})
        task._facing = 'RIGHT'
        self._run(task, self.RIGHT_MOB)
        self.assertTrue(task._last_attack_present)
        task.find_mobs = MagicMock(return_value=[])      # 这一拍漏检
        task._last_detect = 0.0
        run_with_frame(task, now=100.5)                  # 0.5s 后,仍在 1.0s 保持内
        self.assertTrue(task._last_attack_present)

    def test_mob_crosses_behind_clears_attack_immediately(self):
        """怪从面朝侧绕到背侧:即使在 丢怪保持 窗口内,攻击信号必须立刻清。
        去抖保持是为 YOLO 漏检(整拍无怪)设计的,不是为"确定性换边"设计的——
        保持会把 §1 的空按从"无限"降级成"每次换边 ≤1 秒"的有界残余。"""
        task = make_task(**{'攻击模式': '检测', '丢怪保持(秒)': 1.0})
        task._facing = 'RIGHT'
        self._run(task, self.RIGHT_MOB)      # 第一拍:怪在面朝侧,进入攻击态
        self.assertTrue(task._last_attack_present)
        task.send_key.reset_mock()           # 清掉第一拍的攻击轻点,只断言换边拍的按键
        task._last_detect = 0.0
        task._last_turn = 99.9               # 转向冷却未过,挡住转向
        self._run(task, self.LEFT_MOB)       # 第二拍:怪已绕到背侧,仍在保持窗口内
        self.assertFalse(task._last_attack_present)   # 修复前此断言失败(保持吞掉换边)
        self.assertFalse(self._attacked(task, KEYS))


class TestDirectionalDecisionLog(unittest.TestCase):
    """决策日志要能回答「有向区到底生效没有」——这是实弹判据 A 的唯一数据源。"""

    @staticmethod
    def _lines(task):
        return [c.args[0] for c in task.log_debug.call_args_list
                if c.args and str(c.args[0]).startswith('决策')]

    def test_logs_attack_zone_count_and_flag(self):
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        task._facing = 'RIGHT'
        task._last_turn = 99.9
        task.find_mobs = MagicMock(return_value=[
            MagicMock(x=1020, y=605, width=60, height=50),   # 中心 1050,接敌区内、攻击区外
            MagicMock(x=1450, y=605, width=60, height=50),   # 中心 1480,两个区都在内
        ])
        run_with_frame(task)
        line = self._lines(task)[0]
        self.assertIn('区内=2', line)
        self.assertIn('可打区内=1', line)
        self.assertIn('可打=True', line)

    def test_attack_count_never_exceeds_engage_count(self):
        """单体模式下 可打区内 <= 区内 必须恒成立(判据 A 的几何自洽检查)。"""
        task = make_task(**{'攻击模式': '检测', '决策日志开关': True})
        for facing in ('LEFT', 'RIGHT', None):
            task._facing = facing
            task._last_detect = 0.0
            task.find_mobs = MagicMock(return_value=[
                MagicMock(x=1020, y=605, width=60, height=50),
                MagicMock(x=1450, y=605, width=60, height=50),
            ])
            run_with_frame(task)
        for line in self._lines(task):
            engage = int(re.search(r'区内=(\d+)', line).group(1))
            attack = int(re.search(r'可打区内=(\d+)', line).group(1))
            self.assertLessEqual(attack, engage, line)


class TestFacingObserver(unittest.TestCase):
    """朝向观测器是只读的:它绝不能改变任何决策。"""

    def test_observer_off_by_default(self):
        task = make_task()
        self.assertFalse(task.config['朝向观测开关'])

    def test_no_observation_when_switch_off(self):
        task = make_task()
        task.config['朝向观测开关'] = False
        with patch('src.detect.facing.observe') as m:
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)
        m.assert_not_called()

    def test_no_observation_on_cached_anchor(self):
        """cached/fallback 的锚点会让 ROI 整体错位(附录 A.3),不许观测。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._facing_template = np.zeros((66, 58), dtype=np.uint8)
        task._facing_template_dir = 'RIGHT'
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), 'cached')), \
             patch('src.detect.facing.observe') as m:
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)
        m.assert_not_called()

    def test_observation_never_writes_facing_when_correction_off(self):
        """纠正关掉时,观测器必须退回纯只读:结果只进日志,不碰 _facing。

        2026-08-08 改:此用例原先不带 `朝向纠正开关=False`,断言的是「观测永不
        写回」。观测器已按事先写死的判据(A=77.3%≥50%、B=0.4%≤5%)升级成纠正器,
        写回是它现在的正常职责;这条改为守「关掉开关就退回只读」这个退路。
        纠正本身的行为由 TestFacingCorrection 覆盖。"""
        task = make_task(朝向纠正开关=False)
        task.config['朝向观测开关'] = True
        task._facing = 'LEFT'
        task._facing_template = np.zeros((66, 58), dtype=np.uint8)
        task._facing_template_dir = 'RIGHT'
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), 'window')), \
             patch('src.detect.facing.observe', return_value=('RIGHT', 0.88, 0.47)):
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)
        self.assertEqual(task._facing, 'LEFT')   # 观测说 RIGHT,信念不许被改

    def test_observation_exception_does_not_propagate(self):
        """观测器不能把挂机搞崩(与 YOLO/模板匹配同样处理)。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._facing_template = np.zeros((66, 58), dtype=np.uint8)
        task._facing_template_dir = 'RIGHT'
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), 'window')), \
             patch('src.detect.facing.observe', side_effect=RuntimeError('boom')):
            task._detect_and_act(_synthetic_frame(), 100.0, task.config, KEYS)   # 不抛即通过

    def test_template_captured_only_after_confirmed_walk(self):
        """位移没确认之前不许采模板 —— 采错方向后面所有观测全错。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._seek_key = '右移键'
        task._seek_dir = 'right'
        task._seek_start_body_x = 1000.0
        with patch('src.detect.facing.capture') as m:
            # 必须带 text 的 AnchorHit:裸 Anchor 没有 text 字段,会先死在 OCR
            # 完整命中那道门,根本走不到 walk_confirmed —— 守卫就白写了
            # (2026-08-08 评审发现,变异验证:删掉守卫后此测试必须失败)。
            task._maybe_capture_facing_template(_synthetic_frame(),
                                                anchor.AnchorHit(1010.0, 720.0, 130, 'Yufeng咕咕'),
                                                'window', 'Yufeng咕咕')
        m.assert_not_called()      # 只走了 10px < 40

    def test_template_captured_records_direction(self):
        task = make_task()
        task.config['朝向观测开关'] = True
        task._seek_key = '右移键'
        task._seek_dir = 'right'
        task._seek_start_body_x = 1000.0
        hit = anchor.AnchorHit(1100.0, 720.0, 130, 'Yufeng咕咕')
        with patch('src.detect.facing.capture',
                   return_value=np.ones((66, 58), dtype=np.uint8)), \
             patch.object(anchor, 'save_template'):
            task._maybe_capture_facing_template(_synthetic_frame(), hit, 'window', 'Yufeng咕咕')
        self.assertEqual(task._facing_template_dir, 'RIGHT')
        self.assertIsNotNone(task._facing_template)

    def test_template_not_captured_on_partial_ocr(self):
        """部分匹配 'ng咕咕' 的框中心系统性右偏(附录 A.3),裁出来是草地和宠物脸。"""
        task = make_task()
        task.config['朝向观测开关'] = True
        task._seek_key = '右移键'
        task._seek_dir = 'right'
        task._seek_start_body_x = 1000.0
        hit = anchor.AnchorHit(1100.0, 720.0, 130, 'ng咕咕')
        with patch('src.detect.facing.capture') as m:
            task._maybe_capture_facing_template(_synthetic_frame(), hit, 'window', 'Yufeng咕咕')
        m.assert_not_called()


class TestFacingCorrection(unittest.TestCase):
    """朝向纠正(spec 2026-08-08-facing-correction-design)。

    几何前提照 memory:角色名为空串 → 锚点回退画面中心 (1280,720)、
    身体 (1280,630)、默认接敌区 x∈[980,1580] y∈[530,730]。

    隔离要点:区内有怪时,既有的转向逻辑自己就会翻 _facing,纠正与转向的
    效果分不开。所以除「攻击区」那条外一律用**空区**(find_mobs 返回 [])——
    mob_present=False 时整个转向分支被跳过,_facing 只可能被纠正改动。
    """

    LEFT_MOB = SimpleNamespace(x=1120, y=570, width=80, height=120)  # 中心 (1160,630),身体左侧

    def _task(self, mobs=(), **cfg):
        task = make_task(决策日志开关=True, **cfg)
        task._facing = 'LEFT'
        task._facing_template = np.zeros((66, 58), dtype=np.uint8)
        task._facing_template_dir = 'RIGHT'
        task.find_mobs = MagicMock(return_value=list(mobs))
        return task

    def _run(self, task, observed='RIGHT', source='window'):
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), source)),              patch('src.detect.facing.observe',
                   return_value=(observed, 0.88, 0.47)),              patch('time.time', return_value=200.0):
            task._detect_and_act(_synthetic_frame(), 200.0, task.config, KEYS)

    def test_hit_does_not_clear_facing(self):
        """受击不再作废朝向:52 个分歧事件里受击后 0.5s 内一次都没有,
        「受击会翻朝向」这个唯一前提已被观测数据证伪(spec §2.2)。

        走位开关必须关掉:`_last_walk` 初值 0.0,now=200 早就过了 120s 间隔,
        无怪时防挂机走位会触发,而首次走位在「自动」朝向下是**随机**选边并写回
        `_facing` —— 不关它,这条断言有一半概率靠运气蒙对,守不住任何东西
        (2026-08-08 变异验证发现:把清空加回来,测试照样通过)。"""
        task = make_task(走位开关=False)
        task._facing = 'LEFT'
        task._prev_hp = 0.90
        run_with_frame(task, hp=0.80, now=200.0)
        self.assertGreater(task._last_hit, 0.0, '前置:这一拍必须真判成受击')
        self.assertEqual(task._facing, 'LEFT')

    def test_correction_writes_observed_facing(self):
        """空区(不会转向)下信念只可能被纠正改动。"""
        task = self._task()
        self._run(task)
        self.assertEqual(task._facing, 'RIGHT')

    def test_correction_applies_to_this_tick_attack_area(self):
        """纠正必须落在 facing_half_zone 取用 _facing 之前 —— 晚一行,
        本拍攻击区仍按错朝向算,白纠正一拍。

        场景就是实测到的 A 类危害:怪在左、信念也说左(目标侧锁定 → 不转向),
        而角色实际朝右。不纠正 → 攻击区=左半区 → 怪在区内 → 可打=True →
        朝右边空处放技能。纠正后攻击区=右半区 → 怪不在区内 → 不开火。
        (断言 _facing 在这里无效:纠正后转向逻辑本拍就会把它翻回来)"""
        task = self._task(mobs=[self.LEFT_MOB])
        self._run(task)
        self.assertFalse(task._last_attack_present)

    def test_correction_off_keeps_belief(self):
        task = self._task(朝向纠正开关=False)
        self._run(task)
        self.assertEqual(task._facing, 'LEFT')

    def test_divergence_line_uses_pre_correction_belief(self):
        """纠正会让 facing_before 恒等于纠正后的值,朝向分歧行永不触发 ——
        修复把测量它的仪器弄瞎了(spec §3.4)。分歧行必须用纠正前的信念。

        变异守卫:把 divergence_log_line 的传参改成纠正后的信念,本用例必须红。
        分歧行归「日志详略」管(spec §3.5),所以要显式开 朝向观测开关。"""
        task = self._task(朝向观测开关=True)
        self._run(task)
        lines = [c.args[0] for c in task.log_debug.call_args_list if c.args]
        div = [l for l in lines if '朝向分歧' in l]
        self.assertEqual(len(div), 1, '纠正发生时必须仍然留下分歧记录')
        self.assertIn('信念=LEFT', div[0])
        self.assertIn('实测=RIGHT', div[0])

    def test_abstain_leaves_belief_untouched(self):
        task = self._task()
        self._run(task, observed=None)
        self.assertEqual(task._facing, 'LEFT')

    def test_cached_anchor_does_not_correct(self):
        """cached/fallback 锚点的 ROI 整体错位,不许据此纠正。"""
        task = self._task()
        self._run(task, source='cached')
        self.assertEqual(task._facing, 'LEFT')

    def test_no_template_does_not_correct(self):
        """还没采到模板 → 不观测不纠正,行为与改动前一致。"""
        task = self._task()
        task._facing_template = None
        with patch.object(task, '_resolve_anchor',
                          return_value=(anchor.Anchor(1280.0, 720.0, 130), 'window')),              patch('time.time', return_value=200.0):
            task._detect_and_act(_synthetic_frame(), 200.0, task.config, KEYS)
        self.assertEqual(task._facing, 'LEFT')


class TestDecisionLogVerticalFields(unittest.TestCase):
    """决策行的怪纵向字段 —— Task 6 改同层口径之前唯一的观测手段。

    字段格式只有一处事实源(decision_log_line),这里断言的是它的输出,
    不手抄格式串(见 tests/test_analyze_facing.py 顶部关于假绑定的记录)。"""

    def _line(self, same_feet=0, same_center=0, near=None):
        from src.task.MapleFarmTask import decision_log_line
        return decision_log_line(
            'window', 1280.0, 880.0, centres=[], in_zone=[], left=0,
            same_feet=same_feet, same_center=same_center, near=near,
            raw_present=False, mob_present=False, attack_in=[], attack_present=False,
            facing_before='LEFT', facing_now='LEFT', turn=None, seek_dir=None,
            key_sendable=True, observed=None, obs_s=0.0, obs_flip=0.0)

    def test_fields_present_with_nearest_mob(self):
        line = self._line(same_feet=1, same_center=4, near=(180.0, -24.0, -64.0))
        self.assertIn('同层脚=1 同层心=4 近怪dx=+180 dy脚=-24 dy心=-64', line)

    def test_fields_degrade_when_no_mob_on_screen(self):
        # 屏幕上一只怪都没有:三个 dy 写 '-',不许写 0(0 会被判据脚本当成真值)
        self.assertIn('同层脚=0 同层心=0 近怪dx=- dy脚=- dy心=-', self._line())

    def test_fields_sit_between_zone_and_raw_present(self):
        # 位置固定:analyze_seek.py 的正则按这个顺序写,挪位置立刻红
        line = self._line(same_feet=2, same_center=2, near=(0.0, 0.0, 0.0))
        self.assertLess(line.index('区内='), line.index('同层脚='))
        self.assertLess(line.index('同层心='), line.index('实测有怪='))

    def test_detect_and_act_feeds_real_mob_geometry(self):
        """接线断言:字段的值真的来自 find_mobs 的框,不是常量。

        几何(全部走 DEFAULT_CONFIG):角色名为空 → _resolve_anchor 直接回退
        画面中心 (1280,720);名字牌到身体偏移 90 → body=(1280,630)
        (anchor.body_center 是 y - offset,名字牌在脚下);
        接敌区 600x200 → 水平 [980,1580] 纵向 [530,730];寻怪同层容差 60。
        _detect_and_act 不读血条,直接调即可,不需要 patch bars。
        """
        task = make_task(**{'决策日志开关': True, '攻击模式': '检测'})
        # 怪 A:中心 y=600 在接敌区纵向内;脚底 640,与 anchor_y=720 差 80 > 60 → 旧口径判不同层
        mob_a = SimpleNamespace(x=1400, y=560, width=80, height=80)
        # 怪 B:中心 y=900,接敌区纵向外,两个口径都不同层
        mob_b = SimpleNamespace(x=1500, y=860, width=80, height=80)
        task.find_mobs = MagicMock(return_value=[mob_a, mob_b])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        line = next(c.args[0] for c in task.log_debug.call_args_list
                    if '决策 src=' in c.args[0])
        self.assertIn('同层脚=0 同层心=1', line)     # 正是 spec §2.3 那条「罩得到却判不同层」的带
        self.assertIn('近怪dx=+160', line)           # 怪 A 中心 1440,body_x 1280
        self.assertIn('dy脚=-80', line)              # 640 - 720
        self.assertIn('dy心=-30', line)              # 600 - 630


class TestDetectCadence(unittest.TestCase):
    """检测拍三态节流的接线(spec §3.1)。

    几何:DEFAULT_CONFIG['角色名'] 为空 → 锚点恒为画面中心,不依赖存档帧。
    """

    def _task(self, **cfg):
        """run() 全程走 mock:_detect_and_act 换成计数器,只验节流。
        走位/坐椅/喝药全关,免得它们各自的计时器干扰 send_key 断言。"""
        task = make_task(**{'攻击模式': '检测', '喝药开关': False,
                            '走位开关': False, '坐椅开关': False,
                            '攻击间隔(秒)': 0.7, '空闲刷新间隔(秒)': 0.3,
                            '寻怪刷新间隔(秒)': 0.1, **cfg})
        task._detect_and_act = MagicMock()
        return task

    def test_idle_detects_at_idle_interval_not_attack_interval(self):
        """空闲时按 空闲刷新间隔(0.3) 检测,不再等 攻击间隔(0.7)。

        这是本次修复的核心:起步寻怪只能在检测拍里发生,旧实现里
        空闲期的检测拍是 0.7s 一次(spec §3.1)。"""
        task = self._task()
        task._last_detect = 1000.0
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.2)
        self.assertEqual(task._detect_and_act.call_count, 0)
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.35)
        self.assertEqual(task._detect_and_act.call_count, 1)

    def test_attacking_keeps_attack_interval(self):
        """在打时仍按 攻击间隔,负载不回归。

        节拍门读的是 _detect_attacking(短宽限快照)而不是 _last_attack_present
        (攻击键用的 丢怪保持 1.0s 去抖):两者分家后,攻击区空过 寻怪起步宽限
        就立刻转空闲档,不再白等一个攻击拍。本用例 _detect_and_act 是 mock,
        真实快照算不出来,所以直接置位——断言的行为(0.35 不跑/0.75 跑)未变。
        """
        task = self._task()
        task._last_detect = 1000.0
        task._detect_attacking = True
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.35)
        self.assertEqual(task._detect_and_act.call_count, 0)
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.75)
        self.assertEqual(task._detect_and_act.call_count, 1)

    def test_seeking_uses_seek_refresh_interval(self):
        task = self._task()
        task._last_detect = 1000.0
        task._seek_dir = 'right'
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.15)
        self.assertEqual(task._detect_and_act.call_count, 1)

    def test_last_seek_refresh_state_is_gone(self):
        """_last_seek_refresh 随 elif 分支一起退休,不留死状态。"""
        task = self._task()
        self.assertFalse(hasattr(task, '_last_seek_refresh'))

    def test_idle_interval_has_a_default(self):
        self.assertEqual(DEFAULT_CONFIG['空闲刷新间隔(秒)'], 0.3)


class TestSeekNotBlockedByAttackGrace(unittest.TestCase):
    """寻怪起步与攻击去抖分家(spec §3.2)。

    几何(全部走 DEFAULT_CONFIG):角色名为空 → 锚点画面中心 (1280,720),
    名字牌到身体偏移 90 → body=(1280,630);接敌区 600x200 →
    水平 [980,1580] 纵向 [530,730]。怪放在中心 (2200, 632):
    水平出区(不该打)、纵向同层、脚底 672 与 anchor_y 720 差 48 ≤ 容差 60
    (本任务还没改同层口径,旧口径也判同层)→ 该追。
    """

    def _task(self, **cfg):
        return make_task(**{'攻击模式': '检测', '寻怪开关': True,
                            '丢怪保持(秒)': 1.0, '寻怪起步宽限(秒)': 0.3, **cfg})

    @staticmethod
    def _far_mob():
        return SimpleNamespace(x=2160, y=592, width=80, height=80)

    def test_seek_starts_once_short_grace_elapsed(self):
        """区里最后一只怪没了 0.3s 后就能起步,不用等满 1.0s 的丢怪保持。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0          # 区内最后一次真见到怪
        task._detect_and_act(_synthetic_frame(), 1000.35, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')

    def test_seek_still_blocked_inside_short_grace(self):
        """0.3s 之内不起步:一拍 YOLO 漏检不该让角色立刻迈腿。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0
        task._detect_and_act(_synthetic_frame(), 1000.2, task.config, KEYS)
        self.assertIsNone(task._seek_dir)

    def test_starting_seek_drops_the_stale_attack_signal(self):
        """起步即停手:不许出现「一边追一边挥」。

        _last_attack_present 还被 丢怪保持 撑着 True,寻怪一旦定向就作废它,
        否则 _do_attack 会继续朝空气轻点攻击键
        (MapleFarmTask.py 去抖注释里担心过的错乱状态)。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0
        task._last_attack_seen = 1000.0
        task._detect_and_act(_synthetic_frame(), 1000.35, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')
        self.assertFalse(task._last_attack_present)

    def test_sit_chair_and_walk_still_use_the_long_grace(self):
        """_last_mob_present 仍按 丢怪保持(1.0s) 算:
        坐椅/防挂机走位不该在怪刚消失 0.3s 就触发。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0
        task._detect_and_act(_synthetic_frame(), 1000.35, task.config, KEYS)
        self.assertTrue(task._last_mob_present)

    def test_short_grace_has_a_default_below_the_long_one(self):
        self.assertEqual(DEFAULT_CONFIG['寻怪起步宽限(秒)'], 0.3)
        self.assertLess(DEFAULT_CONFIG['寻怪起步宽限(秒)'],
                        DEFAULT_CONFIG['丢怪保持(秒)'])


class TestSeekPersistWiring(unittest.TestCase):
    """寻怪去抖的接线(spec §3.3)。几何同 TestSeekNotBlockedByAttackGrace。"""

    def _task(self, **cfg):
        return make_task(**{'攻击模式': '检测', '寻怪开关': True,
                            '丢怪保持(秒)': 1.0, '寻怪起步宽限(秒)': 0.3,
                            '寻怪保持(秒)': 0.5, **cfg})

    @staticmethod
    def _far_mob():
        return SimpleNamespace(x=2160, y=592, width=80, height=80)

    def test_keeps_walking_when_one_tick_misses_the_mob(self):
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')
        # 下一拍 YOLO 一只都没检出 → 仍按上一拍方向走
        task.find_mobs = MagicMock(return_value=[])
        task._detect_and_act(_synthetic_frame(), 1000.3, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')

    def test_gives_up_after_the_grace_expires(self):
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        task.find_mobs = MagicMock(return_value=[])
        task._detect_and_act(_synthetic_frame(), 1000.6, task.config, KEYS)
        self.assertIsNone(task._seek_dir)

    def test_grace_zero_restores_old_behaviour(self):
        task = self._task(**{'寻怪保持(秒)': 0.0})
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        task.find_mobs = MagicMock(return_value=[])
        task._detect_and_act(_synthetic_frame(), 1000.1, task.config, KEYS)
        self.assertIsNone(task._seek_dir)

    def test_default_is_below_the_attack_grace(self):
        # 追错方向的代价高于挥空刀,不该保持得比丢怪保持还久
        self.assertEqual(DEFAULT_CONFIG['寻怪保持(秒)'], 0.5)
        self.assertLess(DEFAULT_CONFIG['寻怪保持(秒)'], DEFAULT_CONFIG['丢怪保持(秒)'])


if __name__ == '__main__':
    unittest.main()


class TestDecisionLineYoloFields(unittest.TestCase):
    """yolo候选/关联距 字段(spec §3.6):没有 yolo 命中时写 '-',绝不写 0
    (0 会被判据脚本当真值,同 near 字段的既有纪律)。"""

    def _line(self, **kw):
        from src.task.MapleFarmTask import decision_log_line
        return decision_log_line(
            'yolo', 1230.0, 866.0, [(1.0, 2.0)], [], 0, 0, 0, None,
            False, False, [], False, 'LEFT', 'LEFT', None, None, True,
            None, 0.0, 0.0, **kw)

    def test_fields_dash_when_absent(self):
        self.assertIn('yolo候选=- 关联距=-', self._line())

    def test_fields_rendered_when_present(self):
        self.assertIn('yolo候选=2 关联距=35', self._line(yolo_cands=2, yolo_dist=35.4))

    def test_fields_appended_at_line_end(self):
        # 追加在行尾:analyze_anchor/analyze_seek 的前缀正则不受影响
        self.assertTrue(self._line().endswith('关联距=- yolo全屏=-'))

    def test_full_count_rendered_when_present(self):
        self.assertIn('yolo候选=0 关联距=- yolo全屏=1',
                      self._line(yolo_cands=0, yolo_full=1))

    def test_full_count_dash_when_absent(self):
        self.assertIn('yolo全屏=-', self._line(yolo_cands=2, yolo_dist=35.4))


class TestFindMobsBoxesParam(unittest.TestCase):
    """find_mobs(boxes=) 纯过滤路径:一拍一次推理(spec §3.2)的接缝。
    不碰 og/模型,boxes 路径必须完全离线可测。"""

    def _fake(self, name):
        return SimpleNamespace(x=0, y=0, width=10, height=10, name=name)

    def test_boxes_param_filters_mobs_without_inference(self):
        from src.task.BaseMapleTask import BaseMapleTask
        m, p = self._fake('mob'), self._fake('player')
        out = BaseMapleTask.find_mobs(SimpleNamespace(), boxes=[m, p, m])
        self.assertEqual(out, [m, m])

    def test_empty_boxes_gives_empty_not_inference(self):
        from src.task.BaseMapleTask import BaseMapleTask
        # boxes=[] 也是「已推理过」:绝不能落回自推理分支(那会二次推理)
        self.assertEqual(BaseMapleTask.find_mobs(SimpleNamespace(), boxes=[]), [])


class TestYoloAnchorFusion(unittest.TestCase):
    """YOLO 关联级(spec §3.3/§3.4):名字牌两级都失效时接管位置;
    身份规则、冷启动、开关、伪锚点换算全在这里锁死。
    OCR 两条通道一律 patch 成 None——测的是阶梯裁决,不是 OCR。"""

    def _player(self, cx, cy, w=60, h=120):
        return SimpleNamespace(x=cx - w / 2, y=cy - h / 2,
                               width=w, height=h, name='player')

    def _task(self, players, identity_age=1.0, anchored=True, **cfg):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '决策日志开关': True, **cfg})
        task.find_all = MagicMock(return_value=list(players))
        task._boxes_enabled = MagicMock(return_value=False)
        task._key_sendable = MagicMock(return_value=True)
        if anchored:
            task._anchor = (1200.0, 900.0)
            task._anchor_time = 99.8      # 新鲜(<0.5s),不外推:搜索中心就是 1200
            task._last_anchor_hit = 99.8
        task._last_anchor_scan = 99.9     # 慢扫节流窗内 → 慢扫不参战
        task._last_identity_hit = 100.0 - identity_age
        return task

    def _beat(self, task, now=100.0):
        frame = _synthetic_frame()
        with patch.object(anchor, 'find_in_window', return_value=None), \
                patch.object(anchor, 'find_in_region', return_value=None), \
                patch('time.time', return_value=now):
            task._detect_and_act(frame, now, task.config,
                                 task.get_global_config())
        return [c.args[0] for c in task.log_debug.call_args_list
                if '决策 ' in c.args[0]]

    def test_occluded_nametag_yolo_takes_over(self):
        # 名字牌两级全失,门内一个 player 框 → src=yolo,伪锚点=框中心+偏移
        lines = self._beat(self._task([self._player(1180, 880)]))
        self.assertTrue(any('src=yolo' in l for l in lines), lines)
        # body_x = 框中心 x(伪锚点往返,spec §3.4);关联距 = |1180-1200| = 20
        self.assertTrue(any('body_x=1180' in l for l in lines), lines)
        self.assertTrue(any('yolo候选=1 关联距=20' in l for l in lines), lines)

    def test_yolo_hit_recenters_next_window(self):
        # 伪锚点喂 _update_anchor:遮挡一散名字牌在正确位置重新咬住(spec §3.4)
        task = self._task([self._player(1180, 880)])
        self._beat(task)
        self.assertEqual(task._anchor,
                         (1180.0, 880.0 + farm_logic.PLAYER_BOX_TO_NAMETAG))
        self.assertEqual(task._last_anchor_hit, 100.0)

    def test_yolo_pseudo_anchor_lands_on_real_nametag_height(self):
        # 伪锚点存进 _anchor 的必须是**名字牌**坐标(下一拍 OCR 小窗、关联门都按它
        # 定心)。框中心 → 名字牌是实测 64px,不是身体偏移 88px:用 88 会让 yolo 拍
        # 的 anchor_y 比名字牌拍系统性低 24px(实测 403 组配对,中位 24/p10 21/p90 27),
        # 攻击区随来源翻拍上下抖 24px,关联门也整体偏 64px
        lines = self._beat(self._task([self._player(1180, 880)]))
        self.assertTrue(any(f'anchor_y={880 + farm_logic.PLAYER_BOX_TO_NAMETAG}'
                            in l for l in lines), lines)

    def test_yolo_does_not_refresh_identity(self):
        # yolo 不验名,不许刷新身份时间戳(spec §3.4)
        task = self._task([self._player(1180, 880)], identity_age=5.0)
        self._beat(task)
        self.assertEqual(task._last_identity_hit, 95.0)

    def test_two_players_stale_identity_falls_to_cached(self):
        lines = self._beat(self._task(
            [self._player(1180, 880), self._player(1300, 880)],
            identity_age=30.0))
        self.assertTrue(any('src=cached' in l for l in lines), lines)
        self.assertFalse(any('src=yolo' in l for l in lines))

    def test_two_players_fresh_identity_picks_nearest(self):
        lines = self._beat(self._task(
            [self._player(1300, 880), self._player(1180, 880),
             self._player(2000, 880)],   # 第三个在门外(|2000-1200|>240):不参与,也不计入候选数
            identity_age=1.0))
        self.assertTrue(any('src=yolo' in l for l in lines), lines)
        # 候选数 = 门内 2,不是全屏 3(gate_player_boxes 口径)
        self.assertTrue(any('yolo候选=2' in l for l in lines), lines)
        self.assertTrue(any('body_x=1180' in l for l in lines), lines)

    def test_cold_start_never_uses_yolo(self):
        # 从未有过名字牌命中:没有先验位置就没有门,首个身份必须由慢扫建立
        task = self._task([self._player(1180, 880)], anchored=False)
        task._last_anchor_scan = 0.0   # 让慢扫真的跑(mock 返回 None → miss)
        lines = self._beat(task)
        self.assertTrue(any('src=fallback' in l for l in lines), lines)
        self.assertFalse(any('src=yolo' in l for l in lines))

    def test_switch_off_restores_old_ladder(self):
        lines = self._beat(self._task([self._player(1180, 880)],
                                      **{'YOLO角色定位开关': False}))
        self.assertTrue(any('src=cached' in l for l in lines), lines)

    def test_gate_narrows_with_fresh_observation(self):
        # 上一拍刚命中(0.2s 前),路人在 200px 外:固定 ±240 会认它,位移门不认。
        # _last_anchor_hit 才是「上次真观测到位置」的时刻(yolo 命中也刷新它)
        task = self._task([self._player(1400, 880)])
        task._last_anchor_hit = 99.8
        lines = self._beat(task)
        self.assertFalse(any('src=yolo' in l for l in lines), lines)
        self.assertTrue(any('src=cached' in l for l in lines), lines)

    def test_gate_widens_after_long_loss(self):
        # 久未观测(2s):门放大到固定上限,远处的自己还认得回来
        task = self._task([self._player(1400, 880)])
        task._last_anchor_hit = 98.0
        lines = self._beat(task)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)

    def test_mobs_come_from_find_mobs_filter_players_from_find_all(self):
        # 分流接线:mob 走 find_mobs(boxes=find_all结果),player 走 find_all(spec §3.2)
        mob = SimpleNamespace(x=1400, y=850, width=60, height=50, name='mob')
        task = self._task([self._player(1180, 880), mob])
        task.find_mobs = MagicMock(return_value=[mob])
        lines = self._beat(task)
        task.find_mobs.assert_called_once()
        _, kwargs = task.find_mobs.call_args
        # 同一对象:分流必须吃 find_all 的结果,不许自己再推理
        self.assertIs(kwargs.get('boxes'), task.find_all.return_value)
        self.assertTrue(any('怪=1' in l for l in lines), lines)

    def test_rejected_beat_records_full_screen_count(self):
        # 多候选 + 身份过期 → 拒裁退 cached,但观测必须留痕:
        # yolo候选=2(门内) yolo全屏=2,不再是 '-/-' 的盲区(spec §3.3)
        lines = self._beat(self._task(
            [self._player(1180, 880), self._player(1300, 880)],
            identity_age=30.0))
        self.assertTrue(any('src=cached' in l for l in lines), lines)
        self.assertTrue(any('yolo候选=2 关联距=- yolo全屏=2' in l
                            for l in lines), lines)

    def test_empty_screen_records_zero_not_dash(self):
        # YOLO 跑了但全屏 0 个 player 框 → 候选=0 全屏=0(可达状态:
        # 「推理了没框」与「YOLO 级未到达」必须分得开,这正是排查被挡两次的盲区)
        lines = self._beat(self._task([]))
        self.assertTrue(any('src=cached' in l for l in lines), lines)
        self.assertTrue(any('yolo候选=0 关联距=- yolo全屏=0' in l
                            for l in lines), lines)

    def test_yolo_exception_marks_level_not_reached(self):
        # 推理异常 ≠ 全屏无框:异常拍 players=None,YOLO 级按未到达处理记 '-',
        # 与「跑了没框」(全屏=0) 在日志里可区分(评审 Minor 1 修复)
        task = self._task([])
        task.find_all = MagicMock(side_effect=RuntimeError('boom'))
        lines = self._beat(task)
        self.assertTrue(any('src=cached' in l for l in lines), lines)
        self.assertTrue(any('yolo候选=- 关联距=- yolo全屏=-' in l
                            for l in lines), lines)

    def test_window_beat_yolo_fields_all_dash(self):
        # YOLO 级未到达(快窗命中)→ 三个字段全 '-'
        task = self._task([self._player(1180, 880)])
        hit = AnchorHit(1200.0, 900.0, 130, 'Yufeng咕咕')
        frame = _synthetic_frame()
        with patch.object(anchor, 'find_in_window', return_value=hit), \
                patch.object(anchor, 'find_in_region', return_value=None), \
                patch('time.time', return_value=100.0):
            task._detect_and_act(frame, 100.0, task.config, task.get_global_config())
        lines = [c.args[0] for c in task.log_debug.call_args_list
                 if '决策 ' in c.args[0]]
        self.assertTrue(any('src=window' in l for l in lines), lines)
        self.assertTrue(all('yolo候选=- 关联距=- yolo全屏=-' in l
                            for l in lines), lines)

    def test_lost_unique_box_takes_over_beyond_gate(self):
        # 丢锚 3s + 全屏唯一框在门外(横向 800px)→ 末级接管,一拍 src=yolo
        # (08-09/08-10 两次完全丢失的主修复:不再等名字牌可读的慢扫)
        task = self._task([self._player(2000, 880)], identity_age=30.0)
        task._anchor_time = 97.0        # 丢锚 3s(now=100)
        lines = self._beat(task)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)
        self.assertTrue(any('body_x=2000' in l for l in lines), lines)
        # 接管不刷身份时间戳:认错路人靠复验慢扫兜底,整条风险章都押在这行上
        self.assertEqual(task._last_identity_hit, 70.0)
        # 本剧本接管瞬移不会污染实测速度:dt=3s > ANCHOR_VX_MAX_AGE(2s)先挡,
        # dy=|944-900|=44 ≥ platform_dy(30)再挡(接管本身就常伴换层)
        self.assertEqual(task._anchor_vx, 0.0)

    def test_lost_unique_box_takeover_vx_learning_is_known_and_capped(self):
        # 通性锁定(spec §5):age 落在 1.0~2.0s 且同层(dy<30,正是横向逃逸
        # 主场景)时,两道门都拦不住,接管瞬移会被低通学进去
        # (dx=600/dt=1.5=400px/s ≤ 600 跳变门 → 0.7*400=280)。
        # 不加门:外推 ±500 封顶 + 同向防护兜底。这条锁「知道它在学、学多少」
        task = self._task([self._player(1800, 836)], identity_age=30.0)
        task._anchor_time = 98.5        # 丢锚 1.5s(now=100);pseudo y=836+64=900=锚点 y,dy=0
        lines = self._beat(task)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)
        self.assertAlmostEqual(task._anchor_vx, 0.7 * 600 / 1.5, places=5)

    def test_lost_unique_box_respects_switch_off(self):
        task = self._task([self._player(2000, 880)], identity_age=30.0,
                          **{'丢锚唯一框接管开关': False})
        task._anchor_time = 97.0
        lines = self._beat(task)
        self.assertFalse(any('src=yolo' in l for l in lines), lines)

    def test_lost_unique_box_rejects_multiple_players(self):
        # 丢锚再久,全屏 ≥2 框也不接管(多人图保守,spec §3.4)
        task = self._task([self._player(2000, 880), self._player(600, 880)],
                          identity_age=30.0)
        task._anchor_time = 97.0
        lines = self._beat(task)
        self.assertFalse(any('src=yolo' in l for l in lines), lines)


class TestTemplateDriftGuard(unittest.TestCase):
    """模板棘轮漂移(spec §3.8):模板通道拿自己上一拍的输出当下一拍搜索中心,
    一次误匹配就一路上飘 62px/拍 直到飞出屏幕,且因为它会刷身份时间戳,
    §3.7 的复验永远不触发 —— 实测全天 11.6% 的拍锚点飘在平台上方 >80px,
    其中 90% 由 template 持有。"""

    def _task(self, **cfg):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '决策日志开关': True, **cfg})
        task.find_all = MagicMock(return_value=[])
        task._boxes_enabled = MagicMock(return_value=False)
        task._key_sendable = MagicMock(return_value=True)
        task._nametag_template = np.zeros((36, 153), np.uint8)
        task._anchor = (1200.0, 887.0)
        task._anchor_time = 99.8
        task._last_anchor_hit = 99.8
        task._last_anchor_scan = 99.9      # 慢扫节流窗内:不参战
        task._last_identity_hit = 99.9
        return task

    def _beat(self, task, tpl_hit, now=100.0):
        with patch.object(anchor, 'split_match', return_value=tpl_hit), \
                patch.object(anchor, 'find_in_window', return_value=None), \
                patch.object(anchor, 'find_in_region', return_value=None), \
                patch('time.time', return_value=now):
            task._detect_and_act(_synthetic_frame(), now, task.config,
                                 task.get_global_config())
        return [c.args[0] for c in task.log_debug.call_args_list
                if '决策 ' in c.args[0]]

    def test_ratchet_step_is_refused_and_anchor_held(self):
        # 恰好 62px 的棘轮步长:不许被采纳,锚点必须留在原处(落到 cached)
        task = self._task()
        lines = self._beat(task, AnchorHit(1200.0, 887.0 - 62, 153, ''))
        self.assertFalse(any('src=template' in l for l in lines), lines)
        self.assertEqual(task._anchor, (1200.0, 887.0))

    def test_normal_template_hit_still_accepted(self):
        # 正常的小幅移动照常走模板快通道(它是怪堆遮挡的主解,不能连带废掉)
        task = self._task()
        lines = self._beat(task, AnchorHit(1240.0, 890.0, 153, ''))
        self.assertTrue(any('src=template' in l for l in lines), lines)
        self.assertEqual(task._anchor, (1240.0, 890.0))

    def test_template_hit_does_not_refresh_identity(self):
        # 模板是**像素**匹配,命中的 text 是空串,根本没验名 —— 它刷新身份时间戳
        # 就等于「误匹配把复验永久锁死」。只有真读到名字的 window/region 才算验名
        task = self._task()
        task._last_identity_hit = 90.0
        self._beat(task, AnchorHit(1240.0, 890.0, 153, ''))
        self.assertEqual(task._last_identity_hit, 90.0)

    def test_window_hit_still_refreshes_identity(self):
        task = self._task()
        task._last_identity_hit = 90.0
        with patch.object(anchor, 'split_match', return_value=None), \
                patch.object(anchor, 'find_in_window',
                             return_value=AnchorHit(1240.0, 890.0, 153, 'Yufeng咕咕')), \
                patch('time.time', return_value=100.0):
            task._detect_and_act(_synthetic_frame(), 100.0, task.config,
                                 task.get_global_config())
        self.assertEqual(task._last_identity_hit, 100.0)


class TestIdentityRecheckScan(unittest.TestCase):
    """身份复验慢扫(spec §3.7):身份过期时慢扫必须排在 YOLO 之前。

    YOLO 级一命中就 return,慢扫那段根本走不到——实测慢扫占比被饿到 0.6%
    (8-08 基线 2.2%),而慢扫是唯一验名、也是唯一能在任意位置找回角色的通道。
    没有它,YOLO 认错人之后 `_update_anchor` 还会刷新 `_anchor_time`、清掉
    `_force_rescan`,丢锚立即重扫也不会触发,锚点就永久钉在路人身上。"""

    def _player(self, cx, cy, w=60, h=120):
        return SimpleNamespace(x=cx - w / 2, y=cy - h / 2,
                               width=w, height=h, name='player')

    def _task(self, identity_age, **cfg):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '决策日志开关': True, **cfg})
        task.find_all = MagicMock(return_value=[self._player(1180, 880)])
        task._boxes_enabled = MagicMock(return_value=False)
        task._key_sendable = MagicMock(return_value=True)
        task._anchor = (1200.0, 900.0)
        task._anchor_time = 99.8
        task._last_anchor_hit = 99.8
        task._last_anchor_scan = 99.9      # 常规节流窗内:慢扫本来轮不到
        task._last_identity_hit = 100.0 - identity_age
        task._last_identity_scan = 0.0
        return task

    def _beat(self, task, region_hit=None, now=100.0):
        frame = _synthetic_frame()
        with patch.object(anchor, 'find_in_window', return_value=None), \
                patch.object(anchor, 'find_in_region',
                             return_value=region_hit) as scan, \
                patch('time.time', return_value=now):
            task._detect_and_act(frame, now, task.config,
                                 task.get_global_config())
        return [c.args[0] for c in task.log_debug.call_args_list
                if '决策 ' in c.args[0]], scan

    def test_stale_identity_runs_scan_before_yolo(self):
        # 身份过期 + 慢扫命中 → src=region,锚点被拉回真实位置,身份时间戳刷新
        hit = AnchorHit(700.0, 890.0, 80, 'Yufeng咕咕')
        lines, scan = self._beat(self._task(identity_age=30.0), region_hit=hit)
        self.assertTrue(scan.called)
        self.assertTrue(any('src=region' in l for l in lines), lines)

    def test_stale_identity_scan_miss_still_falls_to_yolo(self):
        # 慢扫没找到 → 照常让 YOLO 接管:复验只加验名机会,绝不新增丢锚
        lines, scan = self._beat(self._task(identity_age=30.0), region_hit=None)
        self.assertTrue(scan.called)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)

    def test_fresh_identity_does_not_scan(self):
        # 身份还新鲜:不花这 118-235ms,维持原阶梯
        lines, scan = self._beat(self._task(identity_age=1.0))
        self.assertFalse(scan.called)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)

    def test_recheck_is_throttled(self):
        # 复验自身限频:刚扫过就不再扫(慢扫最坏 235ms,不许每拍都跑)
        task = self._task(identity_age=30.0)
        task._last_identity_scan = 99.0     # 1s 前扫过 < 身份复验间隔(3s)
        lines, scan = self._beat(task)
        self.assertFalse(scan.called)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)

    def test_switch_off_restores_old_ladder(self):
        lines, scan = self._beat(self._task(identity_age=30.0,
                                            **{'身份复验开关': False}))
        self.assertFalse(scan.called)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)

    def test_shares_one_scan_per_beat_with_forced_rescan(self):
        # 受击 + 身份过期同拍撞上:慢扫最坏 235ms,只许跑一次。复验那次就算数,
        # 悬着的强制重扫按已消费处理(否则同拍扫两次,主循环直接被打满)
        task = self._task(identity_age=30.0)
        task._force_rescan = True
        _, scan = self._beat(task)
        scan.assert_called_once()
        self.assertFalse(task._force_rescan)
        self.assertEqual(task._last_forced_rescan, 100.0)

class TestForcedRescanWiring(unittest.TestCase):
    """事件触发即时慢扫(spec §3.5):三级全失 +(受击 或 锚点超龄)→ 绕过 2s 节流。"""

    def _task(self, **cfg):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', **cfg})
        task.find_all = MagicMock(return_value=[])
        task._boxes_enabled = MagicMock(return_value=False)
        task._key_sendable = MagicMock(return_value=True)
        task._anchor = (1200.0, 900.0)
        task._anchor_time = 99.8
        task._last_anchor_hit = 99.8
        task._last_anchor_scan = 99.4   # 常规 2s 节流窗内:0.6s 前刚扫过
        task._last_identity_hit = 99.9  # 身份新鲜:本类只测强制重扫,不让身份复验
                                        # (§3.7,同样会绕过常规节流)插进来抢这次慢扫
        return task

    def _beat(self, task, now=100.0):
        with patch.object(anchor, 'find_in_window', return_value=None), \
                patch.object(anchor, 'find_in_region', return_value=None) as region, \
                patch('time.time', return_value=now):
            task._detect_and_act(_synthetic_frame(), now, task.config,
                                 task.get_global_config())
        return region

    def test_knockback_flag_forces_immediate_rescan(self):
        task = self._task()
        task._force_rescan = True
        region = self._beat(task)
        region.assert_called_once()          # 节流窗内照样扫了
        self.assertFalse(task._force_rescan)  # 消费即清
        self.assertEqual(task._last_forced_rescan, 100.0)

    def test_forced_rescan_rate_limited(self):
        task = self._task()
        task._force_rescan = True
        task._last_forced_rescan = 99.7      # 0.3s 前刚强制扫过
        self._beat(task).assert_not_called()

    def test_stale_anchor_age_forces_rescan_without_knockback(self):
        task = self._task()
        task._anchor_time = 97.0             # 超龄 3s > 锚点刷新间隔 2s
        task._last_anchor_hit = 97.0
        self._beat(task).assert_called_once()

    def test_cold_start_not_forced(self):
        # 从未有锚点:保持旧 2s 节奏,不许 0.5s 高频扫(spec §3.5 冷启动例外)
        task = self._task()
        task._anchor = None
        task._anchor_time = None
        self._beat(task).assert_not_called()

    def test_switch_off_restores_throttle(self):
        task = self._task(**{'丢锚立即重扫开关': False})
        task._force_rescan = True
        self._beat(task).assert_not_called()

    def test_any_hit_clears_pending_force(self):
        # 位置重新观测到(此处 yolo 命中)→ 跳变已消化,悬着的强制扫描作废
        task = self._task()
        task._force_rescan = True
        task.find_all = MagicMock(return_value=[SimpleNamespace(
            x=1150, y=820, width=60, height=120, name='player')])
        self._beat(task)
        self.assertFalse(task._force_rescan)

    def test_knockback_sets_flag_via_run(self):
        # run() 级接线:HP 掉 2%+(受击)→ 置 _force_rescan。
        # 角色名留空:锚点通道全程短路(_scan 空目标直接 None),
        # 不 patch OCR 也绝不会真的加载 OCR 引擎(本用例只测受击接线)
        task = make_task(**{'攻击模式': '检测', '角色名': ''})
        task.find_all = MagicMock(return_value=[])
        task._boxes_enabled = MagicMock(return_value=False)
        run_with_frame(task, hp=1.0, now=100.0)
        run_with_frame(task, hp=0.9, now=100.3)
        self.assertTrue(task._force_rescan)


class TestAoeConfig(unittest.TestCase):
    """群攻的两个配置键:默认值 + 「留空=关闭」约定 + 说明文案。"""

    def test_task_defaults(self):
        self.assertEqual(DEFAULT_CONFIG['群攻怪数阈值'], 3)

    def test_no_separate_aoe_interval(self):
        """群攻不再有独立节拍:与单体共用 攻击间隔(秒),按怪数二选一。

        原设计给了 群攻间隔(秒)=2.0,理由是「群攻耗蓝是单体数倍」。该理由被
        用户否掉(耗蓝不是问题);剩下的「群攻施法约 1 秒、独立节拍保护施法窗」
        经查是站不住的——单体自己就在 攻击间隔=0.7 下自断施法(实测施法时长
        0.7-1.0s,见 2026-08-08-facing-observer-design.md:66),群攻并不特殊。
        独立节拍还引入了相位差:两个节拍互质地各走各的,群攻会落在上次单体后
        0.6s(< 攻击间隔 0.7)。共用一个节拍从构造上消掉这一整类问题。"""
        self.assertNotIn('群攻间隔(秒)', DEFAULT_CONFIG)

    def test_global_key_defaults_to_empty(self):
        """群攻键默认留空 = 功能关闭,与 椅子键(可留空) 同一约定。"""
        from config import key_config_option
        self.assertEqual(key_config_option.default_config['群攻键(可留空)'], '')

    def test_global_key_has_description(self):
        """GUI 上没有说明的按键槽等于没有:用户不知道该往里填什么。"""
        from config import key_config_option
        self.assertIn('群攻键(可留空)', key_config_option.config_description)


AOE_KEYS = {**KEYS, '群攻键(可留空)': 'f'}


def _aoe_mob(cx, cy=650):
    """按中心点造怪:width=60 / height=50 → bbox 左上角 (cx-30, cy-25)。
    cy=650 落在接敌区纵向范围 y∈[530,730] 内(锚点走画面中心回退,见计划开头
    的几何前提:角色名为空 → _resolve_anchor 直接返回画面中心)。"""
    return MagicMock(x=cx - 30, y=cy - 25, width=60, height=50)


def _aoe_task(**cfg_overrides):
    """检测模式 + 绑好群攻键 + 关走位(走位有独立 120s 节奏,会给按键序列加噪声)。"""
    task = make_task(**{'攻击模式': '检测', '走位开关': False, **cfg_overrides})
    task.get_global_config = MagicMock(return_value=dict(AOE_KEYS))
    return task


def _run_with_mobs(task, mobs, now=100.0):
    """跑一拍。锚点走回退路径(角色名为空)→ 身体 (1280,630)、
    接敌区 x∈[980,1580] y∈[530,730]。不 patch find_in_region:
    空 角色名 下它压根不会被调用,patch 了只会给读代码的人错误暗示。"""
    task.find_mobs = MagicMock(return_value=mobs)
    run_with_frame(task, now=now)


def _sent(task):
    """本次 run 里真正送出去的按键名(丢掉 down_time 等 kwargs)。"""
    return [c.args[0] for c in task.send_key.call_args_list if c.args]


def _ready_task(**cfg_overrides):
    """把 _aoe_ready 的输入直接摆好:计数快照(值 + 测得时刻)、单体节拍、受击时刻。

    判据现在有四项状态输入,用「真跑一拍」去摆它们会让「这条测的是哪一项」不可读,
    而且真跑的那一拍自己就会发群攻、把 _last_attack 推到 now,断言时点被迫漂移。
    快照有没有被正确写进去,由 test_zone_count_snapshot 单独盯着。"""
    task = _aoe_task(**cfg_overrides)
    task._last_zone_count = 3
    task._last_zone_count_time = 100.0
    task._last_attack = 0.0        # 0.0 哨兵=从未攻击,节拍天然放行
    return task


class TestAoeReady(unittest.TestCase):
    """群攻判据 _aoe_ready:转向门与攻击门的唯一事实源(spec §3.4)。"""

    def test_zone_count_snapshot(self):
        """检测拍把接敌区内怪数记进 _last_zone_count(原始计数,不去抖)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        self.assertEqual(task._last_zone_count, 3)

    def test_zone_count_excludes_mobs_outside_zone(self):
        """区外的怪不计数:接敌区 x∈[980,1580],2000 与 500 都在区外。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(2000), _aoe_mob(500)])
        self.assertEqual(task._last_zone_count, 1)

    def test_ready_when_count_reaches_threshold(self):
        task = _ready_task()
        self.assertTrue(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))

    def test_not_ready_below_threshold(self):
        task = _ready_task()
        task._last_zone_count = 2
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))

    def test_not_ready_when_key_unbound(self):
        """群攻键留空 = 功能关闭,计数够也不 ready。"""
        task = _ready_task()
        self.assertFalse(task._aoe_ready(task.config, dict(KEYS), 100.0))

    def test_not_ready_on_stale_count(self):
        """计数必须是**本拍**测的。_do_attack 每个 10Hz 拍都跑,而计数只在检测拍
        写;没有这一道门,怪清光后的非检测拍会拿着上一个检测拍的旧计数放空群攻
        (实测:t=100.0 发群攻,t=101.5 检测拍计数=3,t=101.6 怪清光,
        t=102.0 非检测拍读到 0.5s 前的 3 又发一次)。这正是 farm_logic.crowd_present
        的 docstring 里说「不加保持窗」要避免的那件事,逐拍求值把它从后门放了回来。"""
        task = _ready_task()
        self.assertTrue(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.1))

    def test_not_ready_within_attack_interval(self):
        """与单体共用 攻击间隔:节拍未到不放群攻(不再有独立的 群攻间隔)。"""
        task = _ready_task()
        task._last_attack = 99.0            # 距 100.0 只过了 1.0 < 攻击间隔 1.5
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))
        task._last_attack = 98.0            # 2.0 >= 1.5
        self.assertTrue(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))

    def test_not_ready_in_fixed_rate_mode(self):
        """定频模式没有找怪信息,群攻整段不适用。"""
        task = _ready_task()
        task.config['攻击模式'] = '定频'
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))

    def test_not_ready_while_stunned(self):
        """硬直抑制窗内不发任何技能键,群攻同样受它管。"""
        task = _ready_task(**{'硬直抑制窗(秒)': 0.8})
        task._last_hit = 99.9
        self.assertFalse(task._aoe_ready(task.config, dict(AOE_KEYS), 100.0))


class TestAoeAttack(unittest.TestCase):
    """群攻按键路径:优先、二选一、节拍、日志(spec §3.5/§3.7/§4)。"""

    def test_fires_aoe_and_skips_single_attack(self):
        """区内 3 只 → 按群攻键,且本拍不按单体攻击键(二选一)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('f', sent)
        self.assertNotIn('shift', sent)

    def test_single_attack_below_threshold(self):
        """区内 2 只 → 原样走单体,不按群攻键。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('shift', sent)
        self.assertNotIn('f', sent)

    def test_unbound_key_behaves_as_before(self):
        """群攻键留空 → 与改动前逐键一致:照常单体输出,不出现任何新键。"""
        task = make_task(**{'攻击模式': '检测', '走位开关': False})  # KEYS 无群攻键
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('shift', sent)
        self.assertNotIn('f', sent)
        self.assertTrue(set(sent) <= set(KEYS.values()) - {''},
                        f'出现了 KEYS 之外的按键: {sent}')

    def test_aoe_advances_shared_cadence(self):
        """群攻走的就是单体那一条节拍:发出时推进 _last_attack,下一拍不再出键。

        鉴别力在「实现漏写 self._last_attack = now」那一档:漏写时 _last_attack
        停在 0.0 哨兵,100.3 那拍 100.3 - 0.0 >= 攻击间隔(1.5) 会再出一次键。"""
        task = _aoe_task()
        mobs = [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)]
        _run_with_mobs(task, mobs, now=100.0)
        self.assertIn('f', _sent(task))             # 这一拍真发了群攻
        self.assertEqual(task._last_attack, 100.0)  # 节拍被推进
        task.send_key.reset_mock()
        _run_with_mobs(task, mobs, now=100.3)   # 未满 攻击间隔 1.5
        self.assertEqual(_sent(task), [])

    def test_aoe_never_lands_inside_single_attack_cadence(self):
        """共用节拍的核心收益:群攻与单体永远落在同一张节拍格上,间距恒 = 攻击间隔。

        独立 群攻间隔(2.0)时两个节拍互质地各走各的,群攻会落在上次单体后 0.6s
        (< 攻击间隔 0.7),即落在用户自己声明的单体施法时长之内。攻击间隔取 0.7
        是实机常用值,也正是原实现暴露该相位差的那一档。"""
        task = _aoe_task(**{'攻击间隔(秒)': 0.7})
        task._facing = 'RIGHT'
        mobs = [_aoe_mob(1330), _aoe_mob(1430), _aoe_mob(1530)]   # 面朝侧,不触发转向
        fired = []
        for i in range(60):                       # 6 秒,10Hz 逐拍
            now = round(100.0 + i * 0.1, 1)
            task.send_key.reset_mock()
            _run_with_mobs(task, mobs, now=now)
            fired += [(now, k) for k in _sent(task) if k in ('f', 'shift')]
        gaps = [round(b - a, 1) for (a, _), (b, _) in zip(fired, fired[1:])]
        self.assertTrue(fired, '整整 6 秒一个键都没发,用例失去鉴别力')
        self.assertTrue(all(g >= 0.7 for g in gaps),
                        f'有出键落在攻击间隔之内: {fired}')

    def test_aoe_replaces_single_while_crowded(self):
        """区内一直够阈值 → 每个节拍都是群攻,单体整段不出场(二选一,群攻优先)。"""
        task = _aoe_task(**{'攻击间隔(秒)': 0.7})
        task._facing = 'RIGHT'
        mobs = [_aoe_mob(1330), _aoe_mob(1430), _aoe_mob(1530)]
        sent = []
        for i in range(30):
            task.send_key.reset_mock()
            _run_with_mobs(task, mobs, now=round(100.0 + i * 0.1, 1))
            sent += _sent(task)
        self.assertIn('f', sent)
        self.assertNotIn('shift', sent)

    def test_no_aoe_on_stale_zone_count(self):
        """怪清光后的非检测拍不许拿旧计数放空群攻(见 test_not_ready_on_stale_count)。

        时间线全部踩在实现的真实节流上:怪放在面朝侧不触发转向 —— 转向会把
        _last_detect 清成 0.0 哨兵,反而让 102.0 变回检测拍、把陈旧计数刷掉,
        用例就测不到东西了。"""
        task = _aoe_task()                       # 攻击间隔 1.5 → 检测拍 100.0 / 101.5
        task._facing = 'RIGHT'
        mobs = [_aoe_mob(1330), _aoe_mob(1430), _aoe_mob(1530)]
        _run_with_mobs(task, mobs, now=100.0)    # 检测拍:放群攻
        _run_with_mobs(task, mobs, now=101.5)    # 检测拍:计数刷成 3,节拍未到不出键
        task.find_mobs = MagicMock(return_value=[])   # 怪在 101.6 被清光
        task.send_key.reset_mock()
        _run_with_mobs(task, [], now=102.0)      # 非检测拍(102.0-101.5=0.5 < 1.5)
        self.assertEqual(task._last_zone_count, 3, '前提:这一拍确实没跑检测')
        self.assertNotIn('f', _sent(task))

    def test_no_aoe_in_fixed_rate_mode(self):
        """定频模式:照常按单体攻击键,不按群攻键。"""
        task = _aoe_task(**{'攻击模式': '定频'})
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        sent = _sent(task)
        self.assertIn('shift', sent)
        self.assertNotIn('f', sent)

    def test_no_aoe_while_stunned(self):
        """硬直抑制窗内:群攻键和单体攻击键都不按。"""
        task = _aoe_task(**{'硬直抑制窗(秒)': 0.8})
        task._last_hit = 99.9
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)],
                       now=100.0)
        sent = _sent(task)
        self.assertNotIn('f', sent)
        self.assertNotIn('shift', sent)

    def test_logs_aoe_line(self):
        """决策日志开着时,每次真按下群攻键写一行 群攻 区内=N 阈值=M(N >= M)。"""
        task = _aoe_task(**{'决策日志开关': True})
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        lines = [c.args[0] for c in task.log_debug.call_args_list if c.args]
        aoe_lines = [ln for ln in lines if ln.startswith('群攻 ')]
        self.assertEqual(len(aoe_lines), 1, f'期望一行群攻日志,实得 {aoe_lines}')
        self.assertEqual(aoe_lines[0], '群攻 区内=3 阈值=3')

    def test_no_log_when_switch_off(self):
        """决策日志关着 → 不写群攻行(10Hz 下不限频会刷爆日志)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        lines = [c.args[0] for c in task.log_debug.call_args_list if c.args]
        self.assertEqual([ln for ln in lines if ln.startswith('群攻 ')], [])


class TestAoeSkipsTurn(unittest.TestCase):
    """群攻双向命中,那一拍转向零收益却要付一次方向键 tap + 作废检测节拍
    (self._last_detect = 0.0)。只跳过真发群攻的那一拍(spec §3.6)。"""

    def test_no_turn_on_aoe_tick(self):
        """面朝右 + 区内 3 只全在左(本该转向) + 群攻就绪 → 不发方向键,只发群攻键。"""
        task = _aoe_task()
        task._facing = 'RIGHT'
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1130), _aoe_mob(1230)])
        sent = _sent(task)
        self.assertIn('f', sent)
        self.assertNotIn('left', sent)
        self.assertNotIn('right', sent)
        self.assertEqual(task._facing, 'RIGHT')   # 朝向信念不动,不产生新分叉

    def test_turns_normally_below_threshold(self):
        """对照组:同样面朝右、怪在左,但只有 1 只 → 照常转向(转向逻辑没被改坏)。"""
        task = _aoe_task()
        task._facing = 'RIGHT'
        _run_with_mobs(task, [_aoe_mob(1030)])
        self.assertIn('left', _sent(task))
        self.assertEqual(task._facing, 'LEFT')

    def test_turns_normally_between_attack_beats(self):
        """节拍未到 → 转向照常(不许「区内够阈值就整段禁转向」,否则节拍间隙里
        怪全在背侧时,单体攻击区是空的,角色面朝空处站着挨打)。"""
        task = _aoe_task()
        task._facing = 'RIGHT'
        task._last_attack = 99.5       # 距 100.0 只过了 0.5 < 攻击间隔 1.5
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1130), _aoe_mob(1230)],
                       now=100.0)
        sent = _sent(task)
        self.assertNotIn('f', sent)
        self.assertIn('left', sent)

    def test_seek_and_aoe_are_mutually_exclusive(self):
        """隐式不变量:crowd 成立 ⇒ 接敌区有怪 ⇒ 走接战分支,不可能同时在寻怪。
        将来有人改 seek_hold 的算法,这条会红(spec §3.8)。"""
        task = _aoe_task()
        _run_with_mobs(task, [_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)], now=100.0)
        self.assertIn('f', _sent(task))           # 这一拍确实放了群攻
        self.assertIsNone(task._seek_dir)         # 同一拍不可能在寻怪


class TestAoeOverlay(unittest.TestCase):
    """群攻就绪时接敌区框加粗 + 标签改名,给 E2E 判据 D 一个可视对象。"""

    def _draw_kwargs(self, mobs):
        task = _aoe_task()
        task._boxes_enabled = MagicMock(return_value=True)
        task._draw_debug = MagicMock()
        _run_with_mobs(task, mobs)
        self.assertTrue(task._draw_debug.called, '_draw_debug 没被调用')
        return task._draw_debug.call_args.kwargs

    def test_aoe_ready_passed_true(self):
        kwargs = self._draw_kwargs([_aoe_mob(1030), _aoe_mob(1230), _aoe_mob(1530)])
        self.assertIs(kwargs['aoe_ready'], True)

    def test_aoe_ready_passed_false_below_threshold(self):
        kwargs = self._draw_kwargs([_aoe_mob(1230), _aoe_mob(1530)])
        self.assertIs(kwargs['aoe_ready'], False)

class TestBuffTimer(unittest.TestCase):
    """定时补BUFF(spec §S5):到点且攻击区无怪 → 按 BUFF 键+更新计时+停手 return;
    攻击区有怪 → 不补,正常攻击;开关关 → 不补;多 BUFF 只补到期的。"""

    def _task(self, buff_list='魔法盾=q:180', switch=True, mode='检测'):
        # 坐椅/走位/寻怪都有独立节拍,会干扰"本拍只补BUFF"的隔离断言,测试里全关
        task = make_task(**{'攻击模式': mode, '补BUFF开关': switch, '补BUFF列表': buff_list,
                            '坐椅开关': False, '走位开关': False, '寻怪开关': False})
        return task

    def test_switch_off_never_buffs(self):
        task = self._task(switch=False)
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0)
        task.send_key.assert_not_called()
        self.assertEqual(task._last_buff_times, {})

    def test_due_and_no_mob_sends_buff_key_and_updates_time(self):
        task = self._task('魔法盾=q:180')
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)  # 从未补过 → 到期
        self.assertEqual(task.send_key.call_args_list, [call('q')])
        self.assertEqual(task._last_buff_times.get('魔法盾'), 200.0)

    def test_not_due_no_key(self):
        task = self._task('魔法盾=q:180')
        task._last_attack_present = False
        task._last_buff_times = {'魔法盾': 100.0}
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)  # 距上次 100s < 180s
        task.send_key.assert_not_called()

    def test_mob_in_zone_skips_buff_and_attacks(self):
        """攻击区有怪 → 不补BUFF,攻击逻辑正常跑。"""
        task = self._task('魔法盾=q:180')
        task._last_attack_present = True
        task.send_key.reset_mock()
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)
        self.assertNotIn(call('q'), task.send_key.call_args_list)
        self.assertEqual(task._last_buff_times, {})

    def test_only_due_buffs_sent(self):
        task = self._task('魔法盾=q:180,狂暴=w:300')
        task._last_attack_present = False
        task._last_buff_times = {'魔法盾': 100.0, '狂暴': 0.0}   # 魔法盾差 80s,狂暴已到期
        # now=280:魔法盾 280-100=180 恰到期;狂暴 280-0=280 < 300 未到期 → 只补魔法盾
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=280.0)
        self.assertEqual(task.send_key.call_args_list, [call('q')])
        self.assertEqual(task._last_buff_times['魔法盾'], 280.0)
        self.assertEqual(task._last_buff_times['狂暴'], 0.0)  # 未补,时间不动

    def test_buff_stops_seek_this_tick(self):
        """触发补BUFF:松寻怪键、停追(_seek_dir=None),本拍 return(不攻击不寻怪)。"""
        task = self._task('魔法盾=q:180')
        task._last_attack_present = False
        task._seek_dir = 'right'
        task._seek_key = '右移键'
        with patch.object(task, '_release_seek_key') as release:
            run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)
        release.assert_called_once()
        self.assertIsNone(task._seek_dir)
        self.assertEqual(task.send_key.call_args_list, [call('q')])
        # 本拍 return:没走到攻击/寻怪,不会发攻击键
        self.assertNotIn(call('shift'), task.send_key.call_args_list)

    def test_no_interval_entry_never_auto_buffs(self):
        """interval None 的项永不自动补(保留手动按键)。"""
        task = self._task('魔法盾=q')   # 无 :间隔
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)
        task.send_key.assert_not_called()
        self.assertEqual(task._last_buff_times, {})

    def test_pause_resets_buff_timer(self):
        """F9 暂停(executor_paused=True)归零补BUFF计时:
        暂停可能持续很久,冻结的时间戳会让恢复后迟迟不补——
        暂停时清空 _last_buff_times → 恢复后第一空闲拍立即补。"""
        task = self._task('魔法盾=q:180')
        task._last_attack_present = False
        task._last_buff_times = {'魔法盾': 100.0}   # 暂停前累计了 100s
        task._on_executor_paused(True)
        self.assertEqual(task._last_buff_times, {}, '暂停必须清空补BUFF计时')
        # 恢复后(模拟 paused=False 后的一拍)立即补:now 任意大,因从未补过 → 到期
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=2000.0)
        self.assertEqual(task.send_key.call_args_list, [call('q')])
        self.assertEqual(task._last_buff_times.get('魔法盾'), 2000.0)

    def test_pause_resume_signal_does_not_reset_timer(self):
        """暂停恢复信号(False)不清空计时——只在真正暂停(True)时归零。"""
        task = self._task('魔法盾=q:180')
        task._last_buff_times = {'魔法盾': 100.0}
        task._on_executor_paused(False)
        self.assertEqual(task._last_buff_times, {'魔法盾': 100.0},
                         '恢复信号不该清空计时')

    def test_multi_buff_same_due_spaced(self):
        """两 BUFF 同到期 → 分拍补:第一拍只按第一个,间隔未到不按,间隔到才按第二个。"""
        task = self._task('魔法盾=q:180,狂暴=w:180')
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)  # 从未补过 → 都到期
        self.assertEqual(task.send_key.call_args_list, [call('q')])        # 只按第一个
        self.assertEqual(task._last_buff_times, {'魔法盾': 200.0, '狂暴': 200.0})  # 入队即计时
        self.assertEqual(len(task._buff_queue), 1)
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.2)  # 间隔未到(0.2<0.5)
        self.assertEqual(task.send_key.call_args_list, [call('q')])        # 不按
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.5)  # 间隔到(0.5)
        self.assertEqual(task.send_key.call_args_list, [call('q'), call('w')])
        self.assertEqual(len(task._buff_queue), 0)

    def test_buff_queue_paused_when_mob(self):
        """队列推进中来怪 → 不按键、队列保留;怪消失后继续补。"""
        task = self._task('魔法盾=q:180,狂暴=w:180')
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)
        self.assertEqual(task.send_key.call_args_list, [call('q')])
        self.assertEqual(len(task._buff_queue), 1)
        task._last_attack_present = True
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.5)  # 有怪:整个块跳过
        self.assertEqual(task.send_key.call_args_list, [call('q')])        # 不按
        self.assertEqual(len(task._buff_queue), 1)                          # 队列保留
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.5)  # 怪走,间隔已到
        self.assertEqual(task.send_key.call_args_list, [call('q'), call('w')])
        self.assertEqual(len(task._buff_queue), 0)

    def test_pause_clears_buff_queue(self):
        """暂停清空队列+计时;恢复后重新入队补齐。"""
        task = self._task('魔法盾=q:180,狂暴=w:180')
        task._last_attack_present = False
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=200.0)
        self.assertEqual(len(task._buff_queue), 1)
        task._on_executor_paused(True)
        self.assertEqual(len(task._buff_queue), 0)
        self.assertEqual(task._last_buff_times, {})
        run_with_frame(task, hp=1.0, mp=1.0, exp=1.0, now=2000.0)  # 恢复,从未补过 → 重新入队
        self.assertEqual(task.send_key.call_args_list, [call('q'), call('w')])  # 第一拍按 q,队列剩 w
        self.assertEqual(len(task._buff_queue), 1)
