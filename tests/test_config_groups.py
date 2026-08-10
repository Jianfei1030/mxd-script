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


if __name__ == '__main__':
    unittest.main()
