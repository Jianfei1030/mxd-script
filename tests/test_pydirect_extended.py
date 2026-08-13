import ctypes
import unittest
from unittest import mock

import pydirectinput

from ok.device.interaction_methods import pydirect


class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", ctypes.c_byte * 28)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]


def _capture_sendinput():
    """替换 pydirectinput.SendInput 为记录型 fake,返回 (list, restore)。"""
    sent = []

    def fake(n, p, s):
        inp = ctypes.cast(p, ctypes.POINTER(Input)).contents
        ki = inp.ii.ki
        sent.append((inp.type, ki.wVk, ki.wScan, ki.dwFlags))
        return n

    original = pydirectinput.SendInput
    pydirectinput.SendInput = fake
    return sent, lambda: setattr(pydirectinput, 'SendInput', original)


class TestSendExtendedKey(unittest.TestCase):
    """pydirectinput 扩展键 bug 修复验证(官方 Issue #26):
    KEYBOARD_MAPPING 中扩展键编码为 `扫描码|0x80 + 0x400`,直接发该值游戏收不到。
    修复:扫描码取 `& 0x7F`,并设 KEYEVENTF_EXTENDEDKEY 标志。
    """

    def setUp(self):
        self.sent, self.restore = _capture_sendinput()

    def tearDown(self):
        self.restore()

    def test_pagedown_sends_valid_scancode_with_extended_flag(self):
        handled = pydirect.send_extended_key('pagedown')
        self.assertTrue(handled)
        self.assertEqual(len(self.sent), 1)
        typ, wVk, wScan, flags = self.sent[0]
        self.assertEqual(typ, 1)  # INPUT_KEYBOARD
        self.assertEqual(wScan, 0x51, 'PageDown 标准 PS/2 扫描码应为 0x51')
        self.assertEqual(flags, 0x0009, '应含 SCANCODE|EXTENDEDKEY')  # 0x8 | 0x1

    def test_pagedown_keyup_sets_keyup_flag(self):
        pydirect.send_extended_key('pagedown', key_up=True)
        typ, wVk, wScan, flags = self.sent[0]
        self.assertEqual(flags, 0x000B, 'keyup 应为 SCANCODE|EXTENDEDKEY|KEYUP')  # 0x8 | 0x1 | 0x2

    def test_all_extended_keys_valid_scancodes(self):
        # 这些键在 pydirectinput 中均为 `x|0x80 + 0x400` 编码,直接发送无效
        for key, expected_scan in [('pageup', 0x49), ('pagedown', 0x51), ('insert', 0x52),
                                   ('home', 0x47), ('end', 0x4F), ('del', 0x53), ('delete', 0x53)]:
            self.sent.clear()
            handled = pydirect.send_extended_key(key)
            self.assertTrue(handled, f'{key} 应被扩展键路径处理')
            self.assertEqual(self.sent[0][2], expected_scan, f'{key} 扫描码错误')
            self.assertEqual(self.sent[0][3], 0x0009, f'{key} 应含 EXTENDEDKEY')

    def test_normal_letter_keys_not_handled(self):
        # 普通字母键扫描码本就正确,不应走扩展键路径
        handled = pydirect.send_extended_key('u')
        self.assertFalse(handled)
        self.assertEqual(len(self.sent), 0)

    def test_unknown_key_not_handled(self):
        handled = pydirect.send_extended_key('__not_a_key__')
        self.assertFalse(handled)
        self.assertEqual(len(self.sent), 0)


class TestPyDirectInteractionSendKey(unittest.TestCase):
    """PyDirectInteraction.send_key 对扩展键走修复路径,普通键走 pydirectinput。"""

    def _make_interaction(self):
        capture = mock.MagicMock()
        capture.width, capture.height = 2560, 1440
        hwnd = mock.MagicMock()
        hwnd.is_foreground.return_value = True
        return pydirect.PyDirectInteraction(capture, hwnd)

    def test_send_key_pagedown_uses_extended_path(self):
        sent, restore = _capture_sendinput()
        try:
            with mock.patch.object(pydirectinput, 'keyDown') as kd, \
                    mock.patch.object(pydirectinput, 'keyUp') as ku, \
                    mock.patch('time.sleep'):
                interaction = self._make_interaction()
                interaction.send_key('pagedown')
            kd.assert_not_called()
            ku.assert_not_called()
            self.assertEqual(len(sent), 2)  # down + up
            self.assertEqual(sent[0][2], 0x51)
            self.assertEqual(sent[0][3], 0x0009)
            self.assertEqual(sent[1][3], 0x000B)
        finally:
            restore()

    def test_send_key_normal_key_uses_pydirectinput(self):
        sent, restore = _capture_sendinput()
        try:
            with mock.patch.object(pydirectinput, 'keyDown') as kd, \
                    mock.patch.object(pydirectinput, 'keyUp') as ku, \
                    mock.patch('time.sleep'):
                interaction = self._make_interaction()
                interaction.send_key('u')
            kd.assert_called_once_with('u')
            ku.assert_called_once_with('u')
            self.assertEqual(len(sent), 0)  # 未走扩展键路径
        finally:
            restore()


if __name__ == '__main__':
    unittest.main()
