# 按键录制式输入（Key Input Recording）实施计划

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/key-input-recording.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GUI 中「游戏按键」全局配置与 BUFF 列表的键位输入从手打规范名改为「点击输入框 → 直接按键 → 自动映射」的录制式输入。

**Architecture:** 新建 `LabelAndKeyInput` 控件（Qt 控件级 `grabKeyboard()` + `keyPressEvent` 捕获），配合纯函数 `qt_key_to_pydirect_name` 把 Qt 键转成 pydirectinput 规范名写回配置；经 `ConfigItemFactory` 新类型 `key_input` 接入「游戏按键」全局配置，直接实例化接入 BUFF 对话框；录制期间通过 `communicate.hotkey_recording` 信号让 `StartCard` 临时卸载全局热键（F9 等 RegisterHotKey）防误触。

**Tech Stack:** Python 3.12 / PySide6 6.9.1 / qfluentwidgets 1.8.3 / pydirectinput 1.0.4 / unittest（offscreen QTest）

**Spec:** `docs/compose/specs/2026-08-13-key-input-recording-design.md`

---

### Task 1: 映射函数 qt_key_to_pydirect_name

**Covers:** [S3.1]

**Files:**
- Create: `ok/gui/tasks/LabelAndKeyInput.py`（本任务只含映射函数，控件类在 Task 2）
- Test: `tests/test_key_input.py`

- [ ] **Step 1: 写失败测试**（`tests/test_key_input.py`，import 会失败因为函数不存在）

```python
# tests/test_key_input.py
import os
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from ok.gui.tasks.LabelAndKeyInput import qt_key_to_pydirect_name


class QtKeyToPydirectNameTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
        self.assertEqual(self._name(Qt.Key_Apps), 'apps')

    def test_unknown_key_returns_none(self):
        self.assertIsNone(self._name(Qt.Key_F13))

    def _name(self, key):
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        return qt_key_to_pydirect_name(event)
```

- [ ] **Step 2: 跑测试确认失败**

```
& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_key_input -v
```
Expected: `ModuleNotFoundError: No module named 'ok.gui.tasks.LabelAndKeyInput'`

- [ ] **Step 3: 实现映射函数**（`ok/gui/tasks/LabelAndKeyInput.py`，仅函数）

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent


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
        Qt.Key_Pause: 'pause', Qt.Key_Print: 'printscreen', Qt.Key_Apps: 'apps',
    }
    return mapping.get(key)
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 13 个测试全 PASS

- [ ] **Step 5: Commit**（需用户确认；默认跳过，最后统一提交）

---

### Task 2: LabelAndKeyInput 控件

**Covers:** [S3]

**Files:**
- Modify: `ok/gui/tasks/LabelAndKeyInput.py`（追加控件类）
- Modify: `tests/test_key_input.py`（追加控件测试）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_key_input.py`）

```python
from ok.util.config import Config
from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


class LabelAndKeyInputTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_widget(self, value=''):
        config = Config('test_key_input', {'key': value})
        widget = LabelAndKeyInput(None, config, 'key')
        return widget, config

    def test_idle_shows_value_or_placeholder(self):
        widget, _ = self._make_widget('ctrl')
        self.assertEqual(widget.button.text(), 'ctrl')
        widget2, _ = self._make_widget('')
        self.assertIn('点击录制', widget2.button.text())

    def test_click_enters_recording_and_key_writes_config(self):
        widget, config = self._make_widget('')
        QTest.mouseClick(widget.button, Qt.MouseButton.LeftButton)
        self.assertTrue(widget._recording)
        self.assertIn('按下按键', widget.button.text())
        # 录制中按 PgDn → 写回 pagedown 并退出录制
        QTest.keyClick(widget, Qt.Key_PageDown)
        self.assertFalse(widget._recording)
        self.assertEqual(config.get('key'), 'pagedown')
        self.assertEqual(widget.button.text(), 'pagedown')

    def test_escape_cancels_without_write(self):
        widget, config = self._make_widget('ctrl')
        QTest.mouseClick(widget.button, Qt.MouseButton.LeftButton)
        QTest.keyClick(widget, Qt.Key_Escape)
        self.assertFalse(widget._recording)
        self.assertEqual(config.get('key'), 'ctrl')

    def test_unmappable_key_keeps_recording(self):
        widget, config = self._make_widget('')
        QTest.mouseClick(widget.button, Qt.MouseButton.LeftButton)
        QTest.keyClick(widget, Qt.Key_F13)
        self.assertTrue(widget._recording, '不可映射键应保持录制态')
        QTest.keyClick(widget, Qt.Key_A)
        self.assertEqual(config.get('key'), 'a')

    def test_context_menu_clear(self):
        widget, config = self._make_widget('home')
        # 直接调用菜单动作处理器(offscreen 无法 exec 菜单)
        from PySide6.QtCore import QPoint
        widget._clear_value()
        self.assertEqual(config.get('key'), '')
        self.assertIn('点击录制', widget.button.text())
