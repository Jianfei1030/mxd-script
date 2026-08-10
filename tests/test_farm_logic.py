import unittest
from unittest.mock import patch

from src.task import farm_logic as fl


class TestFarmLogic(unittest.TestCase):

    def test_need_hp_potion(self):
        self.assertTrue(fl.need_hp_potion(0.5, 0.7))
        self.assertFalse(fl.need_hp_potion(0.7, 0.7))

    def test_need_mp_potion(self):
        self.assertTrue(fl.need_mp_potion(0.2, 0.35))
        self.assertFalse(fl.need_mp_potion(0.9, 0.35))

    def test_emergency(self):
        self.assertTrue(fl.is_emergency(0.24, 0.25))
        self.assertFalse(fl.is_emergency(0.25, 0.25))

    def test_emergency_action(self):
        self.assertEqual(fl.emergency_action('t'), 'return_scroll')
        self.assertEqual(fl.emergency_action(''), 'stop')
        self.assertEqual(fl.emergency_action('  '), 'stop')

    def test_potion_not_working(self):
        self.assertTrue(fl.potion_not_working(5, 5))
        self.assertFalse(fl.potion_not_working(4, 5))

    def test_potions_exhausted(self):
        self.assertEqual(fl.potions_exhausted(0.5, 0.7, 0, 0.9, 0.35, 10), 'hp')
        self.assertEqual(fl.potions_exhausted(0.9, 0.7, 10, 0.2, 0.35, 0), 'mp')
        self.assertIsNone(fl.potions_exhausted(0.9, 0.7, 10, 0.9, 0.35, 10))
        self.assertIsNone(fl.potions_exhausted(0.5, 0.7, None, 0.9, 0.35, None))  # 未知不判

    def test_should_attack(self):
        self.assertTrue(fl.should_attack(10.0, 8.4, 1.5))
        self.assertFalse(fl.should_attack(10.0, 9.0, 1.5))

    def test_should_detect_three_cadences(self):
        # 在打:按攻击间隔(慢)。检测本来就是为下一刀服务,不必更快,负载不回归
        self.assertFalse(fl.should_detect(1000.5, 1000.0, True, False, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.75, 1000.0, True, False, 0.7, 0.1, 0.3))
        # 在追:按寻怪刷新间隔(最快)。目标死了/换近了要立刻改方向
        self.assertFalse(fl.should_detect(1000.05, 1000.0, False, True, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.15, 1000.0, False, True, 0.7, 0.1, 0.3))
        # 空闲:按空闲刷新间隔 —— 这是「起步寻怪」唯一的入口(spec §3.1)
        self.assertFalse(fl.should_detect(1000.2, 1000.0, False, False, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.35, 1000.0, False, False, 0.7, 0.1, 0.3))

    def test_should_detect_attacking_beats_seeking(self):
        # 攻击区里有怪就是在打,不该被寻怪的快间隔拉高负载
        self.assertFalse(fl.should_detect(1000.15, 1000.0, True, True, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.75, 1000.0, True, True, 0.7, 0.1, 0.3))

    def test_should_detect_boundary_is_inclusive(self):
        # 与 should_attack 同口径:恰好到点就放行,别让浮点抖动多等一拍
        self.assertTrue(fl.should_detect(1000.5, 1000.0, False, False, 0.7, 0.1, 0.5))

    def test_seek_persist_holds_through_a_missed_tick(self):
        # 这一拍检出了 → 直接用这一拍的方向
        self.assertEqual(fl.seek_persist('left', 'right', 100.0, 99.0, 0.5), 'left')
        # 这一拍没检出,但距上次检出还在保持窗内 → 继续按上一拍方向走
        self.assertEqual(fl.seek_persist(None, 'right', 100.3, 100.0, 0.5), 'right')
        # 边界:恰好等于保持窗 → 仍然保持
        self.assertEqual(fl.seek_persist(None, 'right', 100.5, 100.0, 0.5), 'right')
        # 超出保持窗 → 停追
        self.assertIsNone(fl.seek_persist(None, 'right', 100.6, 100.0, 0.5))

    def test_seek_persist_degrades_safely(self):
        # 上一拍本来就没在追 → 没什么可保持的
        self.assertIsNone(fl.seek_persist(None, None, 100.1, 100.0, 0.5))
        # 从没检出过同层怪
        self.assertIsNone(fl.seek_persist(None, 'right', 100.1, None, 0.5))
        # 保持窗 0 = 关掉去抖,退回旧行为(一拍判失立刻停)
        self.assertIsNone(fl.seek_persist(None, 'right', 100.0, 100.0, 0.0))

    def test_potion_window_elapsed(self):
        self.assertFalse(fl.potion_window_elapsed(100.5, 100.0, 1.0))
        self.assertTrue(fl.potion_window_elapsed(101.0, 100.0, 1.0))  # 边界:恰好一个窗口 → 已过

    def test_should_pickup(self):
        self.assertFalse(fl.should_pickup(100.0, 0.0, 30.0, False))
        self.assertTrue(fl.should_pickup(100.0, 0.0, 30.0, True))
        self.assertFalse(fl.should_pickup(20.0, 0.0, 30.0, True))

    def test_should_feed_pet(self):
        self.assertTrue(fl.should_feed_pet(900.0, 0.0, 900, True))
        self.assertFalse(fl.should_feed_pet(899.9, 0.0, 900, True))  # 未到间隔
        self.assertFalse(fl.should_feed_pet(900.0, 0.0, 900, False))  # 开关关

    def test_parse_buff_config(self):
        self.assertEqual(fl.parse_buff_config('magic_shield=q,armor=w'),
                         [('magic_shield', 'q'), ('armor', 'w')])
        self.assertEqual(fl.parse_buff_config(''), [])
        self.assertEqual(fl.parse_buff_config('  '), [])
        self.assertEqual(fl.parse_buff_config('bad-entry,good=x'), [('good', 'x')])

    def test_is_dead(self):
        self.assertTrue(fl.is_dead(0.0))
        self.assertTrue(fl.is_dead(0.01))
        self.assertFalse(fl.is_dead(0.02))
        self.assertFalse(fl.is_dead(0.5))

    def test_walk_confirmed(self):
        # 按右键且真的往右走够了 → 确认朝右
        self.assertTrue(fl.walk_confirmed('right', 1000.0, 1045.0, 40))
        # 位移不够 → 不确认(可能只是锚点抖动)
        self.assertFalse(fl.walk_confirmed('right', 1000.0, 1030.0, 40))
        # 按右键却往左动 = 撞墙/锚点跳变,绝不能据此标定
        self.assertFalse(fl.walk_confirmed('right', 1000.0, 955.0, 40))
        # 按左键且真的往左走够了
        self.assertTrue(fl.walk_confirmed('left', 1000.0, 955.0, 40))
        self.assertFalse(fl.walk_confirmed('left', 1000.0, 1045.0, 40))
        # 没在寻怪 / 没记起点 → 一律不确认
        self.assertFalse(fl.walk_confirmed(None, 1000.0, 1045.0, 40))
        self.assertFalse(fl.walk_confirmed('right', None, 1045.0, 40))

    def test_crowd_present(self):
        # 等于阈值算命中:阈值语义是「达到就用群攻」,与 should_attack 的 >= 同口径
        self.assertTrue(fl.crowd_present(3, 3))
        self.assertTrue(fl.crowd_present(4, 3))
        self.assertFalse(fl.crowd_present(2, 3))
        self.assertFalse(fl.crowd_present(0, 3))
        # 阈值 <= 0 = 功能关闭,不许因为「0 只怪 >= 0」而恒真
        self.assertFalse(fl.crowd_present(5, 0))
        self.assertFalse(fl.crowd_present(5, -1))
        self.assertFalse(fl.crowd_present(0, 0))


