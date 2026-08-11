# Double Attack（二连击）实现计划

> [!NOTE]
> This document may not reflect the current implementation.
> See the final report for up-to-date state:
> [Final Report](../reports/double-attack.md)

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「二连击」挂机功能——检测模式下怪物进入攻击范围时，攻击键与副攻击键背靠背连按两次，中间不插入任何指令（垫步被跳过）。

**Architecture:** 在 `MapleFarmTask._do_attack` 的单体攻击分支内增加二连击判定（开关 + 副攻击键非空），连发两个 `send_key`；群攻路径、定频路径不受影响。配置分两层：`config.py` 的「游戏按键」加 `副攻击键(可留空)`（全局按键，留空=关闭，同群攻键约定），`DEFAULT_CONFIG`/`CONFIG_GROUPS` 加 `二连击开关`（默认 False）。

**Tech Stack:** Python 3.12 / PySide6 GUI / unittest（无新依赖）

## Global Constraints

- 新配置键必须同步加入 `CONFIG_GROUPS`（`tests/test_config_groups.py` 完整性用例会红）
- 攻击-副攻击之间禁止插入任何指令（垫步、转向等一律不插）；二连击开启时跳过攻击前垫步
- 副攻击键留空 = 二连击关闭（同群攻键留空约定）；二连击仅作用于检测模式单体攻击路径，群攻/定频路径零改动
- 二连击两键共用同一条 `攻击间隔(秒)` 节拍，`_last_attack = now` 记一次（同群攻路径口径）
- 测试命令：`$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline tests.test_config_groups`
- 编译检查：`$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
- 禁止 hard code 本地路径；新配置键默认值只改 `DEFAULT_CONFIG`

---

### Task 1: 配置层（副攻击键 + 二连击开关 + 归组）

**Covers:** 用户需求（副攻击键位、二连击开关默认关闭）

**Files:**
- Modify: `config.py:17`（`'群攻键(可留空)': '',` 之后插入副攻击键）
- Modify: `config.py:24`（config_description 加副攻击键描述）
- Modify: `src/task/MapleFarmTask.py:43`（`'群攻怪数阈值': 3,` 之后插入 `'二连击开关': False,`）
- Modify: `src/task/MapleFarmTask.py:89-90`（CONFIG_GROUPS「攻击」组加 `'二连击开关'`）
- Modify: `src/task/MapleFarmTask.py:226` 附近（配置描述 dict 加 `'二连击开关'` 键描述）

**Interfaces:**
- Consumes: 无
- Produces: 配置键 `'二连击开关'`（bool, 默认 False）；游戏按键 `'副攻击键(可留空)'`（str, 默认 ''）——Task 2 的 `_do_attack` 用 `cfg.get('二连击开关')` 和 `keys.get('副攻击键(可留空)', '')` 读取

- [ ] **Step 1: 先加 DEFAULT_CONFIG 键,跑完整性用例确认红**

在 `src/task/MapleFarmTask.py:43` 的 `'群攻怪数阈值': 3,` 后插入：

```python
    '二连击开关': False,
```

运行 `tests.test_config_groups`：

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups
```

Expected: FAIL——`test_all_default_config_keys_covered_exactly_once`（或等价用例）报 `二连击开关` 未被 CONFIG_GROUPS 覆盖。

- [ ] **Step 2: 归组 + 补描述**

`src/task/MapleFarmTask.py:89-90`，「攻击」组列表末尾加 `'二连击开关'`：

```python
    ('攻击', ['攻击间隔(秒)', '攻击模式', '攻击区形状', '攻击区宽(像素)', '攻击区高(像素)', '丢怪保持(秒)',
             '群攻怪数阈值', '攻击前垫步开关', '二连击开关']),
```

在配置描述 dict（`'群攻怪数阈值'` 条目之后,约 :226 附近）加：

```python
            '二连击开关': '检测模式下区内有怪时,攻击键与副攻击键背靠背连按两次(先攻击键、立即副攻击键,中间不插入垫步等任何指令),第一次攻击打不死、怪靠近后被角色/宠物遮挡导致短暂检测不到时,第二下补刀。开启后跳过「攻击前垫步」。需要先在设置页「游戏按键」绑定「副攻击键(可留空)」,留空则本项无效。超过两下才死的怪不适合挂机',
```

- [ ] **Step 3: config.py 加副攻击键**

`config.py:17` 的 `'群攻键(可留空)': '',` 后插入：

```python
    '副攻击键(可留空)': '',
```

`config.py:24` 的 config_description dict 加条目：

```python
    '副攻击键(可留空)': '二连击的第二段攻击键(先按攻击键、立即接它)。开启「二连击开关」时生效。留空 = 功能关闭',
```

- [ ] **Step 4: 测试配置层**