```

- [ ] **Step 2: 跑测试确认失败**

Expected: `AttributeError: module 'ok.gui.tasks.LabelAndKeyInput' has no attribute 'LabelAndKeyInput'`

- [ ] **Step 3: 实现控件类**（追加到 `ok/gui/tasks/LabelAndKeyInput.py`）

```python
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QMenu
from qfluentwidgets import PushButton

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

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        clear_action = menu.addAction('清除')
        action = menu.exec(self.button.mapToGlobal(pos))
        if action is clear_action:
            self._clear_value()

    def _clear_value(self):
        self.update_config('')
        self.update_value()
```

注意：`grabKeyboard()`/`releaseKeyboard()` 在 `self` 上（保证 `keyPressEvent` 收到事件）；`ConfigLabelAndWidget` 的 `update_config(value)` 即 `self.config[self.key] = value`，与 `LabelAndLineEdit` 同构。

- [ ] **Step 4: 跑测试确认通过**

Expected: 全部 PASS（Task 1 + Task 2 共 18 用例）

- [ ] **Step 5: Commit**（需用户确认；默认跳过）

---

### Task 3: 「游戏按键」全局配置接入

**Covers:** [S4.1]

**Files:**
- Modify: `config.py:9-27`（key_config_option 加 config_type）
- Modify: `ok/gui/tasks/ConfigItemFactory.py:11,16-29,62-96`（key_input 分支）
- Test: `tests/test_key_input.py`（追加渲染测试）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_key_input.py`）

```python
from ok.gui.tasks.ConfigItemFactory import config_widget
from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput


class GameKeysConfigTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_key_config_option_marks_all_keys_key_input(self):
        from config import key_config_option
        self.assertIsNotNone(key_config_option.config_type)
        for key in key_config_option.default_config:
            self.assertEqual(key_config_option.config_type.get(key, {}).get('type'), 'key_input',
                             f'{key} 应标记为 key_input')

    def test_factory_returns_key_input_widget(self):
        from config import key_config_option
        config = Config('游戏按键', key_config_option.default_config)
        widget = config_widget(key_config_option.config_type, key_config_option.config_description,
                               config, '攻击键', 'ctrl', None)
        self.assertIsInstance(widget, LabelAndKeyInput)
```

- [ ] **Step 2: 跑测试确认失败**

Expected: `AssertionError`（config_type 为 None）

- [ ] **Step 3: 实现**

`config.py` — `key_config_option` 增加 `config_type` 参数（10 键位全部标 `key_input`）：

