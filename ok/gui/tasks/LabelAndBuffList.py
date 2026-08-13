from qfluentwidgets import BodyLabel, FluentIcon, LineEdit, MessageBoxBase, PushButton, SpinBox, SubtitleLabel, ListWidget
from PySide6.QtCore import Qt

from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget
from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput
from src.task import farm_logic


class AddBuffDialog(MessageBoxBase):
    """添加/编辑一个 BUFF:名称 + 按键(点击即录) + 间隔秒 三字段表单。
    确认后经 accepted_buff 信号传出 (name, key, interval)。
    edit_value 非空 = 编辑模式,预填三字段(parse_buff_config 的逆)。"""

    def __init__(self, parent=None, edit_value=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(self.tr('Add Buff'), self)
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText(self.tr('名称, 如 魔法盾'))
        self._key_config = {'key': ''}
        self.key_input = LabelAndKeyInput(None, self._key_config, 'key')
        self.key_input.recorded.connect(lambda _name: self._validate())
        self.interval_spin = SpinBox(self)
        self.interval_spin.setRange(1, 86400)
        self.interval_spin.setValue(180)
        self.interval_spin.setSuffix(self.tr(' 秒'))

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.name_edit)
        self.viewLayout.addWidget(self.key_input)
        self.viewLayout.addWidget(self.interval_spin)

        self.yesButton.setText(self.tr('Confirm'))
        self.cancelButton.setText(self.tr('Cancel'))
        self.yesButton.setDisabled(True)
        self.name_edit.textChanged.connect(self._validate)
        if edit_value:
            self.titleLabel.setText(self.tr('Edit Buff'))
            self._prefill(edit_value)
        self.widget.setMinimumWidth(360)

    def _prefill(self, edit_value):
        """从 '名称=按键[:间隔]' 预填表单;间隔缺省/非法用默认 180。"""
        parsed = farm_logic.parse_buff_config([edit_value])
        if parsed:
            name, key, interval = parsed[0]
            self.name_edit.setText(name)
            self._key_config['key'] = key
            self.key_input.update_value()
            if interval is not None:
                self.interval_spin.setValue(interval)
        self._validate()

    def _validate(self):
        self.yesButton.setEnabled(bool(self.name_edit.text().strip()
                                       and (self._key_config.get('key') or '').strip()))

    def buff_value(self):
        name = self.name_edit.text().strip()
        key = (self._key_config.get('key') or '').strip()
        return farm_logic.buff_entry_to_text(name, key, self.interval_spin.value())


class BuffListDialog(MessageBoxBase):
    """BUFF 列表编辑对话框:现有条目列表 + 添加/删除/上移/下移。"""

    def __init__(self, items, parent):
        super().__init__(parent)
        self.original_items = list(items)
        self.list_widget = ListWidget()
        self.list_widget.addItems(self.original_items)

        self.move_up_button = PushButton(FluentIcon.UP, self.tr('Move Up'))
        self.move_up_button.clicked.connect(self.move_up)
        self.move_down_button = PushButton(FluentIcon.DOWN, self.tr('Move Down'))
        self.move_down_button.clicked.connect(self.move_down)
        self.add_button = PushButton(FluentIcon.ADD, self.tr('Add Buff'))
        self.add_button.clicked.connect(self.add_buff)
        self.edit_button = PushButton(FluentIcon.EDIT, self.tr('Edit'))
        self.edit_button.clicked.connect(self.edit_item)
        self.remove_button = PushButton(FluentIcon.REMOVE, self.tr('Remove'))
        self.remove_button.clicked.connect(self.remove_item)
        self.list_widget.itemSelectionChanged.connect(self.update_list_actions)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.edit_item())

        self.yesButton.setText(self.tr('Confirm'))
        self.cancelButton.setText(self.tr('Cancel'))
        self.yesButton.clicked.connect(self.confirm)
        self.cancelButton.clicked.connect(self.cancel)

        self.viewLayout.addWidget(self.list_widget)

        self._add_button_row()
        self.widget.setMinimumHeight(420)
        self.widget.setMinimumWidth(460)
        self.update_list_actions()

    def _add_button_row(self):
        from PySide6.QtWidgets import QHBoxLayout
        row = QHBoxLayout()
        row.addWidget(self.move_up_button)
        row.addWidget(self.move_down_button)
        row.addWidget(self.add_button)
        row.addWidget(self.edit_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        self.viewLayout.addLayout(row)

    def update_list_actions(self):
        row = self.list_widget.currentRow()
        has_selection = row >= 0
        self.move_up_button.setEnabled(has_selection and row > 0)
        self.move_down_button.setEnabled(has_selection and row < self.list_widget.count() - 1)
        self.edit_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)

    def move_up(self):
        row = self.list_widget.currentRow()
        if row >= 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)

    def move_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)

    def add_buff(self):
        dlg = AddBuffDialog(self.window())
        if dlg.exec():
            self.list_widget.addItem(dlg.buff_value())
            self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def edit_item(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        current = self.list_widget.item(row).text()
        dlg = AddBuffDialog(self.window(), edit_value=current)
        if dlg.exec():
            self.list_widget.takeItem(row)
            self.list_widget.insertItem(row, dlg.buff_value())
            self.list_widget.setCurrentRow(row)

    def remove_item(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.list_widget.takeItem(row)
            self.update_list_actions()

    def confirm(self):
        self._result = [self.list_widget.item(i).text()
                        for i in range(self.list_widget.count())]
        self.accept()

    def cancel(self):
        self._result = self.original_items
        self.reject()

    def result_list(self):
        return getattr(self, '_result', self.original_items)


class LabelAndBuffList(ConfigLabelAndWidget):
    """BUFF 列表配置控件:显示当前条目,点按钮弹编辑对话框(添加 = 三字段表单)。
    配置值为 list,元素 '名称=按键:间隔秒'(与 farm_logic.parse_buff_config 兼容)。"""

    def __init__(self, config_desc, config, key: str):
        super().__init__(config_desc, config, key)
        self.switch_button = PushButton(FluentIcon.ADD, self.tr('Modify Buffs'))
        self.switch_button.clicked.connect(self.clicked)
        self.list_text = BodyLabel("")
        self.update_value()
        self.add_widget(self.list_text, stretch=1)
        self.add_widget(self.switch_button, stretch=0)

    def update_value(self):
        items = self.config.get(self.key) or []
        self.list_text.setText('、'.join(str(i) for i in items) if items else self.tr('(空, 点 Modify Buffs 添加)'))

    def clicked(self):
        items = self.config.get(self.key) or []
        dlg = BuffListDialog(items, self.window())
        dlg.exec()
        self.update_config(dlg.result_list())
        self.update_value()