class TestAttackZone(unittest.TestCase):

    def test_zone_centered(self):
        self.assertEqual(fl.attack_zone((1280, 630), 600, 200),
                         (980.0, 530.0, 1580.0, 730.0))

    def test_point_inside(self):
        zone = fl.attack_zone((1280, 630), 600, 200)
        self.assertTrue(fl.point_in_zone((1280, 630), zone))

    def test_point_on_edge_counts_as_inside(self):
        zone = fl.attack_zone((1280, 630), 600, 200)
        self.assertTrue(fl.point_in_zone((980.0, 530.0), zone))
        self.assertTrue(fl.point_in_zone((1580.0, 730.0), zone))

    def test_point_outside(self):
        zone = fl.attack_zone((1280, 630), 600, 200)
        self.assertFalse(fl.point_in_zone((1581.0, 630), zone))
        self.assertFalse(fl.point_in_zone((1280, 529.0), zone))

    def test_mob_in_zone_any(self):
        zone = fl.attack_zone((1280, 630), 600, 200)
        self.assertTrue(fl.mob_in_zone([(100, 100), (1300, 640)], zone))

    def test_mob_in_zone_none(self):
        zone = fl.attack_zone((1280, 630), 600, 200)
        self.assertFalse(fl.mob_in_zone([(100, 100), (2400, 1300)], zone))

    def test_no_mobs(self):
        zone = fl.attack_zone((1280, 630), 600, 200)
        self.assertFalse(fl.mob_in_zone([], zone))


class TestAnchorTiming(unittest.TestCase):

    def test_never_acquired_counts_as_expired(self):
        self.assertTrue(fl.anchor_expired(100.0, None, 10))

    def test_fresh_anchor(self):
        self.assertFalse(fl.anchor_expired(105.0, 100.0, 10))

    def test_expired_anchor(self):
        self.assertTrue(fl.anchor_expired(111.0, 100.0, 10))
        # 边界:年龄恰好等于保鲜期 → 按 spec"年龄 ≤ 保鲜期视为不过期",应为 False(实现用严格 >)
        self.assertFalse(fl.anchor_expired(110.0, 100.0, 10))

    def test_rescan_throttle(self):
        self.assertFalse(fl.should_rescan_anchor(101.0, 100.0, 2))
        self.assertTrue(fl.should_rescan_anchor(102.0, 100.0, 2))

    def test_anchor_vx_learns_lowpass(self):
        # 相邻命中 dt=1s,右移 20px → v=20;低通 0.7*20 + 0.3*0
        self.assertEqual(fl.anchor_vx_update(0.0, dx=20, dt=1, dy=0), 0.7 * 20.0)

    def test_anchor_vx_rejects_implausible_spike(self):
        # 720px/s 的跳变(回退/误检)不许学
        self.assertEqual(fl.anchor_vx_update(0.0, dx=720, dt=1, dy=0), 0.0)

    def test_anchor_vx_rejects_platform_change(self):
        # 名字牌 y 位移 50px(换平台)≠ 行走,不学
        self.assertEqual(fl.anchor_vx_update(0.0, dx=20, dt=1, dy=50), 0.0)

    def test_anchor_vx_rejects_stale_gap(self):
        # dt 超 2s:期间可能停过/回退过,速度不可信
        self.assertEqual(fl.anchor_vx_update(0.0, dx=20, dt=3, dy=0), 0.0)