```python
_KEYS = ['攻击键', '副攻击键(可留空)', '血药键', '蓝药键', '回城卷键(可留空)', '拾取键',
         '宠物食物键(可留空)', '椅子键(可留空)', '群攻键(可留空)', '左移键', '右移键']

key_config_option = ConfigOption('游戏按键', {
    '攻击键': 'ctrl',
    '副攻击键(可留空)': '',
    '血药键': 'home',
    '蓝药键': 'insert',
    '回城卷键(可留空)': '',
    '拾取键': 'z',
    '宠物食物键(可留空)': '',
    '椅子键(可留空)': '',
    '群攻键(可留空)': '',
    '左移键': 'left',
    '右移键': 'right',
}, description='冒险岛游戏内按键,与游戏内键盘设置保持一致', config_description={
    '回城卷键(可留空)': '低血保命用。留空则低血时只停止任务不逃跑',
    '宠物食物键(可留空)': '喂宠物用。先在游戏内把宠物食物拖到快捷键,再填对应按键;留空则不喂',
    '椅子键(可留空)': '坐椅用(检测模式没怪时自动坐椅子回血蓝)。先在游戏内把椅子拖到快捷键,再填对应按键;留空则不坐',
    '群攻键(可留空)': '群攻(前后双向命中)技能键。接敌区内怪数达到「群攻怪数阈值」时改按它,那一拍不转向也不按单体攻击键。留空 = 功能关闭',
    '副攻击键(可留空)': '二连击的第二段攻击键(先按攻击键、立即接它)。需「二连击开关」开启且此处已绑定才生效:留空或开关未开,二连击均不启用',
}, config_type={k: {'type': 'key_input'} for k in _KEYS},
   show_at_tab=True, icon=FluentIcon.GAME)
```

`ok/gui/tasks/ConfigItemFactory.py` — import 与分支：

```python
from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput
```

`config_widget` 中 `if resolved_type:` 分支内新增：

```python
        elif resolved_type == 'key_input':
            return LabelAndKeyInput(config_desc, config, key)
```

- [ ] **Step 4: 跑测试确认通过**

Expected: 新增 2 用例 PASS

- [ ] **Step 5: 手动验证渲染**（offscreen 抓全局配置卡片确认 10 键渲染为 LabelAndKeyInput）

```
& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from PySide6.QtWidgets import QApplication; app=QApplication([]); from ok import og; from types import SimpleNamespace; og.app=SimpleNamespace(tr=lambda s: s); og.config={}; from ok.util.config import Config; from config import key_config_option; from ok.gui.settings.GlobalConfigCard import GlobalConfigCard; c=Config('游戏按键', key_config_option.default_config); card=GlobalConfigCard(c, key_config_option); print(len(card.config_widget_by_key), [type(w).__name__ for w in card.config_widget_by_key.values()])"
```
Expected: `['LabelAndKeyInput', ...]` × 10（顺序无要求，数量=10）

- [ ] **Step 6: Commit**（需用户确认；默认跳过）

---

### Task 4: BUFF 列表按键字段接入

**Covers:** [S4.2]

**Files:**
- Modify: `ok/gui/tasks/LabelAndBuffList.py:8-58`（AddBuffDialog）

- [ ] **Step 1: 改造 AddBuffDialog**（key_edit 替换为 LabelAndKeyInput）

`AddBuffDialog.__init__` 中替换：

```python
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText(self.tr('名称, 如 魔法盾'))
        self._key_config = Config('buff_key_temp', {'key': ''})
        self.key_input = LabelAndKeyInput(None, self._key_config, 'key')
        self.key_input.recorded.connect(lambda _name: self._validate())
        self.interval_spin = SpinBox(self)
```

`viewLayout` 追加顺序不变，但 `key_edit` 一行换成 `self.key_input`：

```python
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.name_edit)
        self.viewLayout.addWidget(self.key_input)
        self.viewLayout.addWidget(self.interval_spin)
```

`_validate` 与 `buff_value`、`_prefill` 中的 `key_edit` 引用全部替换：

```python
    def _prefill(self, edit_value):
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
```

文件头部 import 增加：

```python
from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput
from ok.util.config import Config
```

- [ ] **Step 2: 编译检查**

```
& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m py_compile ok/gui/tasks/LabelAndBuffList.py
```
Expected: 无输出（0 退出码）

- [ ] **Step 3: 手动验证**（offscreen 实例化 AddBuffDialog 不崩、确认键可录制）

```
& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from PySide6.QtWidgets import QApplication; app=QApplication([]); from ok.gui.tasks.LabelAndBuffList import AddBuffDialog, BuffListDialog; dlg=AddBuffDialog(); print(type(dlg.key_input).__name__)"
```
Expected: `LabelAndKeyInput`（构造不抛异常）

