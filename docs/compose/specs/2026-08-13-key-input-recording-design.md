# 按键录制式输入（Key Input Recording）设计

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/key-input-recording.md)

日期：2026-08-13
状态：approved（用户 2026-08-13 确认）

## [S1] Problem

GUI 中所有键位设置（「游戏按键」全局配置 10 个键位 + BUFF 列表按键字段）目前都是纯文本
输入，用户需要手打 pydirectinput 风格规范键名（如 `pagedown`、`insert`、`ctrl`）。键盘上
只有缩写的键（PgDn、Ins、Ctrl）用户要查表才知道叫什么，体验差。

目标：改为「点击输入框 → 直接按键盘 → 自动映射为规范键名」的录制式输入。

## [S2] Solution overview

新建 `LabelAndKeyInput` 控件（Qt 控件级按键捕获，方案已确认），接入「游戏按键」全局配置与
BUFF 列表按键字段；录制期间临时卸载全局热键（F9 等）防误触。

已确认的需求边界（brainstorm 结论）：
- 范围：设置页「游戏按键」10 键位 + 补BUFF 列表按键字段
- 交互：点击即录；Esc 取消
- 仅键盘键，不支持鼠标
- 不保留手动输入（只能录制）
- 技术：Qt 控件级 `keyPressEvent` + `grabKeyboard()`（无全局监听副作用、QTest 可测）

## [S3] 核心组件 LabelAndKeyInput

新建 `ok/gui/tasks/LabelAndKeyInput.py`，继承 `ConfigLabelAndWidget`（与 `LabelAndLineEdit`
同构，`update_config(value)` 写回配置）。

状态机：
- `idle`：显示当前键名；空值显示占位文案「点击录制」
- 鼠标左键点击 → `recording`：显示「按下按键…」+ 高亮提示样式，`grabKeyboard()` 捕获键盘
- `recording` 中按任意键 → 经映射函数转规范名 → `update_config(name)` 写回 → 回 `idle`
- `recording` 中按 Esc → 取消，不写回，回 `idle`
- 不可映射的键 → 忽略，保持 `recording` 继续等待
- 右键菜单「清除」：清空该键位（供可留空键使用，如 副攻击键(可留空)）

键名规范：pydirectinput 风格小写（与 `ok/device/interaction_methods/keys.py`
`normalize_pydirect_key` 归一化口径一致）。录制得到的键名必须能被
`pydirectinput.KEYBOARD_MAPPING` 接受，保证发送链路可用。

### [S3.1] 映射函数 qt_key_to_pydirect_name

纯函数 `qt_key_to_pydirect_name(event: QKeyEvent) -> str | None`，放同文件（可离线单测）：

| Qt 键 | 输出规范名 |
|---|---|
| `Key_A`~`Key_Z` | `a`~`z`（统一小写） |
| `Key_0`~`Key_9` | `0`~`9` |
| `Key_F1`~`Key_F12` | `f1`~`f12` |
| `Key_Left/Right/Up/Down` | `left`/`right`/`up`/`down` |
| `Key_Home/End/PageUp/PageDown/Insert/Delete` | `home`/`end`/`pageup`/`pagedown`/`insert`/`delete` |
| `Key_Space/Return/Enter/Tab/Backspace` | `space`/`enter`/`tab`/`backspace` |
| `Key_Control/Alt/Shift/Meta` | `ctrl`/`alt`/`shift`/`win`（修饰键单按也记录） |
| `Key_CapsLock/NumLock/ScrollLock` | `capslock`/`numlock`/`scrolllock` |
| `Key_Pause/Print/Apps` | `pause`/`printscreen`/`apps` |
| 其他（含系统保留键） | `None`（忽略） |

已知局限：小键盘数字键录制后映射为主键盘同名（`0`~`9`），因 pydirectinput 无独立小键盘
数字键名；spec 记录此局限，不在本期解决。

## [S4] 接入点

### [S4.1] 「游戏按键」全局配置

- `config.py`：`key_config_option` 增加 `config_type` 参数，10 个键位全部标
  `{'type': 'key_input'}`（`ConfigOption` 已支持 `config_type` 参数，见
  `inference_config_option` 先例）
- `ok/gui/tasks/ConfigItemFactory.py`：`_resolve_type` 增加 `'key_input'` 分支 →
  `LabelAndKeyInput(config_desc, config, key)`
- 渲染路径 `GlobalConfigCard → ConfigCard → config_widget` 无需改动（已透传
  `config_type`）

### [S4.2] BUFF 列表按键字段

`ok/gui/tasks/LabelAndBuffList.py` 的 `AddBuffDialog`：`key_edit`（`LineEdit`）替换为
`LabelAndKeyInput`（对话框内点击即录）。注意 `AddBuffDialog` 是 `MessageBoxBase`，
`LabelAndKeyInput` 需以独立 widget 加入 `viewLayout`（不做成 `LabelAndWidget` 布局，
因为对话框内已有「按键」标签）。`_validate` 改为监听 `LabelAndKeyInput` 的值变化信号。

## [S5] 全局热键防冲突

F9 等全局热键经 Win32 `RegisterHotKey(None, 999, ...)` 注册（`ok/gui/start/StartCard.py`
`rebind_hotkey`），系统级热键在 Qt 控件收到按键事件之前就被拦截——录制时按 F9 既录不到
又会误触发 Start/Stop。

方案：
- `StartCard.py`：把 `rebind_hotkey` 拆出 `_register_hotkey(hotkey)` / `_unregister_hotkey()`
  两个方法（内部仍是 `windll.user32.RegisterHotKey/UnregisterHotKey`，id 固定 999）
- `LabelAndKeyInput`：录制开始/结束通过 `ok.gui.Communicate.communicate` 广播
  `hotkey_recording.emit(True/False)` 信号
- `StartCard`：订阅 `hotkey_recording` 信号，`True` 时 `_unregister_hotkey()`、
  `False` 时按当前 `Start/Stop` 配置 `_register_hotkey()` 恢复

## [S6] 测试

- 新增 `tests/test_key_input.py`：
  - `qt_key_to_pydirect_name` 映射全覆盖（字母/数字/F 键/方向/扩展/修饰/符号键，
    未知键 → `None`），`QTest.keyClick` 构造事件离线可跑
  - 控件 offscreen 测试：点击进入录制态、按键写入配置、Esc 取消不写回、右键清除、
    空值占位文案
- 全量单测 + 全源码编译检查全绿（§11.6 命令）
- E2E：真实 GUI 启动无崩溃；交互类 E2E 走 offscreen grab + 断言（agent 受限窗口站
  无法截图提权 GUI，参照 §12 先例）

## [S7] 范围外（YAGNI）

- 不保留手动输入（用户确认只能录制）
- 不支持鼠标键（用户确认仅键盘键）
- 不改非键位 LineEdit（角色名等照旧）
- 小键盘数字键独立映射（见 [S3.1] 局限，不在本期解决）