运行 `tests.test_config_groups`（Step 1 的完整性用例必须绿）：

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_config_groups
```

Expected: OK (10 tests)。

- [ ] **Step 5: Commit**

```bash
git add config.py src/task/MapleFarmTask.py
git commit -m "feat: 新增副攻击键与二连击开关配置(默认关,攻击组)"
```

---

### Task 2: `_do_attack` 二连击实现 + 单元测试

**Covers:** 用户需求（检测到怪进入攻击范围→攻击键+副攻击键连按、中间不插入任何指令、垫步跳过）

**Files:**
- Modify: `src/task/MapleFarmTask.py:1110-1130`（`_do_attack` 单体攻击分支）
- Modify: `tests/test_farm_task_offline.py:16-18`（KEYS 常量加副攻击键空值）
- Test: `tests/test_farm_task_offline.py`（TestAttackTap 类内新增用例）

**Interfaces:**
- Consumes: Task 1 的 `'二连击开关'`（bool）与 `'副攻击键(可留空)'`（str）
- Produces: 无新对外接口；`_do_attack(cfg, keys, now)` 行为扩展——二连击开启且副攻击键非空时,单体攻击连发两键且不垫步

- [ ] **Step 1: 更新测试 KEYS 常量并写失败测试**

`tests/test_farm_task_offline.py:16-18` 改为：

```python
KEYS = {'攻击键': 'shift', '血药键': 'home', '蓝药键': 'insert',
        '回城卷键(可留空)': '', '拾取键': 'z', '宠物食物键(可留空)': 'q',
        '椅子键(可留空)': 'r', '左移键': 'left', '右移键': 'right',
        '副攻击键(可留空)': ''}
