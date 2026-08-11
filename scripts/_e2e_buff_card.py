"""offscreen E2E:渲染「自动打怪」ConfigCard,验证补BUFF配置键出现在「挂机辅助」组,
且 补BUFF列表 是 buff_list 可添加控件(非裸字符串)。产出截图证据。
(agent 受限窗口站无法截图提权 GUI,交互类 E2E 走 offscreen grab + 断言,AGENTS.md §12)"""
import os
import sys
import tempfile

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon

from ok import og
from ok.gui.tasks.ConfigCard import ConfigCard
from ok.util.config import Config


class _FakeApp:
    def tr(self, message):
        return message


app = QApplication.instance() or QApplication([])
og.app = _FakeApp()
og.config = {}
Config.config_folder = tempfile.mkdtemp()

from types import SimpleNamespace
from src.task.MapleFarmTask import MapleFarmTask

task = MapleFarmTask(SimpleNamespace(scene=None), None)
task.config = Config('MapleFarmTask', task.default_config)

card = ConfigCard(task, task.name, task.config, task.description,
                  task.default_config, task.config_description,
                  task.config_type, task.icon or FluentIcon.INFO)

from ok.gui.tasks.LabelAndBuffList import LabelAndBuffList

assert hasattr(card, 'config_widget_by_key'), '卡片应渲染配置控件'
assert '补BUFF开关' in card.config_widget_by_key, '补BUFF开关 未渲染'
assert '补BUFF列表' in card.config_widget_by_key, '补BUFF列表 未渲染'
group_widgets = card.group_widgets.get('挂机辅助', [])
by_key = card.config_widget_by_key
assert by_key['补BUFF开关'] in group_widgets, '补BUFF开关 不在 挂机辅助 组'
assert by_key['补BUFF列表'] in group_widgets, '补BUFF列表 不在 挂机辅助 组'
assert isinstance(by_key['补BUFF列表'], LabelAndBuffList), '补BUFF列表 应为 buff_list 可添加控件'
# 填充示例条目后抓图:展示"添加配置区"形态(非空列表 + Modify Buffs 按钮)
by_key['补BUFF列表'].config['补BUFF列表'] = ['魔法盾=q:180', '狂暴=w:300']
by_key['补BUFF列表'].update_value()

out_dir = os.path.join('screenshots', 'e2e', 'buff_timer')
os.makedirs(out_dir, exist_ok=True)
card.setExpand(True)
for _ in range(30):
    app.processEvents()
img = card.grab().toImage()
p = os.path.join(out_dir, 'config_card_buff_list_20260812.png')
img.save(p)
print(f'OK: 补BUFF开关/补BUFF列表(可添加控件) 在「挂机辅助」组;截图 {p}')