- [ ] **Step 4: Commit**（需用户确认；默认跳过）

---

### Task 5: 全局热键防冲突

**Covers:** [S5]

**Files:**
- Modify: `ok/gui/Communicate.py:31`（新增 hotkey_recording 信号）
- Modify: `ok/gui/start/StartCard.py:132-140`（拆分注册/注销方法 + 订阅信号）
- Modify: `ok/gui/tasks/LabelAndKeyInput.py`（录制起止发信号）

- [ ] **Step 1: Communicate 加信号**

`ok/gui/Communicate.py`，`global_config = Signal(str)` 后加：

```python
    hotkey_recording = Signal(bool)
```

- [ ] **Step 2: StartCard 拆分热键注册**

`ok/gui/start/StartCard.py` 的 `rebind_hotkey` 替换为：

```python
    VK_MAP = {'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B}

    def rebind_hotkey(self, hotkey):
        self._unregister_hotkey()
        if hotkey and hotkey != 'None' and hotkey in self.VK_MAP:
            self._register_hotkey(hotkey)

    def _register_hotkey(self, hotkey):
        vk = self.VK_MAP.get(hotkey)
        if vk and not windll.user32.RegisterHotKey(None, 999, 0, vk):
            logger.error(f"Failed to register hotkey {hotkey}")

    def _unregister_hotkey(self):
        windll.user32.UnregisterHotKey(None, 999)

    def on_hotkey_recording(self, recording):
        if recording:
            self._unregister_hotkey()
        else:
            self._register_hotkey(self.basic_options.get('Start/Stop'))
```

`__init__` 末尾（`communicate.window.connect(self.update_status)` 附近）加订阅：

```python
        communicate.hotkey_recording.connect(self.on_hotkey_recording)
```

- [ ] **Step 3: 控件发信号**

`ok/gui/tasks/LabelAndKeyInput.py` 顶部 import communicate：

```python
from ok.gui.Communicate import communicate
```

`start_recording` 末尾加：

```python
        communicate.hotkey_recording.emit(True)
```

`_stop_recording` 末尾加：

```python
        communicate.hotkey_recording.emit(False)
```

- [ ] **Step 4: 验证**（编译 + 全量相关单测）

```
& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m py_compile ok/gui/Communicate.py ok/gui/start/StartCard.py ok/gui/tasks/LabelAndKeyInput.py
& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_key_input -v
```
Expected: 编译无输出；测试全 PASS

- [ ] **Step 5: Commit**（需用户确认；默认跳过）

---

### Task 6: 全量验证

**Covers:** [S6]

**Files:**（无新增）

- [ ] **Step 1: 全量单测**

```
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo tests.test_config_groups tests.test_config_card_ui tests.test_dependency tests.test_dependency_ui tests.test_pydirect_extended tests.test_key_input
```
Expected: 全绿（既有 12 个 skip 保留）

- [ ] **Step 2: 全源码编译检查**

```
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 真实 GUI 启动冒烟**（ShellExecute runas 提权启动，见 AGENTS.md §1.3）

```
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class SHExec{[DllImport("shell32.dll", CharSet=CharSet.Unicode)]public static extern int ShellExecute(IntPtr hwnd, string op, string file, string args, string dir, int show);}'
[SHExec]::ShellExecute([IntPtr]::Zero, "runas", "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe", "main_debug.py", "G:\projects\MyDocs\projects\mxd_script", 1)
```
等 20s 后用 `Get-Process` 查 `MainWindowTitle` = `OK-MXD v0.1.0 开发工具` 且 `WorkingSet > 100MB` 确认存活；随后任务完成后停止该 GUI。

- [ ] **Step 4: 收尾**（可选）——更新 `AGENTS.md` §9/§10 提及按键输入方式变更；更新 `docs/configs/端侧大模型_战士_MapleFarmTask.json` 若键名格式受影响（本次不改配置格式，仅 UI 输入方式，通常无需动）。
