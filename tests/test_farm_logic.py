import unittest

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


if __name__ == '__main__':
    unittest.main()
