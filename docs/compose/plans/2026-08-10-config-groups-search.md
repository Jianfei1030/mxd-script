# 自动打怪卡片配置项分组+搜索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给「实时触发」tab 的「自动打怪」任务卡片展开区加功能分组 + 关键字搜索，纯 UI 层修改，不触碰任何任务执行/配置读写逻辑。

**Architecture:** 分组元数据 `CONFIG_GROUPS` 作为模块级常量定义在 `src/task/MapleFarmTask.py`（与 `DEFAULT_CONFIG` 同风格）；搜索匹配/分组判定写成纯函数放新模块 `src/task/config_groups.py`（离线可单测）；`ok/gui/tasks/ConfigCard.py`（`TaskCard` 的父类，仅被任务卡片使用）消费二者：有 `task.config_groups` 时渲染组标题分隔条 + 展开区顶部搜索框，无则行为与现在逐字节一致。匹配逻辑（`matches`/`visible_keys`/`visible_groups`）全部下沉为纯函数，UI 只做装配，符合 AGENTS.md §11.2「纯逻辑必须单测」。

**Tech Stack:** Python 3.12、PySide6 6.9.1（qfluentwidgets ExpandSettingCard）、unittest。

## Global Constraints

- 运行环境：Python 3.12 `C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe`（本机无 .venv-warrior）
- 禁止 hard code 本地绝对路径（AGENTS.md §11.1），路径一律 `os.path.dirname(...)` 推导
- 任何新增/修改的纯逻辑必须带 unittest（§11.2）；全量单测 + py_compile 必须通过才能算完成（§11.6）
- 数据缺失的测试显式 skip（§11.4），不允许 assert 假失败
- 无 `config_groups` 的任务卡片渲染行为必须与修改前完全一致（不破坏其他任务/框架行为）
- 不改动任何任务执行、配置读写、按键/检测逻辑——本次修改仅限 UI 展示层
- `ok/` 是第三方框架目录：可修改但必须向后兼容（新功能全部走可选属性/空检查）

---

### Task 1: config_groups 纯函数模块

**Covers:** 搜索匹配与分组判定逻辑（用户需求核心：宽松匹配、按功能分组）

**Files:**
- Create: `src/task/config_groups.py`
- Test: `tests/test_config_groups.py`

**Interfaces:**
- Consumes: 无（纯标准库）
- Produces:
  - `group_of(key: str, groups: list[tuple[str, list[str]]]) -> str | None` — key 所属组名，未分组返回 None
  - `should_insert_header(prev_group: str | None, current_group: str | None) -> bool` — 渲染到 current_group 的键时是否需先插组标题
  - `matches(query: str, key: str, description: str) -> bool` — 宽松匹配：空/纯空白 query 全匹配；否则键名或描述包含 query（忽略大小写、首尾空白）
  - `visible_keys(query: str, keys: list[str], descriptions: dict) -> set[str]` — query 下应显示的键集合
  - `visible_groups(query: str, groups, keys: list[str], descriptions: dict) -> list[str]` — 应显示的组名列表（保持 groups 顺序；组内任一键可见即可见）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config_groups.py
import unittest

from src.task import config_groups


