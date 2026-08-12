import sys
import unittest
from unittest import mock

import src.dependency as dep_mod
from src.dependency import (
    DEPENDENCIES, MIRRORS, build_install_cmd, check_dependencies,
    install_missing, missing_dependencies,
)


class TestCheckDependencies(unittest.TestCase):

    def test_all_installed(self):
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            result = check_dependencies()
        self.assertEqual(len(result), 2)
        self.assertTrue(all(d['installed'] for d in result))

    def test_partial_missing(self):
        with mock.patch.object(dep_mod, '_installed', side_effect=lambda m: m == 'openvino'):
            result = check_dependencies()
        self.assertTrue(result[0]['installed'])
        self.assertFalse(result[1]['installed'])

    def test_all_missing(self):
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            self.assertEqual(len(missing_dependencies()), 2)

    def test_missing_only_uninstalled(self):
        with mock.patch.object(dep_mod, '_installed', side_effect=lambda m: m == 'onnxruntime'):
            missing = missing_dependencies()
        self.assertEqual([d['name'] for d in missing], ['openvino'])

    def test_entries_pin_versions_from_requirements(self):
        by_name = {d['name']: d for d in DEPENDENCIES}
        self.assertEqual(by_name['openvino']['version'], '2026.2.1')
        self.assertEqual(by_name['onnxruntime']['pip'], 'onnxruntime-directml')
        self.assertEqual(by_name['onnxruntime']['version'], '1.24.4')
        self.assertTrue(by_name['openvino']['required'])
        self.assertFalse(by_name['onnxruntime']['required'])


class TestBuildInstallCmd(unittest.TestCase):

    def test_with_mirror(self):
        cmd = build_install_cmd([DEPENDENCIES[0]], 'https://mirror.example/simple')
        self.assertEqual(cmd[:2], [sys.executable, '-m'])
        self.assertEqual(cmd[2:4], ['pip', 'install'])
        self.assertIn('openvino==2026.2.1', cmd)
        self.assertEqual(cmd[-2:], ['-i', 'https://mirror.example/simple'])

    def test_without_mirror_uses_official(self):
        cmd = build_install_cmd(DEPENDENCIES, None)
        self.assertNotIn('-i', cmd)
        self.assertIn('onnxruntime-directml==1.24.4', cmd)


class TestInstallMissing(unittest.TestCase):

    def test_no_missing_is_noop(self):
        with mock.patch.object(dep_mod, 'missing_dependencies', return_value=[]):
            ok, detail = install_missing()
        self.assertTrue(ok)

    def test_tries_mirrors_in_order_until_success(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            mirror = cmd[cmd.index('-i') + 1] if '-i' in cmd else None
            if mirror == MIRRORS[1]:
                return mock.Mock(returncode=0, stderr='')
            return mock.Mock(returncode=1, stderr='boom')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertTrue(ok)
        self.assertEqual(detail, MIRRORS[1])
        self.assertEqual(len(calls), 2, '第二个镜像成功后应立即停止,不应继续尝试')

    def test_all_fail_returns_last_error(self):
        def fake_run(cmd, **kwargs):
            tag = cmd[cmd.index('-i') + 1] if '-i' in cmd else 'official'
            return mock.Mock(returncode=1, stderr=f'fail-{tag}')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertFalse(ok)
        self.assertIn('fail-official', detail, '应返回最后一个(官方源)错误')

    def test_exception_keeps_trying_next_mirror(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if len(calls) == 1:
                raise TimeoutError('too slow')
            return mock.Mock(returncode=0, stderr='')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)

    def test_exception_all_mirrors_returns_error(self):
        def fake_run(cmd, **kwargs):
            raise TimeoutError('too slow')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertFalse(ok)
        self.assertIn('too slow', detail)

    def test_mirror_order_tuna_first(self):
        self.assertEqual(MIRRORS[0], 'https://pypi.tuna.tsinghua.edu.cn/simple')


if __name__ == '__main__':
    unittest.main()
