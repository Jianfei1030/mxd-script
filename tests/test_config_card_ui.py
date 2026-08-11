# tests/test_config_card_ui.py
"""ConfigCard 分组+搜索的 offscreen 渲染测试(不依赖真实 GUI/窗口站)。

§11.3 E2E 的自动化兜底:agent 受限窗口站无法截图提权 GUI,改用
QT_QPA_PLATFORM=offscreen 渲染真实 ConfigCard + 真实 MapleFarmTask 元数据,
断言分组标题/搜索框/过滤行为,并用 grab() 输出渲染图作为截图证据。
"""
import os
import tempfile
import time
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication

from ok import og
from ok.util.config import Config


class _FakeApp:
    """代替 og.app,只提供 tr()(ConfigCard 渲染链只用到它与 og.config)。"""

    def tr(self, message):
        return message


class ConfigCardUiTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        og.app = _FakeApp()
        og.config = {}
        # Config 读写重定向到临时目录,不触碰真实 configs/(§11.1 禁止污染运行时配置)
        Config.config_folder = tempfile.mkdtemp()

    def _make_task(self, with_groups):
        from types import SimpleNamespace
        from src.task.MapleFarmTask import MapleFarmTask
        # 假 executor 只提供 scene(构造链 ExecutorOperation.__init__ 需要 executor.scene)
        task = MapleFarmTask(SimpleNamespace(scene=None), None)
        # 手动构造 config,不调 after_init:on_create 会 prewarm OCR 模型(重型依赖,§11.4)
        task.config = Config('MapleFarmTask', task.default_config)
        if not with_groups:
            del task.config_groups
        return task

    def _make_card(self, task):
        from qfluentwidgets import FluentIcon
        from ok.gui.tasks.ConfigCard import ConfigCard
        return ConfigCard(task, task.name, task.config, task.description,
                          task.default_config, task.config_description,
                          task.config_type, task.icon or FluentIcon.INFO)

    def test_maple_farm_card_has_search_box_and_9_group_headers(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        self.assertTrue(hasattr(card, 'search_box'), '有分组的卡片应创建搜索框')
        self.assertEqual(len(card.group_headers), 9, '应有 9 个组标题')
        self.assertEqual(len(card.group_header_by_group), 9)

    def test_search_filters_widgets_and_headers(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        card.search_box.setText('椅子')
        # 键级过滤:键名/描述含「椅子」的项保留(坐椅开关描述「自动坐椅子…拖到快捷键」),其余隐藏
        self.assertFalse(card.config_widget_by_key['坐椅开关'].isHidden())
        self.assertTrue(card.config_widget_by_key['攻击间隔(秒)'].isHidden())
        self.assertTrue(card.config_widget_by_key['角色名'].isHidden())
        # 组标题过滤:挂机辅助组有可见键 → 保留;攻击/角色定位组无匹配 → 隐藏
        self.assertFalse(card.group_header_by_group['挂机辅助'].isHidden())
        self.assertTrue(card.group_header_by_group['攻击'].isHidden())
        self.assertTrue(card.group_header_by_group['角色定位'].isHidden())

    def test_search_matches_description_too(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        # 「阈值」出现在多个键名/描述里(喝血阈值、喝蓝阈值、模板匹配阈值……)
        card.search_box.setText('阈值')
        visible = [k for k, w in card.config_widget_by_key.items() if not w.isHidden()]
        self.assertTrue(any('阈值' in k for k in visible), f'应至少命中一个含「阈值」的键,实际可见: {visible}')
        self.assertTrue(any('阈值' not in k for k in visible), '描述命中也应保留(如 模板匹配阈值 相关项)')

    def test_clear_search_restores_all(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        card.search_box.setText('喝药')
        card.search_box.clear()
        for widget in card.config_widgets:
            self.assertFalse(widget.isHidden(), f'清空后 {widget} 应恢复显示')
        for header in card.group_headers:
            self.assertFalse(header.isHidden(), f'清空后组标题 {header} 应恢复显示')

    def test_task_without_groups_has_no_search_box(self):
        task = self._make_task(with_groups=False)
        card = self._make_card(task)
        self.assertFalse(hasattr(card, 'search_box'), '无分组的任务不应创建搜索框')
        self.assertEqual(len(card.group_headers), 0, '无分组的任务不应有组标题')

    def test_render_grab_screenshots(self):
        """offscreen 渲染抓图,作为 E2E 截图证据归档(§11.3/§11.5)。"""
        import pathlib
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        out = pathlib.Path('screenshots/e2e/config_groups')
        out.mkdir(parents=True, exist_ok=True)
        card.setExpand(True)
        for _ in range(30):  # 跑完 qfluentwidgets 展开动画
            self.app.processEvents()
            time.sleep(0.01)
        card.grab().save(str(out / 'card_groups_all_20260810.png'))
        card.search_box.setText('锚点')
        for _ in range(10):
            self.app.processEvents()
        card.grab().save(str(out / 'card_groups_filtered_20260810.png'))
        self.assertTrue((out / 'card_groups_all_20260810.png').exists())
        self.assertTrue((out / 'card_groups_filtered_20260810.png').exists())


if __name__ == '__main__':
    unittest.main()
