# tests/test_key_input.py
"""按键录制式输入测试:qt_key_to_pydirect_name 映射 + LabelAndKeyInput 控件。

offscreen 渲染(QT_QPA_PLATFORM=offscreen),不依赖真实 GUI/游戏/网络(§11)。
"""
import os
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ok.gui.tasks.LabelAndKeyInput import qt_key_to_pydirect_name


class QtKeyToPydirectNameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _name(self, key):
        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        return qt_key_to_pydirect_name(event)

    def test_letters_lowercase(self):
        self.assertEqual(self._name(Qt.Key_A), 'a')
        self.assertEqual(self._name(Qt.Key_Z), 'z')

    def test_digits(self):
        self.assertEqual(self._name(Qt.Key_0), '0')
        self.assertEqual(self._name(Qt.Key_9), '9')

    def test_function_keys(self):
        self.assertEqual(self._name(Qt.Key_F1), 'f1')
        self.assertEqual(self._name(Qt.Key_F12), 'f12')

    def test_arrows(self):
        self.assertEqual(self._name(Qt.Key_Left), 'left')
        self.assertEqual(self._name(Qt.Key_Right), 'right')
        self.assertEqual(self._name(Qt.Key_Up), 'up')
        self.assertEqual(self._name(Qt.Key_Down), 'down')

    def test_extended_keys(self):
        self.assertEqual(self._name(Qt.Key_Home), 'home')
        self.assertEqual(self._name(Qt.Key_End), 'end')
        self.assertEqual(self._name(Qt.Key_PageUp), 'pageup')
        self.assertEqual(self._name(Qt.Key_PageDown), 'pagedown')
        self.assertEqual(self._name(Qt.Key_Insert), 'insert')
        self.assertEqual(self._name(Qt.Key_Delete), 'delete')

    def test_special_keys(self):
        self.assertEqual(self._name(Qt.Key_Space), 'space')
        self.assertEqual(self._name(Qt.Key_Return), 'enter')
        self.assertEqual(self._name(Qt.Key_Tab), 'tab')
        self.assertEqual(self._name(Qt.Key_Backspace), 'backspace')

    def test_modifiers(self):
        self.assertEqual(self._name(Qt.Key_Control), 'ctrl')
        self.assertEqual(self._name(Qt.Key_Alt), 'alt')
        self.assertEqual(self._name(Qt.Key_Shift), 'shift')
        self.assertEqual(self._name(Qt.Key_Meta), 'win')

    def test_lock_and_misc_keys(self):
        self.assertEqual(self._name(Qt.Key_CapsLock), 'capslock')
        self.assertEqual(self._name(Qt.Key_NumLock), 'numlock')
        self.assertEqual(self._name(Qt.Key_ScrollLock), 'scrolllock')
        self.assertEqual(self._name(Qt.Key_Pause), 'pause')
        self.assertEqual(self._name(Qt.Key_Print), 'printscreen')
        self.assertEqual(self._name(Qt.Key_Menu), 'apps')

    def test_unknown_key_returns_none(self):
        self.assertIsNone(self._name(Qt.Key_F13))


class LabelAndKeyInputTest(unittest.TestCase):

    _config_seq = 0

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from ok import og
        from ok.util.config import Config
        from types import SimpleNamespace
        og.app = SimpleNamespace(tr=lambda s: s)
        # Config 读写重定向到临时目录,不触碰真实 configs/(§11.4)
        Config.config_folder = tempfile.mkdtemp()

    def _make_widget(self, value=''):
        import tempfile
        from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput
        from ok.util.config import Config
        type(self)._config_seq += 1
        config = Config(f'test_key_input_{type(self)._config_seq}', {'key': value})
        widget = LabelAndKeyInput(None, config, 'key')
        return widget, config

    def test_idle_shows_value_or_placeholder(self):
        widget, _ = self._make_widget('ctrl')
        self.assertEqual(widget.button.text(), 'ctrl')
        widget2, _ = self._make_widget('')
        self.assertIn('点击录制', widget2.button.text())

    def test_click_enters_recording_and_key_writes_config(self):
        from PySide6.QtTest import QTest
        widget, config = self._make_widget('')
        QTest.mouseClick(widget.button, Qt.MouseButton.LeftButton)
        self.assertTrue(widget._recording)
        self.assertIn('按下按键', widget.button.text())
        QTest.keyClick(widget, Qt.Key_PageDown)
        self.assertFalse(widget._recording)
        self.assertEqual(config.get('key'), 'pagedown')
        self.assertEqual(widget.button.text(), 'pagedown')

    def test_escape_cancels_without_write(self):
        from PySide6.QtTest import QTest
        widget, config = self._make_widget('ctrl')
        QTest.mouseClick(widget.button, Qt.MouseButton.LeftButton)
        QTest.keyClick(widget, Qt.Key_Escape)
        self.assertFalse(widget._recording)
        self.assertEqual(config.get('key'), 'ctrl')

    def test_unmappable_key_keeps_recording(self):
        from PySide6.QtTest import QTest
        widget, config = self._make_widget('')
        QTest.mouseClick(widget.button, Qt.MouseButton.LeftButton)
        QTest.keyClick(widget, Qt.Key_F13)
        self.assertTrue(widget._recording, '不可映射键应保持录制态')
        QTest.keyClick(widget, Qt.Key_A)
        self.assertEqual(config.get('key'), 'a')

    def test_context_menu_clear(self):
        widget, config = self._make_widget('home')
        widget._clear_value()
        self.assertEqual(config.get('key'), '')
        self.assertIn('点击录制', widget.button.text())


class GameKeysConfigTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from ok import og
        from ok.util.config import Config
        from types import SimpleNamespace
        og.app = SimpleNamespace(tr=lambda s: s)
        # Config 读写重定向到临时目录,不触碰真实 configs/(§11.4)
        Config.config_folder = tempfile.mkdtemp()

    def test_key_config_option_marks_all_keys_key_input(self):
        from config import key_config_option
        self.assertIsNotNone(key_config_option.config_type)
        for key in key_config_option.default_config:
            self.assertEqual(key_config_option.config_type.get(key, {}).get('type'), 'key_input',
                             f'{key} 应标记为 key_input')

    def test_factory_returns_key_input_widget(self):
        from config import key_config_option
        from ok.gui.tasks.ConfigItemFactory import config_widget
        from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput
        from ok.util.config import Config
        config = Config('游戏按键', key_config_option.default_config)
        widget = config_widget(key_config_option.config_type, key_config_option.config_description,
                               config, '攻击键', 'ctrl', None)
        self.assertIsInstance(widget, LabelAndKeyInput)