class TestWarriorZone(unittest.TestCase):
    """战士巡逻/近战攻击区纯函数(T1.1, spec §3.3)。"""

    def test_mob_feet(self):
        mob = type('Box', (), {'x': 100, 'y': 200, 'width': 60, 'height': 50})()
        self.assertEqual(fl.mob_feet(mob), (130, 250))  # 脚底 = (x+w/2, y+h)

    def test_warrior_attack_zone_left(self):
        # 身体中心 (1280, 700),朝左,距离 120,高 200
        zone = fl.warrior_attack_zone((1280, 700), 'LEFT', 120, 200)
        self.assertEqual(zone, (1160, 600, 120, 200))  # x∈[1160,1280], y∈[600,800]

    def test_warrior_attack_zone_right(self):
        zone = fl.warrior_attack_zone((1280, 700), 'RIGHT', 120, 200)
        self.assertEqual(zone, (1280, 600, 120, 200))  # x∈[1280,1400]

    def test_warrior_attack_zone_unknown_facing_defaults_right(self):
        zone = fl.warrior_attack_zone((1280, 700), 'UP', 120, 200)
        self.assertEqual(zone, (1280, 600, 120, 200))  # 未知朝向按右

    def test_mob_in_zone_hit(self):
        zone = (1160, 600, 120, 200)
        mob = type('Box', (), {'x': 1190, 'y': 550, 'width': 40, 'height': 60})()
        self.assertTrue(fl.mob_feet_in_zone(mob, zone))  # 脚底 (1210, 610) 在区内

    def test_mob_in_zone_miss(self):
        zone = (1160, 600, 120, 200)
        mob = type('Box', (), {'x': 900, 'y': 600, 'width': 40, 'height': 60})()
        self.assertFalse(fl.mob_feet_in_zone(mob, zone))  # 脚底 (920, 660) 在区外

    def test_mob_in_zone_edge(self):
        zone = (1160, 600, 120, 200)
        mob = type('Box', (), {'x': 1140, 'y': 550, 'width': 40, 'height': 60})()
        self.assertTrue(fl.mob_feet_in_zone(mob, zone))  # 脚底 (1160, 610) 正好压左边界

    def test_facing_update(self):
        self.assertEqual(fl.facing_update('LEFT', 'left'), 'LEFT')
        self.assertEqual(fl.facing_update('LEFT', 'right'), 'RIGHT')
        self.assertEqual(fl.facing_update(None, 'left'), 'LEFT')
        self.assertEqual(fl.facing_update(None, None), 'RIGHT')  # 无历史默认右

    def test_patrol_direction(self):
        self.assertEqual(fl.patrol_direction(0.1, 0.2, 0.8), 'right')   # 靠左 → 向右
        self.assertEqual(fl.patrol_direction(0.9, 0.2, 0.8), 'left')    # 靠右 → 向左
        self.assertEqual(fl.patrol_direction(0.5, 0.2, 0.8), None)      # 中间 → 保持
        self.assertEqual(fl.patrol_direction(0.2, 0.2, 0.8), None)      # 正好压左界 → 保持

    def test_should_approach(self):
        # 怪脚底与身体中心水平距离 > 攻击距离 → 需接近
        self.assertTrue(fl.should_approach((1280, 700), (1000, 700), 120))
        self.assertFalse(fl.should_approach((1280, 700), (1250, 700), 120))

    def test_walk_order_facing_left_stays_left(self):
        # 朝左 → 先向右走出、再向左走回,结束时仍朝左(走位不翻转朝向)
        self.assertEqual(fl.walk_order('LEFT'), ('right', 'left', 'LEFT'))

    def test_walk_order_facing_right_stays_right(self):
        # 朝右 → 先向左走出、再向右走回,结束时仍朝右
        self.assertEqual(fl.walk_order('RIGHT'), ('left', 'right', 'RIGHT'))

    def test_walk_order_unknown_random_left(self):
        # 朝向未知(首次走位):随机一侧出、反方向回,采纳走完后的实际朝向(第二段方向)
        with patch('src.task.farm_logic.random.choice', return_value='left'):
            self.assertEqual(fl.walk_order(None), ('left', 'right', 'RIGHT'))

    def test_walk_order_unknown_random_right(self):
        with patch('src.task.farm_logic.random.choice', return_value='right'):
            self.assertEqual(fl.walk_order(None), ('right', 'left', 'LEFT'))

    def test_turn_direction_facing_wrong_side(self):
        # 朝右但怪在左 → 需按左转向;朝左但怪在右 → 需按右转向
        self.assertEqual(fl.turn_direction('RIGHT', 1280, 1000), 'left')
        self.assertEqual(fl.turn_direction('LEFT', 1280, 1500), 'right')

    def test_turn_direction_facing_correct_side(self):
        # 已面朝怪所在侧 → 不转向
        self.assertIsNone(fl.turn_direction('RIGHT', 1280, 1500))
        self.assertIsNone(fl.turn_direction('LEFT', 1280, 1000))

    def test_turn_direction_unknown_facing_turns_to_mob(self):
        # 朝向未知 → 按怪所在侧转向
        self.assertEqual(fl.turn_direction(None, 1280, 1000), 'left')
        self.assertEqual(fl.turn_direction(None, 1280, 1500), 'right')

    def test_nearest_mob_x_picks_closest_in_zone(self):
        zone = fl.attack_zone((1280, 630), 600, 200)  # x∈[980,1580], y∈[530,730]
        centres = [(1500, 640), (1000, 700), (2000, 200)]
        self.assertEqual(fl.nearest_mob_x(centres, zone, 1280), 1500)  # 区内两个,取近的

    def test_nearest_mob_x_none_in_zone(self):
        zone = fl.attack_zone((1280, 630), 600, 200)
        self.assertIsNone(fl.nearest_mob_x([(2000, 200), (100, 100)], zone, 1280))

    def test_same_floor_within_tolerance(self):
        self.assertTrue(fl.same_floor(800, 800, 60))      # 同高
        self.assertTrue(fl.same_floor(830, 800, 60))      # 差 30 ≤ 容差
        self.assertTrue(fl.same_floor(860, 800, 60))      # 边界:恰好容差 → 同层

    def test_same_floor_beyond_tolerance(self):
        self.assertFalse(fl.same_floor(861, 800, 60))     # 差 61 > 容差 → 不同层
        self.assertFalse(fl.same_floor(700, 800, 60))     # 高一层(负方向同样不追)

    def test_seek_direction_nearest_same_floor_mob(self):
        # 同层怪左右都有 → 取水平距离最近的;不同层的忽略
        entries = [(700, 800), (2000, 800), (900, 950)]   # (中心x, 脚底y)
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60), 'left')
        # 改近在右侧时 → 向右
        entries = [(700, 800), (1700, 800)]
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60), 'right')

    def test_seek_direction_left_only(self):
        entries = [(900, 800)]
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60), 'left')

    def test_seek_direction_right_only(self):
        entries = [(1800, 800)]
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60), 'right')

    def test_seek_direction_ignores_other_floor(self):
        # 有怪但全在不同层 → 不寻怪
        entries = [(900, 1000), (1800, 900)]
        self.assertIsNone(fl.seek_direction(entries, 1280, 800, 60))

    def test_seek_direction_empty(self):
        self.assertIsNone(fl.seek_direction([], 1280, 800, 60))


