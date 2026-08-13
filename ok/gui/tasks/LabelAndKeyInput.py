from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QMenu
from qfluentwidgets import PushButton

from ok.gui.Communicate import communicate
from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget

IDLE_PLACEHOLDER = '点击录制'
RECORDING_TEXT = '按下按键…'
RECORDING_STYLE = ('color: #009faa; font-weight: 600;'
                   'border: 2px solid #009faa; border-radius: 4px;')


class LabelAndKeyInput(ConfigLabelAndWidget):
    """点击即录的键位输入控件:点击进入录制态,按任意键写回规范键名,Esc 取消,右键清除。"""

    recorded = Signal(str)  # 录制成功写回后发射(供对话框等无 config 上下文复用)

    def __init__(self, config_desc, config, key: str):
        super().__init__(config_desc, config, key)
        self.button = PushButton()
        self.button.setMinimumWidth(120)
        self.button.clicked.connect(self.start_recording)
        self.button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.button.customContextMenuRequested.connect(self._show_context_menu)
        self.add_widget(self.button, stretch=0)
        self._recording = False
        self.update_value()

    def update_value(self):
        value = self.config.get(self.key) or ''
        self.button.setText(value or IDLE_PLACEHOLDER)

    def start_recording(self):
        if self._recording:
            return
        self._recording = True
        self.button.setText(RECORDING_TEXT)
        self.button.setStyleSheet(RECORDING_STYLE)
        self.grabKeyboard()
        communicate.hotkey_recording.emit(True)

    def keyPressEvent(self, event: QKeyEvent):
        if not self._recording:
            return super().keyPressEvent(event)
        if event.key() == Qt.Key_Escape:
            self._stop_recording()
            event.accept()
            return
        name = qt_key_to_pydirect_name(event)
        if name is None:
            event.accept()  # 不可映射,继续录制
            return
        self.update_config(name)
        self.recorded.emit(name)
        self._stop_recording()
        event.accept()

    def _stop_recording(self):
        self._recording = False
        self.releaseKeyboard()
        self.button.setStyleSheet('')
        self.update_value()
        communicate.hotkey_recording.emit(False)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        clear_action = menu.addAction('清除')
        action = menu.exec(self.button.mapToGlobal(pos))
        if action is clear_action:
            self._clear_value()

    def _clear_value(self):
        self.update_config('')
        self.update_value()


def qt_key_to_pydirect_name(event: QKeyEvent) -> str | None:
    """Qt 按键事件 → pydirectinput 规范键名;不可映射返回 None。

    小键盘数字键的 key() 与主键盘相同(Key_0..Key_9),统一映射为主键盘名——
    pydirectinput 无独立小键盘数字键名(见 spec [S3.1] 已知局限)。
    """
    key = event.key()
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key).lower()
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key)
    if Qt.Key_F1 <= key <= Qt.Key_F12:
        return f'f{key - Qt.Key_F1 + 1}'
    mapping = {
        Qt.Key_Left: 'left', Qt.Key_Right: 'right', Qt.Key_Up: 'up', Qt.Key_Down: 'down',
        Qt.Key_Home: 'home', Qt.Key_End: 'end', Qt.Key_PageUp: 'pageup', Qt.Key_PageDown: 'pagedown',
        Qt.Key_Insert: 'insert', Qt.Key_Delete: 'delete', Qt.Key_Backspace: 'backspace',
        Qt.Key_Space: 'space', Qt.Key_Return: 'enter', Qt.Key_Enter: 'enter', Qt.Key_Tab: 'tab',
        Qt.Key_Control: 'ctrl', Qt.Key_Alt: 'alt', Qt.Key_Shift: 'shift', Qt.Key_Meta: 'win',
        Qt.Key_CapsLock: 'capslock', Qt.Key_NumLock: 'numlock', Qt.Key_ScrollLock: 'scrolllock',
        Qt.Key_Pause: 'pause', Qt.Key_Print: 'printscreen', Qt.Key_Menu: 'apps',
    }
    return mapping.get(key)
