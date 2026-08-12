# tests/test_dependency_ui.py
"""LabelAndDependencyCheck offscreen 渲染测试(不依赖真实 GUI/窗口站,§11.3 自动化兜底)。"""
import os
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication

from ok import og


class _FakeApp:
    """代替 og.app,只提供 tr()(LabelAndWidget 渲染链只用到它)。"""

    def tr(self, message):
        return message


class DependencyCheckUiTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        og.app = _FakeApp()
        og.config = {}

    def _make(self):
        from ok.gui.tasks.LabelAndDependencyCheck import LabelAndDependencyCheck
        return LabelAndDependencyCheck({}, {}, '依赖状态')

    def test_shows_installed_and_missing_text(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', side_effect=lambda m: m == 'openvino'):
            widget = self._make()
        text = widget.status_label.text()
        self.assertIn('✓ 已安装', text)
        self.assertIn('✗ 未安装', text)
        self.assertIn('OpenVINO', text)

    def test_install_button_enabled_only_when_missing(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            widget = self._make()
        self.assertFalse(widget.install_button.isEnabled(), '全齐时安装按钮应禁用')
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget.refresh()
        self.assertTrue(widget.install_button.isEnabled(), '有缺失时安装按钮应可用')

    def test_refresh_updates_status(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            widget = self._make()
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget.refresh()
        self.assertNotIn('✓ 已安装', widget.status_label.text())
        self.assertIn('✗ 未安装', widget.status_label.text())

    def test_install_done_success_resets_and_alerts(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        with mock.patch.object(dep_mod, '_installed', return_value=True), \
                mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_info') as info, \
                mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_error') as err:
            widget._on_install_done(True, '清华')
        self.assertFalse(widget._installing)
        self.assertFalse(widget.install_button.isEnabled(), '装完后状态刷新为全齐 → 按钮禁用')
        self.assertEqual(widget.install_button.text(), '安装缺失依赖')
        info.assert_called_once()
        err.assert_not_called()
        self.assertIn('重启后生效', info.call_args[0][0])

    def test_install_done_failure_reports_error(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        with mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_info') as info, \
                mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_error') as err:
            widget._on_install_done(False, 'connection refused')
        self.assertFalse(widget._installing)
        err.assert_called_once()
        self.assertIn('connection refused', err.call_args[0][0])
        info.assert_not_called()

    def test_start_install_noop_when_nothing_missing(self):
        import src.dependency as dep_mod
        import ok.gui.tasks.LabelAndDependencyCheck as widget_mod
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            widget = self._make()
        # 全齐时 _start_install 必须提前返回:不建线程、不调 install_missing、_installing 保持 False
        with mock.patch.object(dep_mod, '_installed', return_value=True), \
                mock.patch.object(widget_mod, 'install_missing') as install, \
                mock.patch.object(widget_mod.threading, 'Thread') as thread:
            widget._start_install()
        install.assert_not_called()
        thread.assert_not_called()
        self.assertFalse(widget._installing)

    def test_start_install_runs_worker_thread(self):
        import src.dependency as dep_mod
        import ok.gui.tasks.LabelAndDependencyCheck as widget_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        # Thread 被 mock → worker 不执行:install_missing 不能被同步调用(真起线程会跑真实 pip 安装),
        # 断言的是「创建了 worker 线程 + 进入安装中状态」
        with mock.patch.object(dep_mod, '_installed', return_value=False), \
                mock.patch.object(widget_mod, 'install_missing') as install, \
                mock.patch.object(widget_mod.threading, 'Thread') as thread:
            widget._start_install()
        install.assert_not_called()
        thread.assert_called_once()
        self.assertTrue(widget._installing)
        self.assertFalse(widget.install_button.isEnabled())

    def test_grab_render_screenshot(self):
        # §11.3 E2E 截图留证:渲染图存 screenshots/e2e/inference_dependency/
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        widget.resize(640, 160)
        out_dir = os.path.join('screenshots', 'e2e', 'inference_dependency')
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, 'dependency_check.png')
        widget.grab().save(path)
        self.assertTrue(os.path.exists(path), f'渲染图应已保存: {path}')


if __name__ == '__main__':
    unittest.main()