class TestTargetSideLock(unittest.TestCase):
    """目标侧锁定:消除"每拍重选 argmin 最近怪"导致的左右反复转向。

    实测(219 帧重放,配置 800x200):攻击分支相邻采样最近怪换边 12/32,
    寻怪分支方向翻转 8/28——缩小攻击区并不能降低翻转率,因为翻转来自
    选目标的规则本身。锁定规则:面朝侧还有目标就不换边。
    """

    ZONE = fl.attack_zone((1280, 630), 800, 200)   # x∈[880,1680], y∈[530,730]

    def test_keeps_facing_side_when_it_still_has_a_mob(self):
        # 面朝右,右侧区内有怪(远) + 左侧区内有怪(更近):
        # 旧 argmin 会选左边那只并转向,新规则保持朝右继续打
        centres = [(1600, 640), (900, 640)]
        self.assertIsNone(fl.attack_turn_direction('RIGHT', 1280, centres, self.ZONE))

    def test_keeps_facing_left_side_when_it_still_has_a_mob(self):
        centres = [(920, 640), (1650, 640)]
        self.assertIsNone(fl.attack_turn_direction('LEFT', 1280, centres, self.ZONE))

    def test_turns_when_facing_side_has_no_mob(self):
        # 面朝右但右侧区内已空 → 才允许转向左
        centres = [(900, 640)]
        self.assertEqual(fl.attack_turn_direction('RIGHT', 1280, centres, self.ZONE), 'left')

    def test_turns_right_when_left_side_empty(self):
        centres = [(1600, 640)]
        self.assertEqual(fl.attack_turn_direction('LEFT', 1280, centres, self.ZONE), 'right')

    def test_unknown_facing_turns_to_nearest_side(self):
        # 朝向未知(首次接战)→ 仍按最近怪定向
        centres = [(1600, 640), (1100, 640)]
        self.assertEqual(fl.attack_turn_direction(None, 1280, centres, self.ZONE), 'left')

    def test_no_turn_when_zone_empty(self):
        # 区内无怪(怪都在区外)→ 不转向
        self.assertIsNone(fl.attack_turn_direction('RIGHT', 1280, [(2400, 640)], self.ZONE))

    def test_mob_exactly_at_body_x_counts_as_facing_side(self):
        # 怪正压在身上:不该因为 <=/< 的判边噪声反复翻转,面朝侧即视为有目标
        self.assertIsNone(fl.attack_turn_direction('RIGHT', 1280, [(1280, 640)], self.ZONE))

    def test_seek_keeps_current_direction_while_that_side_has_mob(self):
        # 正在向右追,右侧同层怪(远) + 左侧同层怪(更近)→ 不掉头
        entries = [(2000, 800), (900, 800)]
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60, current_dir='right'), 'right')

    def test_seek_switches_when_current_direction_side_empty(self):
        # 向右追但右侧同层已无怪 → 才换向左
        entries = [(900, 800)]
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60, current_dir='right'), 'left')

    def test_seek_current_direction_ignores_other_floor_mobs(self):
        # 右侧只有不同层的怪 → 不算"那一侧还有目标",应换向左
        entries = [(2000, 1000), (900, 800)]
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60, current_dir='right'), 'left')

    def test_seek_without_current_direction_keeps_nearest_behaviour(self):
        # 未在寻怪(current_dir=None)→ 保持原"最近同层怪"行为,老调用不受影响
        entries = [(700, 800), (1700, 800)]
        self.assertEqual(fl.seek_direction(entries, 1280, 800, 60, current_dir=None), 'right')


class TestNearestMobSide(unittest.TestCase):
    """攻击前必转的方向依据:接敌区内最近怪的观测方向(不再读盲写 _facing)。

    2026-08-08:信念被击退/按键丢失破坏后攻击区画错侧 → 怪不在区内 → 不攻击也无
    修正机会,死锁。有向攻击区改为按观测怪方向画半区,怪必然落进攻击区。"""

    ZONE = fl.attack_zone((1280, 630), 600, 200)   # x∈[980,1580], y∈[530,730]

    def test_nearest_on_left_returns_left(self):
        centres = [(1100, 640), (1500, 640)]
        self.assertEqual(fl.nearest_mob_side(centres, self.ZONE, 1280), (1100, 'left'))

    def test_nearest_on_right_returns_right(self):
        centres = [(1000, 640), (1500, 640), (2000, 200)]
        self.assertEqual(fl.nearest_mob_side(centres, self.ZONE, 1280), (1500, 'right'))

    def test_mob_exactly_at_body_x_counts_as_right(self):
        # 怪压身上:判边噪声不许引发左右横跳,固定按 right
        self.assertEqual(fl.nearest_mob_side([(1280, 640)], self.ZONE, 1280), (1280, 'right'))

    def test_mob_inside_zone_left_of_body(self):
        # 区内近左怪 + 区外更近的怪:只按区内怪定向(区外的不参与攻击判定)
        centres = [(1100, 640), (1000, 200)]
        self.assertEqual(fl.nearest_mob_side(centres, self.ZONE, 1280), (1100, 'left'))

    def test_no_mob_in_zone_returns_none(self):
        self.assertEqual(fl.nearest_mob_side([(2000, 200), (100, 100)], self.ZONE, 1280),
                         (None, None))

    def test_empty_centres_returns_none(self):
        self.assertEqual(fl.nearest_mob_side([], self.ZONE, 1280), (None, None))