```

在 `TestAttackTap` 类内（`test_pad_step_fires_on_first_attack` 之后,~:1036 附近）追加：

```python
    def test_double_attack_off_by_default(self):
        """二连击默认关闭:只按攻击键,不按副攻击键。"""
        task = make_task(**{'攻击模式': '检测'})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_double_attack_fires_both_keys_back_to_back(self):
        """二连击开启 + 副攻击键已绑定:先攻击键、立即副攻击键,两键相邻。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True})
        task._last_attack_present = True
        task._do_attack(task.config, keys, now=100.0)
        self.assertEqual(task.send_key.call_args_list,
                         [call('shift'), call('x')])

    def test_double_attack_skipped_when_subkey_empty(self):
        """二连击开启但副攻击键留空 → 视为关闭,只按攻击键(同群攻键约定)。"""
        task = make_task(**{'攻击模式': '检测', '二连击开关': True})
        task._last_attack_present = True
        task._do_attack(task.config, KEYS, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('shift')])

    def test_double_attack_skips_pad_step(self):
        """二连击开启时跳过攻击前垫步:方向键不许插入攻击-副攻击之间。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True,
                            '攻击前垫步开关': True, '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._last_zone = ((980, 530, 1580, 730))
        task._last_centres = [(1100, 640)]
        task._last_body_x = 1280
        task._last_attack = 98.5  # 垫步条件本应放行(1.5s<2s)
        task._do_attack(task.config, keys, now=100.0)
        self.assertEqual(task.send_key.call_args_list,
                         [call('shift'), call('x')])
        # 无任何方向键插入
        for c in task.send_key.call_args_list:
            self.assertNotIn(c.args[0], ('left', 'right'))

    def test_double_attack_respects_attack_interval(self):
        """二连击共用 攻击间隔 节拍:同一间隔内只发一轮,不连发。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True,
                            '攻击间隔(秒)': 1.5})
        task._last_attack_present = True
        task._do_attack(task.config, keys, now=100.0)
        task.send_key.reset_mock()
        task._do_attack(task.config, keys, now=101.0)  # 未满 1.5s
        task.send_key.assert_not_called()

    def test_double_attack_aoe_path_unaffected(self):
        """群攻路径零改动:区内怪数达阈值时只按群攻键,不做二连击。"""
        keys = dict(KEYS, **{'副攻击键(可留空)': 'x',
                             '群攻键(可留空)': 'a'})
        task = make_task(**{'攻击模式': '检测', '二连击开关': True,
                            '群攻怪数阈值': 2})
        task._last_zone_count = 3
        task._last_zone_count_time = 100.0
        task._last_attack = 0.0
        task._do_attack(task.config, keys, now=100.0)
        self.assertEqual(task.send_key.call_args_list, [call('a')])
```

- [ ] **Step 2: 运行测试确认红**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline.TestAttackTap
```

Expected: FAIL——`test_double_attack_fires_both_keys_back_to_back`（当前实现只按 `shift` 一次）,其余新用例按行为判定。

- [ ] **Step 3: 实现二连击**

`src/task/MapleFarmTask.py:1110-1130` 的 `_do_attack` 单体攻击分支改为：

```python
        if (self._last_attack_present
                and farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)'])
                and not farm_logic.stun_suppressed(
                    now, self._last_hit, cfg['硬直抑制窗(秒)'])):
            # 二连击:攻击键 + 副攻击键背靠背连按,中间不插入任何指令。
            # 副攻击键留空 = 关闭(同群攻键约定);开启时跳过攻击前垫步——
            # 垫步会往攻击序列里插入方向键指令,违背「攻击-副攻击零插入」。
            double_attack = (cfg.get('二连击开关')
                             and keys.get('副攻击键(可留空)', ''))
            # 攻击前垫步(战士可选):先朝最近怪所在侧轻点方向键再攻击。
            # 兜住 _facing 信念被击退/按键丢失破坏的盲区——区内有怪时
            # attack_turn_direction 认为"面朝侧还有目标"不转向,角色背对怪
            # 一直砍空气。垫步不信任信念,信念错则物理修正,信念对则是 no-op。
            # 键窗口不可点击时不垫步(方向键丢了 _facing 不许盲写,见 _key_sendable)。
            # 2 秒没攻击(空闲/寻怪中)不垫步:此时无朝向需求,垫步只会干扰寻怪移动。
            if (not double_attack
                    and cfg.get('攻击前垫步开关')
                    and self._last_zone is not None
                    and (self._last_attack == 0.0 or now - self._last_attack < 2.0)):
                body_x = self._last_body_x if self._last_body_x is not None else CALIBRATED_SIZE[0] / 2
                side = farm_logic.attack_pre_tap_direction(
                    self._last_centres, self._last_zone, body_x)
                if side is not None and self._key_sendable():
                    key = '左移键' if side == 'left' else '右移键'
                    self.send_key(keys[key], down_time=PAD_STEP_TAP_SECONDS)
            self.send_key(keys['攻击键'])
            if double_attack:
                self.send_key(keys['副攻击键(可留空)'])
            self._last_attack = now
```

- [ ] **Step 4: 运行测试确认绿**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_task_offline
```

Expected: OK（含原有 TestAttackTap 全部用例 + 6 个新用例;`test_pad_step_*` 旧用例不受影响——二连击默认关）。

- [ ] **Step 5: 全量回归 + 编译检查**

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo tests.test_config_groups tests.test_config_card_ui
```

Expected: OK(587 tests,12 skipped)——不得出现新红。

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```

Expected: OK

- [ ] **Step 6: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 二连击——攻击键+副攻击键背靠背连按,开启时跳过垫步"
```

---

### Task 3: 文档（AGENTS.md 配置表 + 计划/报告）

**Covers:** 用户需求（配置说明可发现性）

**Files:**
- Modify: `AGENTS.md` §10.1 参考配置表
- Create: `docs/compose/reports/double-attack.md`

**Interfaces:**
- Consumes: Task 1/2 的配置键与行为
- Produces: 无代码接口

- [ ] **Step 1: AGENTS.md §10.1 配置表加两行**

在 `AGENTS.md` §10.1「端侧大模型」参考配置表（`攻击模式` 行附近）加：

```markdown
| 二连击开关 | false | 区内有怪时攻击键+副攻击键连按两下(默认关;开启需绑定「副攻击键(可留空)」,留空则无效;开启时跳过攻击前垫步) |
```

并在表后「注意」块补一行：副攻击键绑定在设置页「游戏按键」→「副攻击键(可留空)」(留空=二连击关闭)。

- [ ] **Step 2: 写最终报告**

`docs/compose/reports/double-attack.md`（结构参考 `docs/compose/reports/config-groups-search.md`）:目标/实现位置/测试证据(TestAttackTap 新增 6 用例全绿 + 587 全量绿)/E2E 说明。

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/compose/reports/double-attack.md
git commit -m "docs: double attack 功能入 AGENTS.md 与最终报告"
```

---

## Self-Review

- **Spec 覆盖**:用户需求 = 副攻击键位(Task 1)、二连击开关默认关(Task 1)、攻击键→副攻击键连按(Task 2)、中间零插入+垫步跳过(Task 2: `test_double_attack_skips_pad_step` + 实现里 `not double_attack` 门)、超过 2 下不适合挂机(计划注释说明,无代码行为)。群攻/定频路径零改动——用户场景是检测模式,定频无攻击区概念,不适用。
- **占位符扫描**:无 TBD/TODO;每个代码步骤含完整代码与预期输出。
- **类型一致性**:`double_attack` 局部变量名在 Step 3 实现内一致;测试用 `keys.get('副攻击键(可留空)', '')` 与实现读法一致;KEYS 常量补键后既有用例(call('shift'))不受影响。
- **潜在风险**:`test_double_attack_aoe_path_unaffected` 依赖 `_aoe_ready` 的 `_last_zone_count_time == now` 与 `_last_attack` 节拍——测试里 `_last_attack = 0.0` 哨兵放行 should_attack,`_last_zone_count_time = 100.0 == now` 放行现测门;群攻键 'a' 非空。实现中 `double_attack` 只包单体分支,群攻 return 在前,行为正确。
