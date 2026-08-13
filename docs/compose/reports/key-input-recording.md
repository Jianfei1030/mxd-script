---
feature: key-input-recording
status: delivered
specs:
  - docs/compose/specs/2026-08-13-key-input-recording-design.md
plans:
  - docs/compose/plans/2026-08-13-key-input-recording.md
branch: master
commits: none (uncommitted, 待用户确认后提交)
---

# 按键录制式输入（Key Input Recording）— Final Report

## What Was Built

GUI 中所有键位设置（「游戏按键」全局配置 11 个键位 + 补BUFF 列表按键字段）从「手打
pydirectinput 规范键名」改为「点击输入框 → 直接按键盘 → 自动映射为规范键名」的录制式
输入。用户不再需要知道 `pagedown`/`insert`/`ctrl` 这类缩写键的标准写法——点一下、按一下、
完成。

## Architecture

**核心控件 `LabelAndKeyInput`**（`ok/gui/tasks/LabelAndKeyInput.py`，继承
`ConfigLabelAndWidget`，与 `LabelAndLineEdit` 同构）：
- 状态机：`idle`（显示当前键名，空值显示「点击录制」占位）→ 点击 → `recording`
  （显示「按下按键…」+ 高亮样式，`grabKeyboard()` 捕获）→ 按键写回 → `idle`；Esc 取消；
  不可映射键忽略继续录制；右键菜单「清除」清空键位（供可留空键使用）
- 映射纯函数 `qt_key_to_pydirect_name(QKeyEvent) -> str | None`：字母（统一小写）、数字、
  F1-F12、方向键、Home/End/PgUp/PgDn/Insert/Delete、Space/Enter/Tab/Backspace、
  修饰键单按（Ctrl/Alt/Shift/Win）、CapsLock/NumLock/ScrollLock/Pause/PrintScreen/Apps；
  输出均为 pydirectinput 规范名（与 `keys.py` 归一化口径一致），保证发送链路可用
- 小键盘数字键映射为主键盘同名（pydirectinput 无独立小键盘数字键名，已知局限）

**接入点**：
- `config.py`：`key_config_option` 增加 `config_type`，11 键位标 `{'type': 'key_input'}`
- `ok/gui/tasks/ConfigItemFactory.py`：`_resolve_type` 新增 `key_input` 分支 → `LabelAndKeyInput`
- `ok/gui/tasks/LabelAndBuffList.py`：`AddBuffDialog` 的 `key_edit`（LineEdit）替换为
  `LabelAndKeyInput`，键值存于对话框内部 `_key_config = {'key': ''}`（普通 dict，不产生
  磁盘配置文件），`recorded` 信号驱动表单校验

**全局热键防冲突**：F9 等热键走 Win32 `RegisterHotKey`（系统级），录制时按 F9 既录不到
又会误触发 Start/Stop。方案：
- `ok/gui/Communicate.py`：新增 `hotkey_recording = Signal(bool)`
- `ok/gui/start/StartCard.py`：`rebind_hotkey` 拆分为 `_register_hotkey`/`_unregister_hotkey`
  （VK_MAP 提为类常量），订阅 `hotkey_recording`：录制开始卸载热键、结束按当前配置恢复
- `LabelAndKeyInput`：`start_recording`/`_stop_recording` 广播信号

### Design Decisions

- **Qt 控件级录制而非 pynput/全局钩子**：录制交互保证焦点必在输入框上，`grabKeyboard` +
  `keyPressEvent` 必然收到按键；无全局副作用（录制不吞其他窗口按键）、无线程、QTest 可测。
  唯一需要处理的是系统级 RegisterHotKey——通过信号临时卸载恢复。
- **不保留手动输入**：用户明确要求只能录制（界面最简），Esc 取消 + 右键清除覆盖取消/清空需求。
- **键值容器用普通 dict 而非 Config**：AddBuffDialog 每次打开若构造 Config 会读写
  `configs/` 产生垃圾文件；dict 满足 `get`/`__setitem__` 接口即可。

## Usage

- **「游戏按键」全局配置**（设置页）：每个键位点击即进入「按下按键…」状态，按任意键立即
  写入规范键名；Esc 取消；右键「清除」清空（可留空键）。
- **补BUFF 列表**：「Modify Buffs」→ 添加/编辑 BUFF → 按键字段同样点击即录。
- 录制时 F9 等全局热键自动临时失效，录制结束恢复（防误触发 Start/Stop）。
- 配置存储格式不变（`'pagedown'`、`'ctrl'` 等小写规范名），老配置与任务执行逻辑零改动。

## Verification

- `tests/test_key_input.py`：16 用例全绿——映射表全覆盖（字母/数字/F 键/方向/扩展键/修饰/
  符号/未知键 None）+ 控件 offscreen 测试（点击进录制、按键写配置、Esc 取消不写回、
  不可映射键保持录制、右键清除、空值占位）+ 「游戏按键」config_type 标记与工厂分派
- `tests/test_config_card_ui.py`：2 个 AddBuffDialog 用例更新为 `_key_config` API
- 全量单测：664 通过（12 skip 为基线既有）
- 全源码编译检查：OK
- 真实 GUI 冒烟：提权重启 `main_debug.py` 无崩溃（PID 80492，374MB，Responding）
- offscreen 渲染验证：「游戏按键」卡片 11 个键位全部渲染为 `LabelAndKeyInput`

## Journey Log

- [lesson] PySide6 枚举成员不在 `dir(Qt)` 中列出；`Qt.Key_Apps` 不存在，上下文菜单键的正确枚举是 `Qt.Key_Menu`（输出名仍为 pydirectinput 的 `apps`）
- [lesson] `Config` 构造会读写 `configs/` 且同名文件在用例间互相污染——测试必须重定向 `Config.config_folder` 到临时目录并使用唯一文件名（§11.4）
- [pivot] `AddBuffDialog` 键值容器从 `Config` 改为普通 dict——`Config` 每次打开对话框都会写磁盘配置文件，dict 满足控件接口且零副作用
- [lesson] qfluentwidgets `MessageBoxBase` 无 parent 构造会崩（`MaskDialogBase` 取 `parent.width()`），offscreen 验证须传 parent

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/specs/2026-08-13-key-input-recording-design.md` | 设计 | 已标记 NOTE |
| `docs/compose/plans/2026-08-13-key-input-recording.md` | 实施计划 | 已标记 NOTE |
| `ok/gui/tasks/LabelAndKeyInput.py` | 核心控件 + 映射函数 | 新建 |
| `tests/test_key_input.py` | 映射 + 控件 + 接入测试 | 新建 |
| `config.py` | 游戏按键 config_type | 修改 |
| `ok/gui/tasks/ConfigItemFactory.py` | key_input 分支 | 修改 |
| `ok/gui/tasks/LabelAndBuffList.py` | AddBuffDialog 接入 | 修改 |
| `ok/gui/Communicate.py` | hotkey_recording 信号 | 修改 |
| `ok/gui/start/StartCard.py` | 热键拆分 + 订阅 | 修改 |
| `tests/test_config_card_ui.py` | 2 用例同步新 API | 修改 |