class TestAttackPreTap(unittest.TestCase):
    """攻击前垫步方向:最近怪在哪侧就轻点哪侧方向键(不比较 facing)。

    2026-08-09 需求:战士 _facing 是盲写信念,被击退/按键丢失破坏后攻击区内有怪
    (attack_turn_direction 认为"面朝侧还有目标"不转向),角色背对怪一直砍空气。
    垫步不信任信念,攻击前无条件朝最近怪所在侧轻点——信念错则物理修正,
    信念对则 no-op(已朝该侧按方向键零代价,50ms 位移可忽略)。"""

    ZONE = fl.attack_zone((1280, 630), 600, 200)   # x∈[980,1580], y∈[530,730]

    def test_mob_on_left_returns_left(self):
        centres = [(1100, 640), (1500, 640)]
        self.assertEqual(fl.attack_pre_tap_direction(centres, self.ZONE, 1280), 'left')

    def test_mob_on_right_returns_right(self):
        centres = [(1000, 640), (1500, 640)]
        self.assertEqual(fl.attack_pre_tap_direction(centres, self.ZONE, 1280), 'right')

    def test_nearest_mob_wins_over_far_mob(self):
        # 左右都有怪:朝最近的一侧垫步(远的等打完这只再处理)
        centres = [(1010, 640), (1560, 640)]
        self.assertEqual(fl.attack_pre_tap_direction(centres, self.ZONE, 1280), 'left')

    def test_mob_exactly_at_body_x_counts_as_right(self):
        # 怪压身上:判边噪声不许引发左右横跳,固定按 right(与 nearest_mob_side 同规则)
        self.assertEqual(fl.attack_pre_tap_direction([(1280, 640)], self.ZONE, 1280), 'right')

    def test_mob_inside_zone_ignores_outside_mob(self):
        # 区外更近的怪不参与:垫步只服务攻击判定(与 nearest_mob_side 同规则)
        centres = [(1100, 640), (1000, 200)]
        self.assertEqual(fl.attack_pre_tap_direction(centres, self.ZONE, 1280), 'left')

    def test_no_mob_in_zone_returns_none(self):
        self.assertIsNone(fl.attack_pre_tap_direction([(2000, 200), (100, 100)],
                                                      self.ZONE, 1280))

    def test_empty_centres_returns_none(self):
        self.assertIsNone(fl.attack_pre_tap_direction([], self.ZONE, 1280))


class TestMobPresentDebounce(unittest.TestCase):
    """区内有怪的去抖:一拍漏检不许立刻退出攻击态。

    2026-08-07 逐拍日志(363 拍)实测:区内怪数为 0 的拍占 76%,进入"可攻击"状态
    28 次但中位只维持 1.07 秒、14 段不到 1 秒,攻击键被反复松开重按 31 次。
    法师一次施法约 1 秒,技能基本放不出来就被打断——这是"不攻击"的直接成因。
    YOLO 单帧 recall 0.886,且自己的攻击特效会遮挡目标,一拍漏检就退出是过度敏感。
    """

    def test_raw_present_is_true(self):
        self.assertTrue(fl.mob_present_debounced(True, 100.0, None, 1.0))

    def test_stays_true_within_grace(self):
        # 上次见到怪是 100.0,现在 100.6,保持窗 1.0 内 → 仍按有怪处理,攻击不松手
        self.assertTrue(fl.mob_present_debounced(False, 100.6, 100.0, 1.0))

    def test_boundary_exactly_at_grace_still_true(self):
        self.assertTrue(fl.mob_present_debounced(False, 101.0, 100.0, 1.0))

    def test_false_after_grace_expires(self):
        self.assertFalse(fl.mob_present_debounced(False, 101.01, 100.0, 1.0))

    def test_false_when_never_seen(self):
        self.assertFalse(fl.mob_present_debounced(False, 100.0, None, 1.0))

    def test_zero_grace_disables_debounce(self):
        # 保持窗设 0 → 退回旧行为(一拍空立刻退出),给用户留关掉的余地
        self.assertFalse(fl.mob_present_debounced(False, 100.01, 100.0, 0))


class TestTurnCooldown(unittest.TestCase):
    """转向冷却:两次转向之间的最小间隔。

    同一份日志实测:转向 17 次里 12 次是反向翻转(71%),序列 LLLLRLRLRLRLRLLRL,
    相邻反向间隔约 1.4-1.5 秒——比一次施法还短,角色光在原地左右扭。
    冷却必须长于一次施法才能打断这种交替。
    """

    def test_allowed_when_cooldown_elapsed(self):
        self.assertTrue(fl.turn_allowed(101.5, 100.0, 1.5))

    def test_blocked_within_cooldown(self):
        self.assertFalse(fl.turn_allowed(101.4, 100.0, 1.5))

    def test_first_turn_always_allowed(self):
        # 从未转过向(哨兵 0.0)→ 不该被冷却挡住
        self.assertTrue(fl.turn_allowed(100.0, 0.0, 1.5))

    def test_zero_cooldown_allows_every_turn(self):
        self.assertTrue(fl.turn_allowed(100.0, 100.0, 0))


class TestKnockbackDetected(unittest.TestCase):
    """受击检测:HP 下降超阈值,或锚点 x 突变且方向远离最近怪。

    2026-08-07 实测结论:冒险岛被怪碰到会往远离怪物的方向击退并翻转朝向来面对
    怪物——朝向信念(_facing)是盲写的,击退是唯一破坏源,必须用受击事件把它
    置为未知,下一检测拍按最近怪定向重建。
    """

    def test_hp_drop_over_threshold(self):
        self.assertTrue(fl.knockback_detected(0.50, 0.70))

    def test_hp_drop_exactly_at_threshold_not_counted(self):
        # 严格"超阈值"才判受击:恰好掉 2% 不触发(浮点下精确相等罕见,语义保守)
        self.assertFalse(fl.knockback_detected(0.68, 0.70))

    def test_hp_drop_just_over_threshold_counts(self):
        # 略超 2%(血条 1 列 ≈0.5%,2% 已是 4 列,不是噪声)→ 受击
        self.assertTrue(fl.knockback_detected(0.679, 0.70))

    def test_small_hp_drop_ignored(self):
        self.assertFalse(fl.knockback_detected(0.69, 0.70))

    def test_no_prev_hp_ignored(self):
        # 第一拍/重新启用:prev_hp=None,不能把初始值当掉血
        self.assertFalse(fl.knockback_detected(0.50, None))

    def test_hp_rise_ignored(self):
        # 喝药/自然回血:HP 上升不算受击
        self.assertFalse(fl.knockback_detected(0.80, 0.70))

    def test_hp_equal_ignored(self):
        self.assertFalse(fl.knockback_detected(0.70, 0.70))

    def test_x_jump_away_from_mob_detects(self):
        # 怪在左(800),人被推右(1200→1270)→ 击退
        self.assertTrue(fl.knockback_detected(0.70, 0.70,
                                              prev_x=1200, new_x=1270, mob_xs=[800]))

    def test_x_jump_toward_mob_is_walk_not_knockback(self):
        # 怪在右(1600),人朝怪走(1200→1270)→ 主动寻怪,不是受击
        self.assertFalse(fl.knockback_detected(0.70, 0.70,
                                               prev_x=1200, new_x=1270, mob_xs=[1600]))

    def test_small_x_jump_ignored(self):
        self.assertFalse(fl.knockback_detected(0.70, 0.70,
                                               prev_x=1200, new_x=1230, mob_xs=[800]))

    def test_x_jump_without_mob_ignored(self):
        # 无怪可判方向:位移可能是任何原因(换地图/相机),不算受击
        self.assertFalse(fl.knockback_detected(0.70, 0.70,
                                               prev_x=1200, new_x=1270, mob_xs=[]))

    def test_x_jump_without_anchor_ignored(self):
        self.assertFalse(fl.knockback_detected(0.70, 0.70,
                                               prev_x=None, new_x=1270, mob_xs=[800]))