class TestConfigGroupsPure(unittest.TestCase):

    def test_group_of(self):
        groups = [('攻击', ['攻击间隔(秒)']), ('保命与药水', ['喝血阈值'])]
        self.assertEqual(config_groups.group_of('攻击间隔(秒)', groups), '攻击')
        self.assertIsNone(config_groups.group_of('不存在的键', groups))

    def test_should_insert_header(self):
        self.assertTrue(config_groups.should_insert_header(None, '攻击'))
        self.assertTrue(config_groups.should_insert_header('攻击', '拾取'))
        self.assertFalse(config_groups.should_insert_header('攻击', '攻击'))
        self.assertFalse(config_groups.should_insert_header('攻击', None))

    def test_matches_empty_query(self):
        self.assertTrue(config_groups.matches('', '攻击间隔(秒)', '说明'))
        self.assertTrue(config_groups.matches('   ', '攻击间隔(秒)', '说明'))

    def test_matches_key_substring(self):
        self.assertTrue(config_groups.matches('攻击', '攻击间隔(秒)', '说明'))
        self.assertFalse(config_groups.matches('喝药', '攻击间隔(秒)', '说明'))

    def test_matches_description(self):
        self.assertTrue(config_groups.matches('阈值', '喝药判定间隔(秒)', 'HP 低于阈值时判效'))
        self.assertTrue(config_groups.matches('hp', '喝药判定间隔(秒)', 'HP 低于阈值时判效'))
        self.assertFalse(config_groups.matches('xyz', '喝药判定间隔(秒)', 'HP 低于阈值时判效'))

    def test_visible_keys_and_groups(self):
        descriptions = {'攻击间隔(秒)': '攻击节奏', '喝血阈值': 'HP 阈值', '朝向': '方向'}
        keys = list(descriptions)
        self.assertEqual(config_groups.visible_keys('阈值', keys, descriptions), {'喝血阈值'})
        groups = [('攻击', ['攻击间隔(秒)']), ('保命与药水', ['喝血阈值']), ('走位与朝向', ['朝向'])]
        self.assertEqual(config_groups.visible_groups('阈值', groups, keys, descriptions), ['保命与药水'])
        self.assertEqual(config_groups.visible_groups('', groups, keys, descriptions),
                         ['攻击', '保命与药水', '走位与朝向'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups`
Expected: `ModuleNotFoundError: No module named 'src.task.config_groups'`

- [ ] **Step 3: 写最小实现**

```python
# src/task/config_groups.py
"""自动打怪卡片展开区配置项的 分组/搜索 纯函数(UI 展示用,不改任何任务逻辑)。"""


def group_of(key, groups):
    """key 所属的组名;未分组返回 None。groups 形如 [(组名, [键, ...]), ...]。"""
    for group, keys in groups:
        if key in keys:
            return group
    return None


def should_insert_header(prev_group, current_group):
    """渲染到 current_group 的键时,是否需要先插入该组的标题分隔条。"""
    return current_group is not None and current_group != prev_group


def matches(query, key, description):
    """宽松匹配:空/纯空白 query 全匹配;否则键名或描述包含 query(忽略大小写)。"""
    q = (query or '').strip().lower()
    if not q:
        return True
    return q in key.lower() or q in (description or '').lower()


def visible_keys(query, keys, descriptions):
    """query 下应显示的键集合(未匹配的键隐藏)。"""
    return {k for k in keys if matches(query, k, descriptions.get(k, ''))}


def visible_groups(query, groups, keys, descriptions):
    """query 下应显示的组名列表(保持 groups 顺序);组内任一键可见即可见。"""
    visible = visible_keys(query, keys, descriptions)
    return [g for g, g_keys in groups if any(k in visible for k in g_keys)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups`
Expected: `Ran 7 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add src/task/config_groups.py tests/test_config_groups.py
git commit -m "feat: 新增配置项分组/搜索纯函数模块 config_groups"
```

---

### Task 2: MapleFarmTask 分组元数据

**Covers:** 62 个配置键按功能分 9 组（攻击/拾取/保命与药水/走位与朝向/寻怪/角色定位/战斗细节/挂机辅助/调试）

**Files:**
- Modify: `src/task/MapleFarmTask.py`（模块常量区，紧邻 `DEFAULT_CONFIG` 之后；`__init__` 加一行 `self.config_groups = CONFIG_GROUPS`）
- Test: `tests/test_config_groups.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `group_of`
- Produces: `MapleFarmTask.CONFIG_GROUPS: list[tuple[str, list[str]]]` 模块级常量；`MapleFarmTask.config_groups` 实例属性（ConfigCard 通过 `task.config_groups` 读取）

- [ ] **Step 1: 写失败测试（追加到 tests/test_config_groups.py）**

```python
from src.task.MapleFarmTask import CONFIG_GROUPS, DEFAULT_CONFIG


class TestMapleFarmConfigGroups(unittest.TestCase):

    def test_all_default_config_keys_covered_exactly_once(self):
        seen = []
        for group, keys in CONFIG_GROUPS:
            for key in keys:
                self.assertIn(key, DEFAULT_CONFIG, f'{group} 含未知键: {key}')
                seen.append(key)
        self.assertEqual(len(seen), len(set(seen)), '同一键出现在多个组')
        self.assertEqual(set(seen), set(DEFAULT_CONFIG.keys()), f'有键未分组: {set(DEFAULT_CONFIG) - set(seen)}')

    def test_group_names_unique(self):
        names = [g for g, _ in CONFIG_GROUPS]
        self.assertEqual(len(names), len(set(names)))

    def test_group_order_visible_groups_keeps_definition_order(self):
        # 组显示顺序 = CONFIG_GROUPS 定义顺序(角色定位组包含搜索区/模板/身份/玩家框等识别类键)
        groups = [g for g, _ in CONFIG_GROUPS]
        self.assertEqual(groups, ['攻击', '拾取', '保命与药水', '走位与朝向', '寻怪', '角色定位',
                                  '战斗细节', '挂机辅助', '调试'])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups`
Expected: `ImportError: cannot import name 'CONFIG_GROUPS' from 'src.task.MapleFarmTask'`

- [ ] **Step 3: 实现——在 DEFAULT_CONFIG 定义之后追加常量**

```python
# 自动打怪卡片展开区配置项的功能分组(UI 展示用;顺序 = 组显示顺序,组内键可任意排)
CONFIG_GROUPS = [
    ('攻击', ['攻击间隔(秒)', '攻击模式', '攻击区形状', '攻击区宽(像素)', '攻击区高(像素)', '丢怪保持(秒)']),
    ('拾取', ['拾取开关', '拾取间隔(秒)']),
    ('保命与药水', ['喝血阈值', '喝蓝阈值', '保命血线', '死亡判定线', '死亡确认帧数', '喝药无效上限',
                   '喝药判定间隔(秒)', '喝药开关', '药水检查间隔(秒)', '药水耗尽保护', '画面静止上限(秒)']),
    ('走位与朝向', ['走位开关', '走位持续时间(秒)', '走位间隔(秒)', '朝向']),
    ('寻怪', ['寻怪开关', '寻怪同层容差(像素)', '寻怪刷新间隔(秒)', '空闲刷新间隔(秒)',
             '寻怪起步宽限(秒)', '寻怪保持(秒)']),
    ('角色定位', ['角色名', '名字牌到身体偏移(像素)', '锚点搜索区宽(比例)', '锚点搜索区高(比例)',
                '锚点搜索区中心Y(比例)', '锚点刷新间隔(秒)', '锚点保鲜(秒)', '寻怪外推速度(像素/秒)',
                '玩家宽(像素)', '玩家高(像素)', '模板分片匹配开关', '模板匹配阈值', 'YOLO角色定位开关',
                '身份保鲜(秒)', '身份复验开关', '身份复验间隔(秒)', '丢锚立即重扫开关']),
    ('战斗细节', ['转向冷却(秒)', '受击防抖(秒)', '硬直抑制窗(秒)', '朝向纠正开关', '朝向观测开关']),
    ('挂机辅助', ['喂宠物开关', '喂宠物间隔(秒)', '坐椅开关', '坐椅延迟(秒)', '经验停滞上限(分钟)']),
    ('调试', ['决策日志开关', '显示玩家框', '显示攻击区', '显示名字搜索范围', '显示寻怪同层带', '显示怪物框']),
]
```

在 `__init__` 中（`self.default_config.update(DEFAULT_CONFIG)` 附近）加：

```python
        self.config_groups = CONFIG_GROUPS
```

- [ ] **Step 4: 跑测试确认通过**

Run: `& "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups`
Expected: `Ran 10 tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_config_groups.py
git commit -m "feat: 自动打怪 62 个配置键按功能分 9 组(config_groups 元数据)"
```

---

### Task 3: ConfigCard 分组标题渲染

**Covers:** 展开区按组显示标题分隔条；无 `config_groups` 的任务零变化

**Files:**
- Modify: `ok/gui/tasks/ConfigCard.py`

**Interfaces:**
- Consumes: `task.config_groups`（Task 2）；Task 1 的 `group_of`/`should_insert_header`
- Produces: 组标题 QLabel 列表 `self.group_headers`、映射 `self.group_header_by_group: dict[str, QLabel]`、`self._last_config_group`、`self.search_box`（Task 4 用）

- [ ] **Step 1: 手动验证现状（对照组）**

Run: 展开「自动打怪」卡片，确认当前 62 项平铺无分组；展开其他任务卡片（如一次性任务）记录现状。
Expected: 平铺、无标题、无搜索框。

- [ ] **Step 2: 修改 `_init_config_content` 加状态字段**

```python
    def _init_config_content(self, task, config, default_config, config_description, config_type):
        self.config = config
        self.config_widgets = []
        self.config_widget_by_key = {}
        self.config_keys = []
        self.group_headers = []                 # 组标题 QLabel 列表(搜索过滤时显隐)
        self.group_header_by_group = {}         # 组名 → 组标题 QLabel
        self._last_config_group = None          # 渲染中的当前组名
        self.default_config = default_config
        self.config_description = config_description
        self.config_type = config_type
        self.sub_configs_rules = {}
        self.sub_configs_controlled_keys = {}
        self.sub_configs_dividers = {}
        self.task = task
        self.reset_config = None
        self.__initWidget()
```

- [ ] **Step 3: 修改 `__addConfig` 插入组标题**

```python
    def __addConfig(self, key: str, value):
        self.__maybe_add_group_header(key)
        widget = config_widget(self.config_type, self.config_description, self.config, key, value, self.task)
        self.config_widgets.append(widget)
        self.config_widget_by_key[key] = widget
        self.config_keys.append(key)
        self.viewLayout.addWidget(widget)
```

在 `__initWidget` 之前（`__collect_sub_configs_rules` 方法上方）新增私有方法：

```python
    def __config_groups(self):
        groups = getattr(self.task, 'config_groups', None) if self.task is not None else None
        return groups or []

    def __maybe_add_group_header(self, key: str):
        groups = self.__config_groups()
        if not groups:
            return
        from src.task.config_groups import group_of, should_insert_header
        group = group_of(key, groups)
        if should_insert_header(self._last_config_group, group):
            header = QLabel(group)
            header.setObjectName('configGroupHeader')
            header.setStyleSheet(
                'color: #009faa; font-weight: 600;'
                'padding: 6px 4px 2px 4px; background: transparent;')
            self.viewLayout.addWidget(header)
            self.group_headers.append(header)
            self.group_header_by_group[group] = header
            self._last_config_group = group
```

- [ ] **Step 4: 文件顶部 import 增加 QLabel**

```python
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
```

- [ ] **Step 5: 验证——单测（无 GUI 依赖的路径已由 Task 1/2 覆盖）+ 编译检查**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','ok','tests'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add ok/gui/tasks/ConfigCard.py
git commit -m "feat: ConfigCard 支持按 config_groups 渲染组标题(无分组任务零变化)"
```

---

### Task 4: ConfigCard 搜索框 + 过滤装配

**Covers:** 展开区顶部搜索框；输入时宽松匹配过滤配置项与组标题；空输入恢复全部分组

**Files:**
- Modify: `ok/gui/tasks/ConfigCard.py`

**Interfaces:**
- Consumes: Task 3 的 `self.group_header_by_group`/`self.config_widget_by_key`/`self.__config_groups()`；Task 1 的 `visible_keys`/`visible_groups`
- Produces: `self.search_box: QLineEdit`（仅在有 config_groups 的任务卡片出现）

- [ ] **Step 1: `__initWidget` 顶部加搜索框**

在 `self.__initWidget` 中、`self.__collect_sub_configs_rules()` 之前插入：

```python
        self.__maybe_add_search_box()
```

新增私有方法（放在 `__maybe_add_group_header` 之后）：

```python
    def __maybe_add_search_box(self):
        groups = self.__config_groups()
        if not groups:
            return
        from PySide6.QtWidgets import QLineEdit
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText('搜索选项')
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.__apply_search_filter)
        self.viewLayout.addWidget(self.search_box)

    def __apply_search_filter(self, query):
        groups = self.__config_groups()
        if not groups:
            return
        from src.task.config_groups import visible_groups, visible_keys
        keys = list(self.config_widget_by_key.keys())
        descriptions = self.config_description or {}
        visible = visible_keys(query, keys, descriptions)
        for key, widget in self.config_widget_by_key.items():
            widget.setVisible(key in visible)
        visible_group_names = visible_groups(query, groups, keys, descriptions)
        for group, header in self.group_header_by_group.items():
            header.setVisible(group in visible_group_names)
        self._adjust_config_content_size()
```

- [ ] **Step 2: 编译检查**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','ok','tests'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Expected: `OK`

- [ ] **Step 3: E2E——启动 GUI 验证分组+搜索（§11.3/§11.5）**

先停掉占用 WGC 的旧 GUI（若在跑），再用 ShellExecute runas 启动（AGENTS.md §1.3）：

```powershell
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class SHExec{[DllImport("shell32.dll", CharSet=CharSet.Unicode)]public static extern int ShellExecute(IntPtr hwnd, string op, string file, string args, string dir, int show);}'
$r = [SHExec]::ShellExecute([IntPtr]::Zero, "runas", "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe", "main_debug.py", "G:\projects\MyDocs\projects\mxd_script", 1)
```

等 MainWindowTitle 出现「OK-MXD v0.1.0 开发工具」且 WorkingSet>100MB 后：
1. 切「实时触发」tab → 展开「自动打怪」卡片：确认顶部有搜索框、配置项按 9 组显示组标题
2. 搜索框输入「锚点」：仅「角色定位」组内含「锚点」的项可见，组标题随匹配
3. 清空搜索框：恢复全部分组
4. 展开其他任务卡片（无分组任务）：确认无搜索框、无组标题（与修改前一致）
5. 截图存 `screenshots/e2e/config_groups/`（文件名带日期），用 vision-capable 模型验收（`actor models --vision` 查看可用项），结论写入 AGENTS.md 或特性说明

- [ ] **Step 4: Commit**

```bash
git add ok/gui/tasks/ConfigCard.py
git commit -m "feat: ConfigCard 展开区搜索框,关键字宽松过滤配置项与组标题"
```

---

### Task 5: 全量回归 + 验收归档

**Covers:** 项目铁律 §11.6 全量单测 + 编译检查；E2E 截图归档

**Files:**
- Modify: `AGENTS.md`（新增 §12「自动打怪卡片配置项分组+搜索」小节，记录功能说明与 E2E 验收结论）

- [ ] **Step 1: 全量单测**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo`
Expected: 全部 OK（含显式 skip 项）

- [ ] **Step 2: 全源码编译检查**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 验收结论归档**

把 Task 4 的 E2E 截图验收结论（通过/失败+原因）写进 `AGENTS.md` §12。

- [ ] **Step 4: Commit**

```bash
git add AGENTS.md screenshots/e2e/config_groups/
git commit -m "docs: AGENTS.md 记录配置项分组+搜索功能与 E2E 验收结论"
```

---

## Self-Review

- **覆盖检查**：用户需求 = 分组（Task 2/3）+ 搜索（Task 1/4）+ 不破坏逻辑（Task 3/4 的向后兼容 + Task 5 全量回归）。无 spec 文档，无缺失任务。
- **占位符扫描**：所有步骤均含完整代码/命令与期望输出，无 TBD/TODO。
- **类型一致性**：`CONFIG_GROUPS` 格式 `[(str, [str])]` 贯穿 Task 1/2/3/4；`group_of`/`should_insert_header`/`visible_keys`/`visible_groups` 签名在 Task 1 定义、Task 3/4 消费，命名一致。
- **风险确认**：`__sync_sub_config_order` 会重排 viewLayout，但仅在存在 sub_configs_rules 时触发（MapleFarmTask 无 sub_configs，其他任务无搜索框）——无冲突；`__apply_sub_config_visibility` 同理，仅 sub_configs 任务调用，不会覆盖搜索过滤结果。
