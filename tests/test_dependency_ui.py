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
        # offscreen 平台不枚举系统字体,中文会渲染成豆腐块;显式注册系统中文字体文件
        # (路径由 WINDIR 环境变量推导,缺失则跳过,截图内容尽力而为)
        import os
        from PySide6.QtGui import QFont, QFontDatabase
        windir = os.environ.get('WINDIR')
        if windir:
            font_id = QFontDatabase.addApplicationFont(os.path.join(windir, 'Fonts', 'msyh.ttc'))
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    widget.setFont(QFont(families[0]))
        widget.resize(640, 160)
        out_dir = os.path.join('screenshots', 'e2e', 'inference_dependency')
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, 'dependency_check.png')
        widget.grab().save(path)
        self.assertTrue(os.path.exists(path), f'渲染图应已保存: {path}')

    def test_global_config_card_update_config_and_reset_do_not_crash(self):
        # 回归:LabelAndDependencyCheck 缺 update_value 时,GlobalConfigCard 的
        # Reset Config(reset_clicked → update_config)对每个 widget 调 update_value() 会抛
        # AttributeError(ConfigCard.py:457-460)。渲染真实卡片 + update_config + reset 均不应崩。
        import tempfile
        from ok.util.config import Config
        from config import inference_config_option
        from ok.gui.settings.GlobalConfigCard import GlobalConfigCard
        Config.config_folder = tempfile.mkdtemp()
        config = Config('推理加速', inference_config_option.default_config)
        card = GlobalConfigCard(config, inference_config_option)
        card.update_config()  # 缺 update_value 时这里抛 AttributeError
        card.reset_clicked()  # reset_to_default + update_config,也不应抛
        self.assertEqual(config.get('启用GPU推理'), inference_config_option.default_config['启用GPU推理'],
                         'reset 后配置回到默认值')

    def test_gpu_switch_has_restart_hook_and_triggers_restart_when_cpu_model(self):
        # 「启用GPU推理」开关必须挂 on_check(勾选→检查模型后端→CPU 则自动重启)
        import tempfile
        from ok.util.config import Config
        from config import inference_config_option
        from ok.gui.settings.GlobalConfigCard import GlobalConfigCard
        from ok.gui.tasks.LabelAndSwitchButton import LabelAndSwitchButton
        from src.globals import should_restart_for_gpu
        Config.config_folder = tempfile.mkdtemp()
        config = Config('推理加速', inference_config_option.default_config)
        card = GlobalConfigCard(config, inference_config_option)
        switch = card.config_widget_by_key.get('启用GPU推理')
        self.assertIsInstance(switch, LabelAndSwitchButton, '「启用GPU推理」应渲染为开关控件')
        self.assertTrue(callable(switch.on_check), '开关必须挂 on_check 回调(勾选时检查是否需要重启)')
        # 决策纯函数语义:模型已 CPU 创建 + 勾选 → 重启;模型未创建 → 不重启
        self.assertTrue(should_restart_for_gpu(True, 'cpu'))
        self.assertFalse(should_restart_for_gpu(True, None))
        self.assertFalse(should_restart_for_gpu(True, 'dml'))


if __name__ == '__main__':
    unittest.main()
