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

    def setUp(self):
        # 每个用例独立:清掉折叠状态文件,避免用例间互相污染
        import os
        from ok.util.file import get_relative_path
        state_path = get_relative_path(Config.config_folder, 'config_groups_state.json')
        if os.path.exists(state_path):
            os.remove(state_path)

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

    def test_groups_initial_expanded(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        for group, widgets in card.group_widgets.items():
            for widget in widgets:
                self.assertFalse(widget.isHidden(), f'{group} 组初始应全部展开: {widget}')

    def test_group_collapse_toggles_widgets(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        card.group_header_by_group['攻击'].click()  # 折叠攻击组
        self.assertTrue(card.config_widget_by_key['攻击间隔(秒)'].isHidden())
        self.assertTrue(card.config_widget_by_key['攻击区宽(像素)'].isHidden())
        self.assertFalse(card.config_widget_by_key['喝血阈值'].isHidden(), '其他组不受影响')
        self.assertFalse(card.group_header_by_group['攻击'].isHidden(), '折叠后组标题仍可见(可再点展开)')
        card.group_header_by_group['攻击'].click()  # 再次点击展开
        self.assertFalse(card.config_widget_by_key['攻击间隔(秒)'].isHidden(), '再点应恢复展开')

    def test_collapse_independent_per_group(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        card.group_header_by_group['角色定位'].click()
        self.assertTrue(card.config_widget_by_key['角色名'].isHidden())
        self.assertFalse(card.config_widget_by_key['攻击间隔(秒)'].isHidden(), '攻击组未折叠')

    def test_search_overrides_collapse_then_restores(self):
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        card.group_header_by_group['攻击'].click()  # 折叠攻击组
        self.assertTrue(card.config_widget_by_key['攻击间隔(秒)'].isHidden())
        card.search_box.setText('攻击')  # 搜索:匹配优先,折叠忽略
        self.assertFalse(card.config_widget_by_key['攻击间隔(秒)'].isHidden(), '搜索中匹配组自动展开')
        card.search_box.clear()  # 清空:恢复折叠状态
        self.assertTrue(card.config_widget_by_key['攻击间隔(秒)'].isHidden(), '清空后恢复折叠')
        self.assertFalse(card.config_widget_by_key['喝血阈值'].isHidden())

    def test_collapse_state_persists_to_file(self):
        from ok.util.file import get_relative_path, read_json_file
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        card.group_header_by_group['攻击'].click()  # 折叠并持久化
        card.group_header_by_group['角色定位'].click()
        path = get_relative_path(Config.config_folder, 'config_groups_state.json')
        data = read_json_file(path)
        self.assertEqual(data['MapleFarmTask']['攻击'], True)
        self.assertEqual(data['MapleFarmTask']['角色定位'], True)
        # 重建卡片(同任务类名),折叠状态应从文件恢复
        card2 = self._make_card(task)
        self.assertTrue(card2.config_widget_by_key['攻击间隔(秒)'].isHidden(), '重建后攻击组应保持折叠')
        self.assertTrue(card2.config_widget_by_key['角色名'].isHidden(), '重建后角色定位组应保持折叠')
        self.assertFalse(card2.config_widget_by_key['喝血阈值'].isHidden(), '未折叠组不受影响')

    def test_collapse_persist_ignores_stale_group_names(self):
        """state 文件里存在但当前 CONFIG_GROUPS 没有的组名应被忽略(配置演进后残留)。"""
        import json
        from ok.util.file import get_relative_path
        path = get_relative_path(Config.config_folder, 'config_groups_state.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'MapleFarmTask': {'攻击': True, '不存在的组': True}}, f, ensure_ascii=False)
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        self.assertTrue(card.config_widget_by_key['攻击间隔(秒)'].isHidden())
        self.assertEqual(card.group_collapsed.get('不存在的组'), None, '残留组名不加载')

    def test_no_groups_task_does_not_write_state(self):
        from ok.util.file import get_relative_path, read_json_file
        task = self._make_task(with_groups=False)
        self._make_card(task)
        path = get_relative_path(Config.config_folder, 'config_groups_state.json')
        self.assertIsNone(read_json_file(path), '无分组任务不应创建折叠状态文件')

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
        card.search_box.clear()
        card.group_header_by_group['攻击'].click()
        card.group_header_by_group['角色定位'].click()
        for _ in range(10):
            self.app.processEvents()
        card.grab().save(str(out / 'card_groups_collapsed_20260810.png'))
        self.assertTrue((out / 'card_groups_all_20260810.png').exists())
        self.assertTrue((out / 'card_groups_filtered_20260810.png').exists())
        self.assertTrue((out / 'card_groups_collapsed_20260810.png').exists())

    def test_buff_list_widget_rendered_and_updates(self):
        """补BUFF列表 是 buff_list 控件(可添加配置区,非裸字符串文本框)。"""
        from ok.gui.tasks.LabelAndBuffList import LabelAndBuffList
        task = self._make_task(with_groups=True)
        card = self._make_card(task)
        widget = card.config_widget_by_key['补BUFF列表']
        self.assertIsInstance(widget, LabelAndBuffList, '补BUFF列表 应渲染为可添加列表控件')
        # 默认空列表 → 显示占位提示
        self.assertIn('Modify Buffs', widget.list_text.text())
        # 配置写入 list 后 update_value 反映新值
        widget.config['补BUFF列表'] = ['魔法盾=q:180']
        widget.update_value()
        self.assertIn('魔法盾=q:180', widget.list_text.text())

    def test_buff_add_dialog_value_format(self):
        """AddBuffDialog 三字段 → 列表元素字符串(与 parse_buff_config 互逆)。"""
        from PySide6.QtWidgets import QWidget
        from ok.gui.tasks.LabelAndBuffList import AddBuffDialog
        parent = QWidget()
        dlg = AddBuffDialog(parent)
        dlg.name_edit.setText('魔法盾')
        dlg.key_edit.setText('q')
        dlg.interval_spin.setValue(180)
        self.assertEqual(dlg.buff_value(), '魔法盾=q:180')
        # 间隔 1 秒是最小值,仍序列化
        dlg.interval_spin.setValue(1)
        self.assertEqual(dlg.buff_value(), '魔法盾=q:1')

    def test_buff_edit_dialog_prefills_fields(self):
        """AddBuffDialog 编辑模式:传 '名称=按键:间隔' 预填三字段。"""
        from PySide6.QtWidgets import QWidget
        from ok.gui.tasks.LabelAndBuffList import AddBuffDialog
        parent = QWidget()
        dlg = AddBuffDialog(parent, edit_value='魔法盾=q:180')
        self.assertEqual(dlg.name_edit.text(), '魔法盾')
        self.assertEqual(dlg.key_edit.text(), 'q')
        self.assertEqual(dlg.interval_spin.value(), 180)
        # 编辑后确认按钮可用(预填即校验通过)
        self.assertTrue(dlg.yesButton.isEnabled())
        # 无间隔的条目:间隔回退默认 180
        dlg2 = AddBuffDialog(parent, edit_value='狂暴=w')
        self.assertEqual(dlg2.name_edit.text(), '狂暴')
        self.assertEqual(dlg2.key_edit.text(), 'w')
        self.assertEqual(dlg2.interval_spin.value(), 180)

    def test_buff_list_edit_replaces_selected_item(self):
        """BuffListDialog 编辑:选中项替换为新值,位置不变。"""
        from unittest import mock
        from PySide6.QtWidgets import QWidget
        from ok.gui.tasks.LabelAndBuffList import BuffListDialog, AddBuffDialog
        parent = QWidget()
        dlg = BuffListDialog(['魔法盾=q:180', '狂暴=w:300'], parent)
        dlg.list_widget.setCurrentRow(0)
        # 编辑按钮存在且选中时可用
        self.assertTrue(dlg.edit_button.isEnabled())
        # 双击列表项应触发编辑(信号连接存在)
        self.assertIsNotNone(dlg.list_widget.itemDoubleClicked)
        # mock 模态对话框:edit_item → AddBuffDialog.exec 返回 True,取修改后的新值
        with mock.patch.object(AddBuffDialog, 'exec', return_value=True):
            with mock.patch.object(AddBuffDialog, 'buff_value', return_value='魔法盾=q:200'):
                dlg.edit_item()
        items = [dlg.list_widget.item(i).text() for i in range(dlg.list_widget.count())]
        self.assertEqual(items, ['魔法盾=q:200', '狂暴=w:300'])
        # 未选中时编辑不做事(不弹框、不崩溃)
        dlg.list_widget.setCurrentRow(-1)
        with mock.patch.object(AddBuffDialog, 'exec') as mocked:
            dlg.edit_item()
        mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