class TestKnockbackDebounced(unittest.TestCase):
    """受击防抖:一次真实掉血只算一次受击。

    2026-08-08 日志实测:一次掉 6.6% 被血条渐变动画拆成 0.7s 内多拍
    ≥2% 的读数,每拍都触发受击(0.2s 内连报 3 次)——每次受击都会
    作废朝向 + 重置转向冷却,冷却形同虚设。游戏受击后约 1s 无敌,
    1s 内不可能有新的真实掉血,防抖取 1s 不会漏真受击。
    """

    def test_raw_hit_false_never_counts(self):
        self.assertFalse(fl.knockback_debounced(False, 10.0, 9.0, 1.0))

    def test_first_hit_always_counts(self):
        # last_hit=None(从未受击)天然放行;last_hit=0.0 哨兵同样放行(now 必远大于 1)
        self.assertTrue(fl.knockback_debounced(True, 10.0, None, 1.0))
        self.assertTrue(fl.knockback_debounced(True, 10.0, 0.0, 1.0))

    def test_hit_within_debounce_window_suppressed(self):
        # 同一掉血的渐变尾巴:0.2s 内再来 → 不算新受击
        self.assertFalse(fl.knockback_debounced(True, 10.2, 10.0, 1.0))

    def test_hit_after_debounce_window_counts(self):
        # 1s 无敌已过,再掉血 = 新的真实受击
        self.assertTrue(fl.knockback_debounced(True, 11.0, 10.0, 1.0))
        self.assertTrue(fl.knockback_debounced(True, 11.2, 10.0, 1.0))

    def test_debounce_zero_disables(self):
        # 设 0 = 关掉防抖,每拍掉血都算受击(旧行为)
        self.assertTrue(fl.knockback_debounced(True, 10.2, 10.0, 0.0))


class TestStunSuppressed(unittest.TestCase):
    """硬直抑制窗:受击后 0.5s 内不转向、不攻击。

    2026-08-08 日志实测:受击后 0.3s/0.5s 的转向 tap 落在击退硬直里被
    游戏吞掉,但转向代码照常盲写朝向 → 信念分叉 → 打空。抑制窗从源头
    掐掉「键被吞、信念照写」:硬直期间根本不按转向/攻击键。
    """

    def test_suppress_zero_disables(self):
        # 设 0 = 关掉抑制,恒放行
        self.assertFalse(fl.stun_suppressed(10.2, 10.0, 0.0))

    def test_never_hit_always_passes(self):
        # 0.0 哨兵 = 从未受击,不受抑制
        self.assertFalse(fl.stun_suppressed(10.5, 0.0, 0.5))

    def test_within_window_suppressed(self):
        # 受击后 0.2s:硬直中,不许转向/攻击
        self.assertTrue(fl.stun_suppressed(10.2, 10.0, 0.5))
        self.assertTrue(fl.stun_suppressed(10.49, 10.0, 0.5))

    def test_after_window_passes(self):
        # 硬直已过:放行
        self.assertFalse(fl.stun_suppressed(10.5, 10.0, 0.5))
        self.assertFalse(fl.stun_suppressed(11.0, 10.0, 0.5))


class TestFacingHalfZone(unittest.TestCase):
    """有向攻击区 = 对称接敌区的面朝侧一半。

    接收「已算好的 zone」而不是 (center, width, height):调用方本来就有 zone,
    传它进去保证接敌区与攻击区严格同源,y 范围一定一致,不会因为两处各算一次而漂移。
    """

    ZONE = (880.0, 530.0, 1680.0, 730.0)   # 宽 800 高 200,身体在正中
    BODY_X = 1280.0

    def test_right_keeps_right_half(self):
        self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, 'RIGHT'),
                         (1280.0, 530.0, 1680.0, 730.0))

    def test_left_keeps_left_half(self):
        self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, 'LEFT'),
                         (880.0, 530.0, 1280.0, 730.0))

    def test_unknown_facing_returns_full_zone(self):
        """朝向未知 → 整个接敌区(spec §4.3)。

        不制造新的挂死风险:若改成"不知道朝向就不打",一旦转向键长期送不出去
        (窗口失焦),_facing 会一直是 None,角色就永远不攻击。回退成对称区
        最坏也只是保持改动前的表现。
        """
        self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, None), self.ZONE)

    def test_invalid_facing_returns_full_zone(self):
        """非法朝向值不许抛——朝向是别处写进来的字符串,这里只做几何。"""
        for bad in ('UP', '', 'left', 0):
            self.assertEqual(fl.facing_half_zone(self.ZONE, self.BODY_X, bad), self.ZONE)

    def test_y_range_never_changes(self):
        for facing in ('LEFT', 'RIGHT', None, 'UP'):
            _, y0, _, y1 = fl.facing_half_zone(self.ZONE, self.BODY_X, facing)
            self.assertEqual((y0, y1), (530.0, 730.0))

    def test_body_outside_zone_degenerates_not_raises(self):
        """锚点外推/回退可能让 body_x 落到 zone 外。不许抛;
        退化成空矩形(x0 >= x1)即可,point_in_zone 天然判否。"""
        z = fl.facing_half_zone(self.ZONE, 100.0, 'LEFT')   # 身体在区左外侧
        self.assertEqual(z[1], 530.0)
        self.assertEqual(z[3], 730.0)
        self.assertFalse(fl.point_in_zone((1000.0, 630.0), z))

    def test_boundary_point_on_body_belongs_to_both_facings(self):
        """正压在身上的怪(x == body_x)两个朝向都算命中:
        这种怪的左右判定纯是噪声,与 farm_logic._on_side 的既有约定一致。"""
        for facing in ('LEFT', 'RIGHT'):
            z = fl.facing_half_zone(self.ZONE, self.BODY_X, facing)
            self.assertTrue(fl.point_in_zone((self.BODY_X, 630.0), z))


