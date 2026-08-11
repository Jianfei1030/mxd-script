# tests/test_config_groups.py
import unittest

from src.task import config_groups


class TestConfigGroupsPure(unittest.TestCase):

    def test_group_of(self):
        groups = [('攻击', ['攻击间隔(秒)']), ('保命与药水', ['喝血阈值'])]
        self.assertEqual(config_groups.group_of('攻击间隔(秒)', groups), '攻击')
        self.assertIsNone(config_groups.group_of('不存在的键', groups))

    def test_should_insert_header(self):
        self.assertTrue(config_groups.should_insert_header(None, '攻击'))
        self.assertTrue(config_groups.should_insert_header('攻击', '拾取'))
        self.assertFalse(config_groups.should_insert_header('攻击', '攻击'))
        self.assertFalse(config_groups.should_insert_header('攻击', None))

    def test_matches_empty_query(self):
        self.assertTrue(config_groups.matches('', '攻击间隔(秒)', '说明'))
        self.assertTrue(config_groups.matches('   ', '攻击间隔(秒)', '说明'))

    def test_matches_key_substring(self):
        self.assertTrue(config_groups.matches('攻击', '攻击间隔(秒)', '说明'))
        self.assertFalse(config_groups.matches('喝药', '攻击间隔(秒)', '说明'))

    def test_matches_description(self):
        self.assertTrue(config_groups.matches('阈值', '喝药判定间隔(秒)', 'HP 低于阈值时判效'))
        self.assertTrue(config_groups.matches('hp', '喝药判定间隔(秒)', 'HP 低于阈值时判效'))
        self.assertFalse(config_groups.matches('xyz', '喝药判定间隔(秒)', 'HP 低于阈值时判效'))

    def test_visible_keys_and_groups(self):
        descriptions = {'攻击间隔(秒)': '攻击节奏', '喝血阈值': 'HP 阈值', '朝向': '方向'}
        keys = list(descriptions)
        self.assertEqual(config_groups.visible_keys('阈值', keys, descriptions), {'喝血阈值'})
        groups = [('攻击', ['攻击间隔(秒)']), ('保命与药水', ['喝血阈值']), ('走位与朝向', ['朝向'])]
        self.assertEqual(config_groups.visible_groups('阈值', groups, keys, descriptions), ['保命与药水'])
        self.assertEqual(config_groups.visible_groups('', groups, keys, descriptions),
                         ['攻击', '保命与药水', '走位与朝向'])


from src.task.MapleFarmTask import CONFIG_GROUPS, DEFAULT_CONFIG


class TestMapleFarmConfigGroups(unittest.TestCase):

    def test_all_default_config_keys_covered_exactly_once(self):
        seen = []
        for group, keys in CONFIG_GROUPS:
            for key in keys:
                self.assertIn(key, DEFAULT_CONFIG, f'{group} 含未知键: {key}')
                seen.append(key)
        self.assertEqual(len(seen), len(set(seen)), '同一键出现在多个组')
        self.assertEqual(set(seen), set(DEFAULT_CONFIG.keys()), f'有键未分组: {set(DEFAULT_CONFIG) - set(seen)}')

    def test_group_names_unique(self):
        names = [g for g, _ in CONFIG_GROUPS]
        self.assertEqual(len(names), len(set(names)))

    def test_group_order_visible_groups_keeps_definition_order(self):
        # 组显示顺序 = CONFIG_GROUPS 定义顺序(角色定位组包含搜索区/模板/身份/玩家框等识别类键)
        groups = [g for g, _ in CONFIG_GROUPS]
        self.assertEqual(groups, ['攻击', '拾取', '保命与药水', '走位与朝向', '寻怪', '角色定位',
                                  '战斗细节', '挂机辅助', '调试'])


if __name__ == '__main__':
    unittest.main()
