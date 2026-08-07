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