if __name__ == '__main__':
    unittest.main()


from types import SimpleNamespace


def _pbox(cx, cy, w=60, h=120):
    """player 框:按中心坐标构造(x/y 是左上角,与 Box 同形)。"""
    return SimpleNamespace(x=cx - w / 2, y=cy - h / 2, width=w, height=h)


class TestSelectPlayerBox(unittest.TestCase):
    """YOLO 关联门(spec §3.3):恰 1 个门内候选 → 接受;多个 → 身份新鲜才取最近;
    0 个/身份过期多候选 → None(宁可退级,不认错人)。"""

    def test_single_candidate_in_gate_accepted_even_if_identity_stale(self):
        # 恰 1 个在门内:接受,不看身份新鲜度(屏幕上只有一个玩家,几乎必是自己)
        box = _pbox(1200, 900)
        self.assertIs(fl.select_player_box([box], (1180, 880), False), box)

    def test_candidate_outside_gate_rejected(self):
        # 横向差 250 > 半宽 240 → 门外
        self.assertIsNone(fl.select_player_box(
            [_pbox(1450, 900)], (1200, 900), True))
        # 纵向差 130 > 半高 120 → 门外
        self.assertIsNone(fl.select_player_box(
            [_pbox(1200, 1030)], (1200, 900), True))

    def test_gate_boundary_inclusive(self):
        # 恰压门边算门内 —— 与 point_in_zone 的边界口径一致
        box = _pbox(1200 + fl.PLAYER_GATE_HALF_W, 900)
        self.assertIs(fl.select_player_box([box], (1200, 900), False), box)

    def test_multiple_fresh_identity_picks_nearest(self):
        near, far = _pbox(1180, 880), _pbox(1350, 900)
        self.assertIs(fl.select_player_box([far, near], (1200, 900), True), near)

    def test_multiple_nearest_breaks_horizontal_tie_by_y(self):
        # 横向同距、纵向不同(隔一层平台的路人):取合位移最近的那个
        same_floor, other_floor = _pbox(1240, 900), _pbox(1160, 1000)
        self.assertIs(fl.select_player_box(
            [other_floor, same_floor], (1200, 900), True), same_floor)

    def test_multiple_stale_identity_rejected(self):
        # 路人贴身且身份过期 → 拒绝,退给慢扫/cached,不认错人
        self.assertIsNone(fl.select_player_box(
            [_pbox(1180, 880), _pbox(1350, 900)], (1200, 900), False))

    def test_empty_players_rejected(self):
        self.assertIsNone(fl.select_player_box([], (1200, 900), True))

    def test_gate_player_boxes_returns_only_in_gate_as_list(self):
        # 决策日志 yolo候选= 记门内候选数,不是全屏数——全屏数混着门外路人,
        # 调关联门/查误认时会误导。返回列表(而非单个框),供 len() 计数
        inside, outside = _pbox(1240, 900), _pbox(1500, 900)
        self.assertEqual(fl.gate_player_boxes([inside, outside], (1200, 900)),
                         [inside])


class TestPlayerBoxCoordinateFrame(unittest.TestCase):
    """关联门的坐标系(2026-08-09 实测根因)。

    pred 来自 self._anchor,存的一直是**名字牌** y;YOLO 的 player 框中心却在
    身体上。实测 403 组「相邻拍、角色几乎没动」的 yolo↔名字牌配对:框中心比名字牌
    高 64px(p10 61 / p90 67,极稳)。两个坐标系不换算直接比,±120 的门实际变成
    「上 56px / 下 184px」——自己一跳(>56px)就被踢出门(丢锚),同时下一层平台
    的路人稳稳落在门内,成了唯一候选被无条件接受(认错人)。用户报的两个症状
    「玩家目标完全丢失」「识别到其他玩家身上」是同一个偏置的两面。"""

    def test_box_anchor_converts_box_center_to_nametag_frame(self):
        self.assertEqual(fl.player_box_anchor(_pbox(1200, 900)),
                         (1200, 900 + fl.PLAYER_BOX_TO_NAMETAG))

    def test_own_box_stays_in_gate_when_character_jumps_up(self):
        # 起跳:框中心跑到名字牌上方 180px(静止时本就高 64,再跳起 116)。
        # 换算后 dy=-116 在门内 —— 不换算是 180>120,自己的框被踢出门
        box = _pbox(1200, 900 - 180)
        self.assertIs(fl.select_player_box([box], (1200, 900), False), box)

    def test_lower_platform_stranger_is_out_of_gate(self):
        # 路人在下一层:框中心比我的名字牌还低 100px(= 比我的身体低 164px)。
        # 换算后 dy=164>120 出门 —— 不换算是 100<=120,它会成为唯一候选被接受
        self.assertIsNone(fl.select_player_box(
            [_pbox(1200, 1000)], (1200, 900), True))

    def test_nearest_is_measured_in_nametag_frame(self):
        # 两个候选:aligned 的框中心正好落在「我此刻应该在的身体高度」(名字牌上方
        # 64),offset 只是横向近一点。必须选 aligned —— 按框中心裸比会选 offset
        aligned = _pbox(1200, 900 - fl.PLAYER_BOX_TO_NAMETAG)
        offset = _pbox(1240, 900)
        self.assertIs(fl.select_player_box(
            [offset, aligned], (1200, 900), True), aligned)


class TestPlayerGateSize(unittest.TestCase):
    """位移合理性判据(spec §3.3):门随「距上次锚点观测的时长」放大,上限仍是
    PLAYER_GATE_HALF_W/H。固定 ±240 的门在 0.2s 的相邻拍上宽得离谱——角色 0.2s
    最多走 60px,门却容得下 240px 外的路人;自己那拍没被检出时,路人就是唯一候选。

    常数由 2026-08-09 实测定:关联距 p99 对 dt 线性拟合斜率 ~260px/s(取 300 放宽),
    dt<0.15s 的 max=174px 是击退冲量(基础半宽 110 覆盖);
    纵向相邻拍 |Δanchor_y| p50=2 / p99=62 / max=66(基础半高 70 覆盖)。"""

    def test_fresh_observation_gives_tight_gate(self):
        w, h = fl.player_gate_size(0.2)
        self.assertEqual(w, fl.PLAYER_GATE_BASE_W + fl.PLAYER_GATE_SPEED_X * 0.2)
        self.assertEqual(h, fl.PLAYER_GATE_BASE_H + fl.PLAYER_GATE_SPEED_Y * 0.2)
        self.assertLess(w, fl.PLAYER_GATE_HALF_W)

    def test_long_gap_saturates_at_fixed_gate(self):
        # 久未观测:退回固定上限,不许无限放大(放大到全屏 = 谁都能认成自己)
        self.assertEqual(fl.player_gate_size(5.0),
                         (fl.PLAYER_GATE_HALF_W, fl.PLAYER_GATE_HALF_H))

    def test_never_observed_uses_fixed_gate(self):
        # dt=None(从未命中过)→ 没有可信的时间基准,退回固定门
        self.assertEqual(fl.player_gate_size(None),
                         (fl.PLAYER_GATE_HALF_W, fl.PLAYER_GATE_HALF_H))

    def test_negative_dt_uses_fixed_gate(self):
        # 时钟回拨等异常:退回固定门,绝不产生比基础值还小的门
        self.assertEqual(fl.player_gate_size(-1.0),
                         (fl.PLAYER_GATE_HALF_W, fl.PLAYER_GATE_HALF_H))

    def test_stranger_200px_away_rejected_on_adjacent_beat(self):
        # 上一拍刚观测到(0.2s 前),路人在 200px 外:固定 ±240 的门会把它当成唯一
        # 候选无条件接受;位移门(110+300*0.2=170)把它挡在外面
        gw, gh = fl.player_gate_size(0.2)
        stranger = _pbox(1400, 900 - fl.PLAYER_BOX_TO_NAMETAG)
        self.assertIsNone(fl.select_player_box(
            [stranger], (1200, 900), False, gw, gh))

    def test_own_box_still_accepted_on_adjacent_beat(self):
        # 同一拍,自己走了 55px:必须照常接受(收紧不能把自己也关在门外)
        gw, gh = fl.player_gate_size(0.2)
        mine = _pbox(1255, 900 - fl.PLAYER_BOX_TO_NAMETAG)
        self.assertIs(fl.select_player_box(
            [mine], (1200, 900), False, gw, gh), mine)


class TestTemplateHitPlausible(unittest.TestCase):
    """模板分片命中的纵向合理性(spec §3.8,2026-08-09 实测棘轮漂移根因)。

    模板通道把自己上一拍的输出当作下一拍的搜索中心,却既不验名(命中的
    AnchorHit.text 是空串)、也没有任何合理性判据 —— 一次误匹配就会自我强化:
    匹配落在搜索窗**顶边**时,回推的锚点 y = (cy - half_h) + 0 + th/2,
    即每拍恒定上移 `half_h - th/2` = 80 - 36/2 = **62px**。日志逐拍实测正是
    -62、-62、-62……一路飘到 y=19(屏幕顶),再也回不来。

    真实纵向步长(只取 OCR 验名过的相邻拍,n=2164):p50=2 / p99=26 / p99.9=34,
    >40px 的只有 1 拍(0.05%)。45px 的帽子挡得住 62px 的棘轮,又几乎不误伤;
    真换平台时纵向位移更大,那一拍让给验名的 OCR 通道去重建,天经地义。"""

    def test_small_vertical_move_accepted(self):
        self.assertTrue(fl.template_hit_plausible(890, 887))

    def test_ratchet_step_rejected(self):
        # 实测棘轮步长 62px:必须挡下,否则下一拍窗口跟着上移,自我强化
        self.assertFalse(fl.template_hit_plausible(887 - 62, 887))

    def test_boundary_is_inclusive(self):
        self.assertTrue(fl.template_hit_plausible(887 - fl.TEMPLATE_MAX_DY, 887))
        self.assertFalse(fl.template_hit_plausible(887 - fl.TEMPLATE_MAX_DY - 1, 887))

    def test_downward_jump_rejected_too(self):
        # 方向无关:往下飘一样是不可信的纵向跳变
        self.assertFalse(fl.template_hit_plausible(887 + 62, 887))

    def test_no_previous_anchor_accepts(self):
        # 没有先验 y 就没有判据,不许凭空拒绝(冷启动/刚复位)
        self.assertTrue(fl.template_hit_plausible(500, None))


class TestForcedRescan(unittest.TestCase):
    """丢锚事件触发即时慢扫(spec §3.5):force 绕过常规节流,但自身限频 0.5s。"""

    def test_force_bypasses_regular_throttle(self):
        # 常规窗没到(0.6s < 2s),force 放行
        self.assertTrue(fl.should_rescan_anchor(100.6, 100.0, 2, force=True))

    def test_force_rate_limited_by_min_interval(self):
        # 距上次强制扫描 0.3s < 0.5s → 不放行(慢扫最坏 235ms,不许打满主循环)
        self.assertFalse(fl.should_rescan_anchor(
            100.6, 100.0, 2, force=True, last_forced=100.3))
        # 边界:恰好 0.5s → 放行(与 should_attack 同口径)
        self.assertTrue(fl.should_rescan_anchor(
            100.8, 100.0, 2, force=True, last_forced=100.3))

    def test_no_force_keeps_old_behavior(self):
        self.assertFalse(fl.should_rescan_anchor(101.0, 100.0, 2))
        self.assertTrue(fl.should_rescan_anchor(102.0, 100.0, 2))

    def test_regular_window_due_passes_even_when_forced_rate_limited(self):
        # 常规窗已到点:force 的限频不该反过来卡住常规扫描
        self.assertTrue(fl.should_rescan_anchor(
            102.0, 100.0, 2, force=True, last_forced=101.9))
