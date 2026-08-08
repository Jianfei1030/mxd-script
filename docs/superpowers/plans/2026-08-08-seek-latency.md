# 寻敌起步延迟修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「停手到起步追怪」的等待从中位 1.19s / p90 3.61s 压到中位 ≤0.5s / p90 ≤1.5s，并让一次追怪不再被一拍误判掐断（撑过 0.5s 的比例 40.4% → ≥65%）。

**Architecture:** 四处独立改动，全部落在**纯逻辑层**（`src/task/farm_logic.py`）+ **接线层**（`src/task/MapleFarmTask.py`），不碰 CV（`src/detect/*`）。顺序是「先造尺子、再动刀」：Task 1-2 只加日志字段和判据脚本（零行为变更），Task 3-7 每个任务改一个根因、各自可独立回退，Task 8 实弹验收。检测节拍从「绑在攻击间隔上」改成三态节流；寻怪的门控与去抖从攻击那边独立出来；同层判据并入接敌区。

**Tech Stack:** Python 3.11（嵌入式，`H:\ok-mxd\data\apps\ok-ww\python\python.exe`），NumPy / OpenCV（已有，本计划不新增用法），unittest。

**上游 spec:** `docs/superpowers/specs/2026-08-08-seek-latency-design.md` —— 根因推导、默认值依据、验收判据全部出自那里，**实现时不要自行改动判据或默认值**。

## Global Constraints

- **Python 只能用** `H:\ok-mxd\data\apps\ok-ww\python\python.exe`，**禁止 `pip install`**（嵌入式解释器，装不了也不许装）
- **测试命令**：`PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests`。**不是 pytest**，没装
- **当前基线：`Ran 380 tests, OK (skipped=8)`**（未恢复测试帧时）。任何任务结束时必须仍然全绿，**测试总数只增不减**
- **跑测试前先恢复测试帧**（每次跑 GUI 都会把 `screenshots/` 清空，不恢复会多出一批与本改动无关的 skip）：
  ```bash
  mkdir -p screenshots/test_frames && cp ../_frames_backup/training_ground_full_2560x1440.png screenshots/test_frames/
  ```
- **改了 `src/task/farm_logic.py` 必须重启 GUI**：框架的调试文件监视器只 `importlib.reload` 任务模块自身（`ok/gui/tasks/TaskManger.py:333-349`），不递归重载依赖，否则「新任务代码 + 旧依赖模块」= `AttributeError`
- **禁止绝对路径**（AGENTS.md §11.1）。所有路径相对仓库根 `H:\ok-mxd\ok-mxd`
- **默认值照抄 spec，不许调**：`空闲刷新间隔(秒)=0.3`、`寻怪起步宽限(秒)=0.3`、`寻怪保持(秒)=0.5`。依据在 spec §3.1 / §3.2 / §3.3
- **验收判据照抄 spec §5，不许改通过线**
- **决策日志格式的唯一事实源是 `MapleFarmTask.decision_log_line`。** 测试里**禁止手抄格式字符串** —— 2026-08-08 评审坐实过假绑定（手抄了一份格式，改字段名后 15 个「绑定」测试全过，commit 9016133）。样本行一律调真实格式函数构造
- 中文注释 / 中文日志，与现有代码风格一致
- **每个 Task 结束必须 commit**，一个 Task 一个提交，便于按 spec §6 单独回退

---

### Task 1: 决策日志补上怪的纵向信息

spec §2.3 的几何推导说「必然存在一条攻击区罩得到却判不同层的带」，但**这条带上到底有多少怪，现在测不出来** —— 决策行只有 `怪=N 区内=M`，没有任何怪的 y。Task 6 要改同层口径，改之前必须先能看见。

本任务**零行为变更**：只加日志字段。

**Files:**
- Modify: `src/task/MapleFarmTask.py`（`decision_log_line` 与 `_log_decision`、`_detect_and_act` 的调用点）
- Modify: `tests/test_analyze_facing.py`（`dec()` 辅助函数，格式绑定跟着变）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `MapleFarmTask.decision_log_line(source, body_x, anchor_y, centres, in_zone, left, same_feet, same_center, near, raw_present, mob_present, attack_in, attack_present, facing_before, facing_now, turn, seek_dir, key_sendable, observed, obs_s, obs_flip) -> str`
    - `same_feet: int` 按**旧口径**（怪脚底 vs 名字牌 y，容差 `寻怪同层容差(像素)`）算的同层怪数
    - `same_center: int` 按**新口径**（怪中心 y 落在接敌区纵向范围内）算的同层怪数
    - `near: tuple[float, float, float] | None` 水平最近那只怪的 `(dx, dy_feet, dy_center)`；屏幕无怪时 `None`
  - 新增日志字段：`同层脚=<int> 同层心=<int> 近怪dx=<±int> dy脚=<±int> dy心=<±int>`，插在 `区内=...` 与 `实测有怪=` 之间

- [ ] **Step 1: 写失败的测试**

加到 `tests/test_farm_task_offline.py` 末尾（新建一个类）：

```python
class TestDecisionLogVerticalFields(unittest.TestCase):
    """决策行的怪纵向字段 —— Task 6 改同层口径之前唯一的观测手段。

    字段格式只有一处事实源(decision_log_line),这里断言的是它的输出,
    不手抄格式串(见 tests/test_analyze_facing.py 顶部关于假绑定的记录)。"""

    def _line(self, same_feet=0, same_center=0, near=None):
        from src.task.MapleFarmTask import decision_log_line
        return decision_log_line(
            'window', 1280.0, 880.0, centres=[], in_zone=[], left=0,
            same_feet=same_feet, same_center=same_center, near=near,
            raw_present=False, mob_present=False, attack_in=[], attack_present=False,
            facing_before='LEFT', facing_now='LEFT', turn=None, seek_dir=None,
            key_sendable=True, observed=None, obs_s=0.0, obs_flip=0.0)

    def test_fields_present_with_nearest_mob(self):
        line = self._line(same_feet=1, same_center=4, near=(180.0, -24.0, -64.0))
        self.assertIn('同层脚=1 同层心=4 近怪dx=+180 dy脚=-24 dy心=-64', line)

    def test_fields_degrade_when_no_mob_on_screen(self):
        # 屏幕上一只怪都没有:三个 dy 写 '-',不许写 0(0 会被判据脚本当成真值)
        self.assertIn('同层脚=0 同层心=0 近怪dx=- dy脚=- dy心=-', self._line())

    def test_fields_sit_between_zone_and_raw_present(self):
        # 位置固定:analyze_seek.py 的正则按这个顺序写,挪位置立刻红
        line = self._line(same_feet=2, same_center=2, near=(0.0, 0.0, 0.0))
        self.assertLess(line.index('区内='), line.index('同层脚='))
        self.assertLess(line.index('同层心='), line.index('实测有怪='))

    def test_detect_and_act_feeds_real_mob_geometry(self):
        """接线断言:字段的值真的来自 find_mobs 的框,不是常量。

        几何(全部走 DEFAULT_CONFIG):角色名为空 → _resolve_anchor 直接回退
        画面中心 (1280,720);名字牌到身体偏移 90 → body=(1280,630)
        (anchor.body_center 是 y - offset,名字牌在脚下);
        接敌区 600x200 → 水平 [980,1580] 纵向 [530,730];寻怪同层容差 60。
        _detect_and_act 不读血条,直接调即可,不需要 patch bars。
        """
        task = make_task(**{'决策日志开关': True, '攻击模式': '检测'})
        # 怪 A:中心 y=600 在接敌区纵向内;脚底 640,与 anchor_y=720 差 80 > 60 → 旧口径判不同层
        mob_a = SimpleNamespace(x=1400, y=560, width=80, height=80)
        # 怪 B:中心 y=900,接敌区纵向外,两个口径都不同层
        mob_b = SimpleNamespace(x=1500, y=860, width=80, height=80)
        task.find_mobs = MagicMock(return_value=[mob_a, mob_b])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        line = next(c.args[0] for c in task.log_debug.call_args_list
                    if '决策 src=' in c.args[0])
        self.assertIn('同层脚=0 同层心=1', line)     # 正是 spec §2.3 那条「罩得到却判不同层」的带
        self.assertIn('近怪dx=+160', line)           # 怪 A 中心 1440,body_x 1280
        self.assertIn('dy脚=-80', line)              # 640 - 720
        self.assertIn('dy心=-30', line)              # 600 - 630
```

⚠️ **带括号的配置键不能当 kwargs 传** —— `make_task(丢怪保持(秒)=1.0)` 是语法错误。仓库里统一写成 `make_task(**{'丢怪保持(秒)': 1.0})`（见 `tests/test_farm_task_offline.py:2064`）。本计划后续所有测试都按这个写法。

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestDecisionLogVerticalFields -v 2>&1 | tail -20
```
Expected: FAIL —— `decision_log_line() got an unexpected keyword argument 'same_feet'`

- [ ] **Step 3: 改 `decision_log_line`**

在 `src/task/MapleFarmTask.py` 里替换整个函数：

```python
def decision_log_line(source, body_x, anchor_y, centres, in_zone, left,
                      same_feet, same_center, near,
                      raw_present, mob_present, attack_in, attack_present,
                      facing_before, facing_now, turn, seek_dir, key_sendable,
                      observed, obs_s, obs_flip):
    """决策日志行(不含时间戳前缀)—— 格式的唯一事实源。

    scripts/analyze_facing.py 与 scripts/analyze_seek.py 的正则按它解析,
    tests/test_analyze_facing.py、tests/test_analyze_seek.py 也调它构造样本行:
    改这里任何字段,绑定测试立刻红。2026-08-08 评审坐实过假绑定 ——
    当时测试里手抄了一份格式,把 `实测=` 改名后 15 个「绑定」测试全过。

    同层脚 / 同层心 是两个口径的同层怪数(spec §2.3):
    同层脚 = 怪脚底 vs 名字牌 y,容差 寻怪同层容差(旧口径,Task 6 后退休);
    同层心 = 怪中心 y 落在接敌区纵向范围内(新口径,与 mob_in_zone 同源)。
    两个都写出来,是为了量出「攻击区罩得到却判不同层」那条带上到底有多少怪。
    near = 水平最近那只怪的 (dx, dy脚, dy心);屏幕无怪时 None → 三项写 '-',
    绝不写 0(0 会被判据脚本当成真值)。
    """
    near_s = ('近怪dx=- dy脚=- dy心=-' if near is None else
              f'近怪dx={near[0]:+.0f} dy脚={near[1]:+.0f} dy心={near[2]:+.0f}')
    return (f'决策 src={source} body_x={body_x:.0f} anchor_y={anchor_y:.0f} '
            f'怪={len(centres)} 区内={len(in_zone)}(左{left}/右{len(in_zone) - left}) '
            f'同层脚={same_feet} 同层心={same_center} {near_s} '
            f'实测有怪={raw_present} 有怪={mob_present} '
            f'可打区内={len(attack_in)} 可打={attack_present} '
            f'朝向={facing_before or "-"}→{facing_now or "-"} '
            f'转向={turn or "-"} 寻怪={seek_dir or "-"} '
            f'可发键={key_sendable} '
            f'实测={_FACING_SHORT.get(observed, "?")} '
            f'分值={max(obs_s, obs_flip):.2f}/{abs(obs_s - obs_flip):.2f}')
```

- [ ] **Step 4: 改 `_log_decision` 算出这三项**

把 `_log_decision` 的签名加一个 `mobs` 参数（放在 `centres` 之后），并在函数体开头补计算：

```python
    def _log_decision(self, source, anchor_hit, body, zone, attack_area, centres, mobs,
                      raw_present, mob_present, attack_present, facing_before, turn,
                      observed, obs_s, obs_flip):
        """逐拍决策留痕(默认关,见配置 决策日志开关)。

        排"左右转向不攻击"时必须知道:锚点是哪条通道给的(fallback/cached 说明角色
        位置本身不可信)、区内怪的左右分布(两侧都有才可能来回换目标)、朝向有没有变、
        按键能不能送出去。少任何一项都只能靠猜。字段一行写完,方便 grep 「决策」后
        直接看序列。

        同层脚/同层心/近怪 三项见 decision_log_line 的说明:它们是 Task 6
        改同层口径之前唯一的观测手段(spec §2.3)。
        """
        in_zone = [x for x, y in centres if farm_logic.point_in_zone((x, y), zone)]
        left = sum(1 for x in in_zone if x < body[0])
        attack_in = [x for x, y in centres
                     if farm_logic.point_in_zone((x, y), attack_area)]
        tol = self.config.get('寻怪同层容差(像素)', 60)
        same_feet = sum(1 for m in mobs
                        if farm_logic.same_floor(m.y + m.height, anchor_hit.y, tol))
        same_center = sum(1 for m in mobs if zone[1] <= m.y + m.height / 2 <= zone[3])
        near = None
        if mobs:
            m = min(mobs, key=lambda m: abs(m.x + m.width / 2 - body[0]))
            near = (m.x + m.width / 2 - body[0],
                    (m.y + m.height) - anchor_hit.y,
                    (m.y + m.height / 2) - body[1])
        self.log_debug(decision_log_line(
            source, body[0], anchor_hit.y, centres, in_zone, left,
            same_feet, same_center, near,
            raw_present, mob_present, attack_in, attack_present,
            facing_before, self._facing, turn, self._seek_dir,
            self._key_sendable(), observed, obs_s, obs_flip))
        if observed is not None and facing_before in ('LEFT', 'RIGHT') \
                and observed != facing_before:
            now = time.time()
            self.log_debug(divergence_log_line(
                facing_before, observed, obs_s, obs_flip,
                now - self._last_attack, now - self._last_hit,
                now - self._last_turn))
```

- [ ] **Step 5: 改 `_detect_and_act` 里的调用点**

`src/task/MapleFarmTask.py:644-647`，把 `mobs` 传进去：

```python
        if cfg.get('决策日志开关'):
            self._log_decision(source, anchor_hit, body, zone, attack_area, centres, mobs,
                               raw_present, mob_present, self._last_attack_present,
                               facing_before, turn, observed, obs_s, obs_flip)
```

- [ ] **Step 6: 更新 `tests/test_analyze_facing.py` 的 `dec()` 绑定**

`dec()` 用关键字调 `decision_log_line`，新增的三个参数没有默认值，必须补上。改它的函数体：

```python
def dec(src, f0, f1, obs, turn='-', seek='-', ts=TS, key_sendable=True):
    """决策行 —— 格式来自 decision_log_line,这里只传数值(测试输入)。

    obs 传观测朝向长写 'LEFT'/'RIGHT'/None:真实接线里 _observe_facing 返回的
    就是长写,短写 L/R 是格式函数内部换算的(手抄格式的旧测试传短写,
    换到真实函数后这一层立即暴露)。

    同层脚/同层心/近怪 与朝向判据无关,填中性值:analyze_facing 的正则用 .*?
    跨过它们,这里正是要证明「加字段没打断朝向判据的解析」。"""
    return task_line(ts, decision_log_line(
        src, 1280.0, 720.0, centres=[], in_zone=[], left=0,
        same_feet=0, same_center=0, near=None,
        raw_present=False, mob_present=False, attack_in=[], attack_present=False,
        facing_before=f0, facing_now=f1, turn=turn, seek_dir=seek,
        key_sendable=key_sendable, observed=obs, obs_s=0.86, obs_flip=0.39))
```

- [ ] **Step 7: 跑测试确认通过（含 analyze_facing 回归）**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline tests.test_analyze_facing -v 2>&1 | tail -20
```
Expected: PASS —— `test_analyze_facing` 全绿即证明新字段没打断朝向判据的解析（它的 `DEC` 正则靠 `.*?` 跨过中间字段）

- [ ] **Step 8: 全量单测**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```
Expected: `OK`，测试数 ≥ 384（380 + 本任务 4 个）

- [ ] **Step 9: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py tests/test_analyze_facing.py docs/superpowers/specs/2026-08-08-seek-latency-design.md
git commit -m "$(cat <<'EOF'
feat: 决策日志补怪的纵向信息——同层两种口径并排写,先造尺子

spec §2.3 的几何推导说「必然存在一条攻击区罩得到却判不同层的带」,
但决策行只有 怪=N 区内=M,没有任何怪的 y,那条带上有多少怪测不出来。
同层脚(旧口径)/同层心(新口径)/近怪dx,dy脚,dy心 一起写出来,
Task 6 改口径之前先拿到数据。零行为变更。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 判据脚本 `scripts/analyze_seek.py`

spec §5 的六条判据必须能被机器复算，否则「改好了没有」只能靠肉眼。照 `scripts/analyze_facing.py` 的模式：**判据在 spec 里写死，脚本只负责算出来，不许在脚本里改通过线。**

判据定义特意只依赖 `可打=` 和 `寻怪=` —— `有怪=` 的门控作用会被 Task 4 改掉，拿它当尺子会在改动后失真。

**Files:**
- Create: `scripts/analyze_seek.py`
- Test: `tests/test_analyze_seek.py`

**Interfaces:**
- Consumes: `MapleFarmTask.decision_log_line`（Task 1 的格式）
- Produces:
  - `analyze_seek.parse(lines) -> list[dict]`，每项键：`t`(float 秒), `mobs`(int), `can_atk`(bool), `seek`(str, `'-'`=没在追), `same_feet`(int|None), `same_center`(int|None)
  - `analyze_seek.sessionize(rows, gap=10.0) -> list[list[dict]]`
  - `analyze_seek.metrics(sessions) -> dict`，键：`A_median`, `A_p90`, `B_ratio`, `C_ratio`, `D_ratio`, `E_p90`, `E_max`

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_analyze_seek.py`：

```python
"""analyze_seek.py 与日志格式的绑定测试 + 判据算法测试。

样本行一律由 MapleFarmTask.decision_log_line 构造,不手抄格式 ——
谁改日志字段,这里的样本行跟着变,正则对不上立刻红(见
tests/test_analyze_facing.py 顶部关于 2026-08-08 假绑定的记录)。

判据定义在 docs/superpowers/specs/2026-08-08-seek-latency-design.md §5,
本文件只测「算法算得对不对」,不测通过线。
"""
import importlib.util
import os
import unittest

from src.task.MapleFarmTask import decision_log_line

_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'analyze_seek.py')
_SPEC = importlib.util.spec_from_file_location('analyze_seek', _SCRIPT)
aseek = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(aseek)


def line(sec, mobs=0, can_atk=False, seek='-', same_feet=0, same_center=0):
    """一条带时间戳的决策行。sec = 当天第几秒(测试只关心相对时间)。"""
    ts = f'2026-08-08 {sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d},000'
    body = decision_log_line(
        'window', 1280.0, 880.0,
        centres=[(0.0, 0.0)] * mobs, in_zone=[], left=0,
        same_feet=same_feet, same_center=same_center, near=None,
        raw_present=False, mob_present=False,
        attack_in=[], attack_present=can_atk,
        facing_before='LEFT', facing_now='LEFT', turn=None, seek_dir=seek,
        key_sendable=True, observed=None, obs_s=0.0, obs_flip=0.0)
    return f'{ts} DEBUG TaskExecutor MapleFarmTask:{body}'


class TestParse(unittest.TestCase):

    def test_parses_fields_written_by_the_real_formatter(self):
        rows = aseek.parse([line(10, mobs=3, can_atk=True, seek='right',
                                 same_feet=1, same_center=4)])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['mobs'], 3)
        self.assertTrue(r['can_atk'])
        self.assertEqual(r['seek'], 'right')
        self.assertEqual(r['same_feet'], 1)
        self.assertEqual(r['same_center'], 4)

    def test_ignores_non_decision_lines(self):
        self.assertEqual(aseek.parse(['2026-08-08 10:00:00,000 INFO x:随便什么']), [])

    def test_tolerates_older_log_generations(self):
        """老日志必须照样能算 —— 基线快照里就有两代格式。

        这两条样本**故意手抄**,是「禁止手抄格式」那条规矩的正当例外:
        它们是**历史**格式,今天的 decision_log_line 已经生不出来了,
        而 Step 5 复算基线要靠解析它们。判据 A-E 都不依赖纵向字段。
        """
        # 第一代:8eb39ce(朝向纠正)之前,连 实测=/分值= 尾巴都没有
        gen1 = ('2026-08-08 10:00:00,000 DEBUG TaskExecutor MapleFarmTask:'
                '决策 src=window body_x=1280 anchor_y=880 怪=3 区内=0(左0/右0) '
                '实测有怪=False 有怪=False 可打区内=0 可打=False '
                '朝向=LEFT→LEFT 转向=- 寻怪=left 可发键=True')
        # 第二代:有 实测=/分值=,但还没有 Task 1 的纵向字段
        gen2 = ('2026-08-08 15:00:00,000 DEBUG TaskExecutor MapleFarmTask:'
                '决策 src=window body_x=1280 anchor_y=880 怪=3 区内=0(左0/右0) '
                '实测有怪=False 有怪=False 可打区内=0 可打=True '
                '朝向=LEFT→LEFT 转向=- 寻怪=right 可发键=True 实测=? 分值=0.00/0.00')
        rows = aseek.parse([gen1, gen2])
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['seek'] for r in rows], ['left', 'right'])
        self.assertEqual([r['can_atk'] for r in rows], [False, True])
        self.assertEqual([r['mobs'] for r in rows], [3, 3])
        self.assertEqual([r['same_feet'] for r in rows], [None, None])


class TestSessionize(unittest.TestCase):

    def test_splits_on_long_gap(self):
        rows = aseek.parse([line(1), line(2), line(3), line(60), line(61), line(62)])
        self.assertEqual(len(aseek.sessionize(rows, gap=10.0, min_rows=2)), 2)


class TestMetrics(unittest.TestCase):

    def test_A_waits_from_stop_attacking_to_seek_start(self):
        # 第 1 秒还在打 → 第 2 秒停手且屏幕有怪(等待起算) → 第 5 秒才起步 = 3s
        rows = aseek.parse([line(1, mobs=2, can_atk=True),
                            line(2, mobs=2), line(3, mobs=2), line(4, mobs=2),
                            line(5, mobs=2, seek='left')])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['A_median'], 3.0, places=2)

    def test_A_ignores_stretches_with_no_mob_on_screen(self):
        # 屏幕上没怪,不追是对的,不该计进等待
        rows = aseek.parse([line(1, mobs=1, can_atk=True), line(2), line(3),
                            line(4, mobs=1), line(5, mobs=1, seek='left')])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['A_median'], 1.0, places=2)

    def test_B_counts_seek_segments_lasting_at_least_half_second(self):
        # 段一:第 1-3 秒在追(2s,算撑住);段二:第 5 秒一拍就断(0s,不算)
        rows = aseek.parse([line(1, mobs=1, seek='left'), line(2, mobs=1, seek='left'),
                            line(3, mobs=1, seek='left'), line(4, mobs=1),
                            line(5, mobs=1, seek='right'), line(6, mobs=1)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['B_ratio'], 0.5, places=3)

    def test_C_idle_ratio_counts_only_stretches_with_mobs_on_screen(self):
        # 10 秒里:第 2-6 秒空转且有怪(4s),第 7-8 秒空转但没怪(不计)
        rows = aseek.parse([line(1, mobs=1, can_atk=True)]
                           + [line(s, mobs=1) for s in range(2, 7)]
                           + [line(7), line(8)]
                           + [line(9, mobs=1, can_atk=True), line(11, mobs=1, can_atk=True)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['C_ratio'], 4.0 / 10.0, places=3)

    def test_D_is_share_of_attacking_ticks(self):
        rows = aseek.parse([line(1, can_atk=True), line(2), line(3, can_atk=True), line(4)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['D_ratio'], 0.5, places=3)

    def test_E_reports_tick_interval_tail(self):
        rows = aseek.parse([line(1), line(2), line(3), line(9)])
        m = aseek.metrics(aseek.sessionize(rows, min_rows=2))
        self.assertAlmostEqual(m['E_max'], 6.0, places=2)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_analyze_seek -v 2>&1 | tail -20
```
Expected: FAIL —— `FileNotFoundError` / `analyze_seek.py` 不存在

- [ ] **Step 3: 写 `scripts/analyze_seek.py`**

```python
# -*- coding: utf-8 -*-
"""寻敌起步延迟判据 A/B/C/D/E(2026-08-08-seek-latency-design.md §5)。

判据在 spec 里事先写死,本脚本只是把它算出来,不许在这里改通过线。

判据只依赖 可打= 与 寻怪= 两个字段:有怪= 的门控作用在本次改动中被改掉了
(spec §3.2),拿它当尺子会在改动前后失真。同层脚= / 同层心= 是 Task 1 加的
观测字段,老日志没有,解析时可缺省(判据 A-E 都不用它们)。

用法:
    python scripts/analyze_seek.py [日志路径] [--since HH:MM:SS] [--until HH:MM:SS]
默认日志路径 logs/ok-script.log。基线快照见 spec §2。
"""
import re
import sys
from datetime import datetime

DEFAULT_LOG = 'logs/ok-script.log'

DEC = re.compile(
    r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) .*?'
    r'决策 src=\S+ body_x=\S+ anchor_y=\S+ 怪=(\d+) 区内=\d+\(\S+\) '
    r'(?:同层脚=(\d+) 同层心=(\d+) 近怪dx=\S+ dy脚=\S+ dy心=\S+ )?'
    r'实测有怪=\w+ 有怪=\w+ 可打区内=\d+ 可打=(\w+) '
    r'朝向=\S+→\S+ 转向=\S+ 寻怪=(\S+) ')


def parse(lines):
    """决策行 → 判据要用的字段。不认识的行直接跳过。"""
    rows = []
    for line in lines:
        m = DEC.match(line)
        if not m:
            continue
        ts, mobs, same_feet, same_center, can_atk, seek = m.groups()
        rows.append(dict(
            t=datetime.strptime(ts, '%Y-%m-%d %H:%M:%S,%f').timestamp(),
            mobs=int(mobs),
            same_feet=None if same_feet is None else int(same_feet),
            same_center=None if same_center is None else int(same_center),
            can_atk=can_atk == 'True',
            seek=seek))
    return rows


def sessionize(rows, gap=10.0, min_rows=20):
    """按大间隔切段:停任务/重启会在日志里留下长空档,跨段算时长没有意义。"""
    if not rows:
        return []
    out, cur = [], [rows[0]]
    for a, b in zip(rows, rows[1:]):
        if b['t'] - a['t'] > gap:
            out.append(cur)
            cur = []
        cur.append(b)
    out.append(cur)
    return [s for s in out if len(s) >= min_rows]


def _quantile(xs, q):
    if not xs:
        return float('nan')
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def _waits(sessions):
    """判据 A:从「可打=False 且 怪>0 且 寻怪=-」的第一拍,到「寻怪≠-」那一拍。

    可打=True 会把等待清零(在打就不该追);屏幕上没怪的拍不起算(不追是对的)。
    """
    out = []
    for s in sessions:
        start = None
        for r in s:
            if r['can_atk']:
                start = None
            elif r['seek'] != '-':
                if start is not None:
                    out.append(r['t'] - start)
                start = None
            elif r['mobs'] > 0 and start is None:
                start = r['t']
    return out


def _seek_segments(sessions):
    """判据 B:每一段连续「寻怪≠-」的时长(段内首末拍的时间差)。"""
    out = []
    for s in sessions:
        start, prev = None, None
        for r in s:
            if r['seek'] != '-' and start is None:
                start = r['t']
            elif r['seek'] == '-' and start is not None:
                out.append(prev['t'] - start)
                start = None
            prev = r
        if start is not None:
            out.append(prev['t'] - start)
    return out


def _idle_runs(sessions):
    """判据 C:每一段连续「可打=False 且 寻怪=- 且 怪>0」的时长。"""
    out = []
    for s in sessions:
        start, prev = None, None
        for r in s:
            idle = (not r['can_atk']) and r['seek'] == '-' and r['mobs'] > 0
            if idle and start is None:
                start = r['t']
            elif not idle and start is not None:
                out.append(prev['t'] - start)
                start = None
            prev = r
        if start is not None:
            out.append(prev['t'] - start)
    return [x for x in out if x > 0]


def metrics(sessions):
    rows = [r for s in sessions for r in s]
    span = sum(s[-1]['t'] - s[0]['t'] for s in sessions)
    waits = _waits(sessions)
    segs = _seek_segments(sessions)
    idle = _idle_runs(sessions)
    gaps = [b['t'] - a['t'] for s in sessions for a, b in zip(s, s[1:])]
    return dict(
        ticks=len(rows), span=span, sessions=len(sessions),
        A_n=len(waits), A_median=_quantile(waits, .5), A_p90=_quantile(waits, .9),
        B_n=len(segs), B_ratio=(sum(1 for x in segs if x >= 0.5) / len(segs)
                                if segs else float('nan')),
        C_n=len(idle), C_ratio=(sum(idle) / span if span else float('nan')),
        D_ratio=(sum(1 for r in rows if r['can_atk']) / len(rows)
                 if rows else float('nan')),
        E_median=_quantile(gaps, .5), E_p90=_quantile(gaps, .9),
        E_max=max(gaps) if gaps else float('nan'))


def main(argv):
    path = DEFAULT_LOG
    since = until = None
    args = list(argv)
    for flag, setter in (('--since', 'since'), ('--until', 'until')):
        if flag in args:
            i = args.index(flag)
            value = args[i + 1]
            if setter == 'since':
                since = value
            else:
                until = value
            del args[i:i + 2]
    if args:
        path = args[0]
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = list(f)
    if since or until:
        lines = [ln for ln in lines
                 if (not since or ln[11:19] >= since)
                 and (not until or ln[11:19] <= until)]
    m = metrics(sessionize(parse(lines)))
    print(f'{path}: {m["ticks"]} 拍 / {m["span"]:.0f}s / {m["sessions"]} 段')
    print(f'A 停手→起步寻怪  中位 {m["A_median"]:.2f}s  p90 {m["A_p90"]:.2f}s  '
          f'(n={m["A_n"]})   通过线: 中位<=0.50 且 p90<=1.50')
    print(f'B 寻怪段撑过0.5s {m["B_ratio"]:.1%}  (n={m["B_n"]})'
          f'                通过线: >=65%')
    print(f'C 连续空转累计   {m["C_ratio"]:.1%}  (n={m["C_n"]})'
          f'                通过线: <=12%')
    print(f'D 可打拍占比     {m["D_ratio"]:.1%}'
          f'                          通过线: >=41.0%')
    print(f'E 拍间隔 中位 {m["E_median"]:.3f}s  p90 {m["E_p90"]:.3f}s  '
          f'max {m["E_max"]:.3f}s   通过线: p90<=0.60 且 max<=5.0')


if __name__ == '__main__':
    main(sys.argv[1:])
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_analyze_seek -v 2>&1 | tail -20
```
Expected: PASS（9 个用例：`TestParse` 3 + `TestSessionize` 1 + `TestMetrics` 5）

- [ ] **Step 5: 用脚本复算冻结基线，核对 spec §2.1 的表**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/analyze_seek.py \
    logs/baseline-2026-08-08-seek.log --since 14:10:00
```
Expected（= spec §2.1 主基线，6668 拍 / 4211s / 10 段）：
A 中位 ≈1.19 / p90 ≈3.61，B ≈40.4%，C ≈25.2%，D ≈41.0%，E p90 ≈0.946 / max ≈9.78。

⚠️ **`--since 14:10:00` 不能省。** 这份日志里有两代格式：今天的 `8eb39ce`（朝向纠正）才给决策行加了 `实测=` / `分值=` 尾巴。本脚本的正则两代都吃，不限窗口会把 00:47 起的 30557 拍全算进来（那是朝向纠正上线**之前**的行为），得到 A 1.29/5.02、B 48.8%、C 23.5%、D 39.2% —— 结论方向一致，但**不是** spec §2.1 的那张表。

⚠️ `logs/` 在 `.gitignore` 里，快照只存本机。**若该文件不存在**（换机器 / 被清理），改用 `logs/ok-script.log` 复算，并把算出的数字**更新进 spec §2.1**，注明新的窗口 —— 判据的通过线是相对基线定的，基线换了要一起换，但通过线的**相对改善幅度**（A 减半、B +25pt、C 减半）必须保持。

- [ ] **Step 6: 全量单测 + Commit**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
git add scripts/analyze_seek.py tests/test_analyze_seek.py
git commit -m "$(cat <<'EOF'
feat: 寻敌判据脚本 analyze_seek —— 先造尺子再动刀

spec §5 的 A/B/C/D/E 五条判据的唯一复算入口。判据只用 可打= / 寻怪=,
不用 有怪=(它的门控作用会被 Task 4 改掉,当尺子会失真)。
样本行由 decision_log_line 构造,格式改动立刻红。
复算冻结基线 logs/baseline-2026-08-08-seek.log 与 spec §2.1 一致。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `farm_logic.should_detect` —— 检测节拍三态节流（纯函数）

治根因 ①（spec §3.1）。先写纯函数，Task 4 再接线 —— 拆开是为了让「节流逻辑对不对」能离线断言（AGENTS.md §11.2：不许把决策逻辑塞进 `run()`）。

**Files:**
- Modify: `src/task/farm_logic.py`（在 `should_attack` 之后新增）
- Test: `tests/test_farm_logic.py`

**Interfaces:**
- Consumes: 无
- Produces: `farm_logic.should_detect(now, last_detect, attacking, seeking, attack_interval, seek_interval, idle_interval) -> bool`
  - `attacking: bool` —— 有向攻击区内有怪（接线时传 `bool(self._last_attack_present)`）
  - `seeking: bool` —— 正在追（接线时传 `self._seek_dir is not None`）

- [ ] **Step 1: 写失败的测试**

加到 `tests/test_farm_logic.py` 的 `TestFarmLogic` 类里：

```python
    def test_should_detect_three_cadences(self):
        # 在打:按攻击间隔(慢)。检测本来就是为下一刀服务,不必更快,负载不回归
        self.assertFalse(fl.should_detect(1000.5, 1000.0, True, False, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.75, 1000.0, True, False, 0.7, 0.1, 0.3))
        # 在追:按寻怪刷新间隔(最快)。目标死了/换近了要立刻改方向
        self.assertFalse(fl.should_detect(1000.05, 1000.0, False, True, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.15, 1000.0, False, True, 0.7, 0.1, 0.3))
        # 空闲:按空闲刷新间隔 —— 这是「起步寻怪」唯一的入口(spec §3.1)
        self.assertFalse(fl.should_detect(1000.2, 1000.0, False, False, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.35, 1000.0, False, False, 0.7, 0.1, 0.3))

    def test_should_detect_attacking_beats_seeking(self):
        # 攻击区里有怪就是在打,不该被寻怪的快间隔拉高负载
        self.assertFalse(fl.should_detect(1000.15, 1000.0, True, True, 0.7, 0.1, 0.3))
        self.assertTrue(fl.should_detect(1000.75, 1000.0, True, True, 0.7, 0.1, 0.3))

    def test_should_detect_boundary_is_inclusive(self):
        # 与 should_attack 同口径:恰好到点就放行,别让浮点抖动多等一拍
        self.assertTrue(fl.should_detect(1000.5, 1000.0, False, False, 0.7, 0.1, 0.5))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v 2>&1 | tail -20
```
Expected: FAIL —— `module 'src.task.farm_logic' has no attribute 'should_detect'`

- [ ] **Step 3: 写实现**

加到 `src/task/farm_logic.py` 的 `should_attack` 之后：

```python
def should_detect(now, last_detect, attacking, seeking,
                  attack_interval, seek_interval, idle_interval):
    """检测拍节流:三种状态各有各的节奏,取当前状态对应的间隔。

    - 在打(有向攻击区里有怪)→ 攻击间隔:检测本来就是为下一刀服务的,
      没必要更快;这一段占挂机时间 41%,保持原节奏 = 负载不回归。
    - 在追 → 寻怪刷新间隔:目标死了/换近了要立刻改方向。
    - 空闲(都不是)→ 空闲刷新间隔。**这是「起步寻怪」唯一的入口。**

    旧实现把「起步」也绑在攻击间隔上,快通道的进入条件是
    `_seek_dir is not None`,于是它只能刷新一个已经存在的寻怪、
    永远发起不了新的。实测停手→起步中位 1.19s / p90 3.61s,
    而 寻怪刷新间隔 调到 0.1s 对这一步完全无效(spec §3.1)。

    「在打」优先于「在追」:攻击区里有怪就是在打,不该被寻怪间隔拉快。
    边界与 should_attack 同口径(>= 即放行)。
    """
    if attacking:
        interval = attack_interval
    elif seeking:
        interval = seek_interval
    else:
        interval = idle_interval
    return now - last_detect >= interval
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/task/farm_logic.py tests/test_farm_logic.py
git commit -m "$(cat <<'EOF'
feat: farm_logic.should_detect —— 检测节拍三态节流

在打/在追/空闲各用各的间隔。旧实现把「起步寻怪」绑在攻击间隔上,
快通道的进入条件是 _seek_dir is not None,只能刷新已有寻怪、
发起不了新的 —— 寻怪刷新间隔调到 0.1s 对起步这一步完全无效。
纯函数,本次不接线(Task 4)。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 接线三态节流 + 新配置 `空闲刷新间隔(秒)`

把 Task 3 的纯函数接进 `run()`，`elif` 分支消失，死状态 `_last_seek_refresh` 一并删除。

**Files:**
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG`、`config_description`、`_reset_state`、`_detect_and_act`、`run`）
- Modify: `GETTING_STARTED.md`（配置项全表）
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `farm_logic.should_detect`（Task 3）
- Produces: 新配置键 `空闲刷新间隔(秒)`，默认 `0.3`

- [ ] **Step 1: 写失败的测试**

加到 `tests/test_farm_task_offline.py` 末尾（新建一个类）：

```python
class TestDetectCadence(unittest.TestCase):
    """检测拍三态节流的接线(spec §3.1)。

    几何:DEFAULT_CONFIG['角色名'] 为空 → 锚点恒为画面中心,不依赖存档帧。
    """

    def _task(self, **cfg):
        """run() 全程走 mock:_detect_and_act 换成计数器,只验节流。
        走位/坐椅/喝药全关,免得它们各自的计时器干扰 send_key 断言。"""
        task = make_task(**{'攻击模式': '检测', '喝药开关': False,
                            '走位开关': False, '坐椅开关': False,
                            '攻击间隔(秒)': 0.7, '空闲刷新间隔(秒)': 0.3,
                            '寻怪刷新间隔(秒)': 0.1, **cfg})
        task._detect_and_act = MagicMock()
        return task

    def test_idle_detects_at_idle_interval_not_attack_interval(self):
        """空闲时按 空闲刷新间隔(0.3) 检测,不再等 攻击间隔(0.7)。

        这是本次修复的核心:起步寻怪只能在检测拍里发生,旧实现里
        空闲期的检测拍是 0.7s 一次(spec §3.1)。"""
        task = self._task()
        task._last_detect = 1000.0
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.2)
        self.assertEqual(task._detect_and_act.call_count, 0)
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.35)
        self.assertEqual(task._detect_and_act.call_count, 1)

    def test_attacking_keeps_attack_interval(self):
        """在打时仍按 攻击间隔,负载不回归。"""
        task = self._task()
        task._last_detect = 1000.0
        task._last_attack_present = True
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.35)
        self.assertEqual(task._detect_and_act.call_count, 0)
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.75)
        self.assertEqual(task._detect_and_act.call_count, 1)

    def test_seeking_uses_seek_refresh_interval(self):
        task = self._task()
        task._last_detect = 1000.0
        task._seek_dir = 'right'
        run_with_frame(task, hp=1.0, mp=1.0, exp=0.5, now=1000.15)
        self.assertEqual(task._detect_and_act.call_count, 1)

    def test_last_seek_refresh_state_is_gone(self):
        """_last_seek_refresh 随 elif 分支一起退休,不留死状态。"""
        task = self._task()
        self.assertFalse(hasattr(task, '_last_seek_refresh'))

    def test_idle_interval_has_a_default(self):
        self.assertEqual(DEFAULT_CONFIG['空闲刷新间隔(秒)'], 0.3)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestDetectCadence -v 2>&1 | tail -20
```
Expected: FAIL —— `KeyError: '空闲刷新间隔(秒)'`

- [ ] **Step 3: 加配置键与说明**

`src/task/MapleFarmTask.py` 的 `DEFAULT_CONFIG`，在 `'寻怪外推速度(像素/秒)': 250,` 之后加一行：

```python
    '空闲刷新间隔(秒)': 0.3,
```

`config_description.update({...})` 里，在 `'寻怪刷新间隔(秒)'` 那条之后加：

```python
            '空闲刷新间隔(秒)': '既不在打也不在追时,多久跑一次检测拍。**「起步寻怪」只能在检测拍里发生,所以这个值直接决定「停手到迈腿」有多快。**旧实现里这一步被绑在 攻击间隔 上(0.7s),而 寻怪刷新间隔 只能刷新一个已经存在的寻怪、发起不了新的,所以把它调小对起步毫无作用——2026-08-08 实测停手→起步中位 1.19s、p90 3.61s,屏幕上有怪却既不打也不追的时间占 25.2%。默认 0.3:一个完整检测拍(模板/OCR+YOLO+朝向观测)实测耗时中位 0.178s、p90 0.286s,10Hz 主循环实际只跑得到 5.6Hz,取 0.1 只会把 CPU 打满而并不会更快。调回 0.7 = 旧行为',
```

- [ ] **Step 4: 删除死状态 `_last_seek_refresh`**

先确认没有别的引用：

```bash
grep -rn "_last_seek_refresh" src/ tests/ scripts/
```

`_reset_state` 里删掉这一行：
```python
        self._last_seek_refresh = 0.0  # 寻怪中快速刷新目标方向的节流时刻
```

`_detect_and_act` 的寻怪分支里（`src/task/MapleFarmTask.py:639-642`）删掉赋值，只留 `_last_walk`：

```python
                if self._seek_dir is not None:
                    # 寻怪本身就在移动=活动中,防挂机走位倒计时顺延
                    self._last_walk = now
```

- [ ] **Step 5: 改 `run()` 的第 4 节**

把 `src/task/MapleFarmTask.py:927-938` 的 `if/elif` 两段替换成一段：

```python
        if cfg['攻击模式'] == '检测':
            # 检测拍三态节流:在打→攻击间隔;在追→寻怪刷新间隔;空闲→空闲刷新间隔。
            # 空闲那一档是「起步寻怪」唯一的入口 —— 旧实现把它绑在攻击间隔上,
            # 而快通道要求 _seek_dir 已经不是 None,只能刷新已有寻怪、
            # 发起不了新的(spec §3.1)
            if farm_logic.should_detect(
                    now, self._last_detect,
                    bool(self._last_attack_present), self._seek_dir is not None,
                    cfg['攻击间隔(秒)'], cfg['寻怪刷新间隔(秒)'],
                    cfg['空闲刷新间隔(秒)']):
                self._last_detect = now
                self._detect_and_act(frame, now, cfg, keys)
```

（其后的 `self._do_attack(...)` / `self._do_seek_move(...)` / `_mark_busy` 三行保持原样。）

- [ ] **Step 6: 跑测试确认通过**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 7: 更新 `GETTING_STARTED.md` 配置项全表**

在「寻怪刷新间隔(秒)」那一行下面补一行，格式照该表已有行：

```markdown
| `空闲刷新间隔(秒)` | 0.3 | 不打也不追时的检测节奏。**起步寻怪只能在检测拍里发生,这个值直接决定「停手到迈腿」有多快**。调回 0.7 = 修复前行为 |
```

- [ ] **Step 8: 全量单测 + Commit**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py GETTING_STARTED.md
git commit -m "$(cat <<'EOF'
fix: 检测节拍与攻击节拍解耦,起步寻怪不再等 0.7s

新配置 空闲刷新间隔(秒)=0.3。旧实现里快通道的进入条件是
_seek_dir is not None,只能刷新已有寻怪,于是「站着→开始追」
永远走 攻击间隔 的慢拍,用户把 寻怪刷新间隔 调到 0.1 也没用。
elif 分支消失,死状态 _last_seek_refresh 一并删除。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 寻怪起步不再被丢怪保持门控 + 新配置 `寻怪起步宽限(秒)`

治根因 ②（spec §3.2）。`丢怪保持(1.0s)` 对攻击键是对的，问题是它被借去门控寻怪，制造 1 秒结构性死区（实测 11.5% 的拍在这个窗里，其中 3310 拍屏幕上有怪）。

**Files:**
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG`、`config_description`、`_detect_and_act`）
- Modify: `GETTING_STARTED.md`
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `farm_logic.mob_present_debounced`（已有）
- Produces: 新配置键 `寻怪起步宽限(秒)`，默认 `0.3`；约束 **必须 < `丢怪保持(秒)`**

- [ ] **Step 1: 写失败的测试**

加到 `tests/test_farm_task_offline.py` 末尾：

```python
class TestSeekNotBlockedByAttackGrace(unittest.TestCase):
    """寻怪起步与攻击去抖分家(spec §3.2)。

    几何(全部走 DEFAULT_CONFIG):角色名为空 → 锚点画面中心 (1280,720),
    名字牌到身体偏移 90 → body=(1280,630);接敌区 600x200 →
    水平 [980,1580] 纵向 [530,730]。怪放在中心 (2200, 632):
    水平出区(不该打)、纵向同层、脚底 672 与 anchor_y 720 差 48 ≤ 容差 60
    (本任务还没改同层口径,旧口径也判同层)→ 该追。
    """

    def _task(self, **cfg):
        return make_task(**{'攻击模式': '检测', '寻怪开关': True,
                            '丢怪保持(秒)': 1.0, '寻怪起步宽限(秒)': 0.3, **cfg})

    @staticmethod
    def _far_mob():
        return SimpleNamespace(x=2160, y=592, width=80, height=80)

    def test_seek_starts_once_short_grace_elapsed(self):
        """区里最后一只怪没了 0.3s 后就能起步,不用等满 1.0s 的丢怪保持。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0          # 区内最后一次真见到怪
        task._detect_and_act(_synthetic_frame(), 1000.35, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')

    def test_seek_still_blocked_inside_short_grace(self):
        """0.3s 之内不起步:一拍 YOLO 漏检不该让角色立刻迈腿。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0
        task._detect_and_act(_synthetic_frame(), 1000.2, task.config, KEYS)
        self.assertIsNone(task._seek_dir)

    def test_starting_seek_drops_the_stale_attack_signal(self):
        """起步即停手:不许出现「一边追一边挥」。

        _last_attack_present 还被 丢怪保持 撑着 True,寻怪一旦定向就作废它,
        否则 _do_attack 会继续朝空气轻点攻击键
        (MapleFarmTask.py 去抖注释里担心过的错乱状态)。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0
        task._last_attack_seen = 1000.0
        task._detect_and_act(_synthetic_frame(), 1000.35, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')
        self.assertFalse(task._last_attack_present)

    def test_sit_chair_and_walk_still_use_the_long_grace(self):
        """_last_mob_present 仍按 丢怪保持(1.0s) 算:
        坐椅/防挂机走位不该在怪刚消失 0.3s 就触发。"""
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._last_mob_seen = 1000.0
        task._detect_and_act(_synthetic_frame(), 1000.35, task.config, KEYS)
        self.assertTrue(task._last_mob_present)

    def test_short_grace_has_a_default_below_the_long_one(self):
        self.assertEqual(DEFAULT_CONFIG['寻怪起步宽限(秒)'], 0.3)
        self.assertLess(DEFAULT_CONFIG['寻怪起步宽限(秒)'],
                        DEFAULT_CONFIG['丢怪保持(秒)'])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline.TestSeekNotBlockedByAttackGrace -v 2>&1 | tail -20
```
Expected: FAIL —— `KeyError: '寻怪起步宽限(秒)'`

- [ ] **Step 3: 加配置键与说明**

`DEFAULT_CONFIG` 里，`'丢怪保持(秒)': 1.0,` 之后加：

```python
    '寻怪起步宽限(秒)': 0.3,
```

`config_description` 里，`'丢怪保持(秒)'` 那条之后加：

```python
            '寻怪起步宽限(秒)': '区内检测不到怪之后,还要再等多久才允许起步去追。**必须小于「丢怪保持(秒)」**,取等 = 退回修复前行为。为什么要分成两个值:丢怪保持是为 YOLO 漏检兜底的(单帧 recall 0.886,一拍漏检就松开攻击键,法师一次施法都放不出来),那个理由只对攻击键成立——多挥一刀空的代价,远小于多站一秒不动。2026-08-08 实测有 11.5% 的拍卡在丢怪保持窗里,其中 3310 拍屏幕上明明有怪却结构性禁止寻怪。攻击键本身不受此项影响(它由「有向攻击区内有没有怪」单独去抖)。寻怪方向一旦定下来,还被丢怪保持撑着的攻击信号会立刻作废,不会出现「一边追一边挥」',
```

- [ ] **Step 4: 改 `_detect_and_act` 的分支门**

`src/task/MapleFarmTask.py` 里，把 `mob_present` 的计算改成两个门（原第 580-582 行附近）：

```python
        mob_present = farm_logic.mob_present_debounced(
            raw_present, now, self._last_mob_seen, cfg['丢怪保持(秒)'])
        self._last_mob_present = mob_present
        # 接战/寻怪的分支门用一个更短的宽限:丢怪保持(1.0s)是为攻击键兜 YOLO
        # 漏检的,那个理由不适用于寻怪 —— 它把「起步走路」也禁掉了整整一秒
        # (实测 11.5% 的拍卡在这个窗里,其中 3310 拍屏幕上有怪,spec §3.2)。
        # _last_mob_present 仍用长宽限:坐椅/防挂机走位不该在怪刚消失 0.3s 就触发。
        seek_hold = farm_logic.mob_present_debounced(
            raw_present, now, self._last_mob_seen, cfg['寻怪起步宽限(秒)'])
```

再把分支判断从 `if mob_present:` 改成 `if seek_hold:`（`src/task/MapleFarmTask.py:602`）：

```python
        facing_before, turn = belief_before_obs, None
        if seek_hold:
            self._seek_dir = None  # 怪进攻击区了,停追,原地攻击
```

（该分支内部一行不改。）

最后在 `else:` 寻怪分支里，定向成功时作废过期的攻击信号：

```python
                if self._seek_dir is not None:
                    # 寻怪本身就在移动=活动中,防挂机走位倒计时顺延
                    self._last_walk = now
                    # 起步即停手:_last_attack_present 可能还被 丢怪保持 撑着 True,
                    # 不作废的话 _do_attack 会一边追一边朝空气轻点攻击键
                    self._last_attack_present = False
```

- [ ] **Step 5: 跑测试确认通过**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 6: 更新 `GETTING_STARTED.md`**

在「丢怪保持(秒)」那一行下面补：

```markdown
| `寻怪起步宽限(秒)` | 0.3 | 区里没怪之后多久允许起步去追。**必须 < 丢怪保持(秒)**,取等 = 修复前行为。攻击键不受影响 |
```

- [ ] **Step 7: 全量单测 + Commit**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py GETTING_STARTED.md
git commit -m "$(cat <<'EOF'
fix: 丢怪保持不再门控寻怪,新增 寻怪起步宽限(秒)=0.3

丢怪保持(1.0s)是为 YOLO 单帧漏检兜攻击键的,那个理由不适用于寻怪:
它把「起步走路」也禁掉了整整一秒。实测 11.5% 的拍卡在这个窗里,
其中 3310 拍屏幕上明明有怪。攻击键本身不受影响(单独去抖),
坐椅/走位仍用长宽限。寻怪定向时作废过期攻击信号,不会边追边挥。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 寻怪去抖 `farm_logic.seek_persist` + 新配置 `寻怪保持(秒)`

治根因 ③（spec §3.3）。攻击侧有 `丢怪保持`，寻怪侧一点去抖都没有 —— 344 段寻怪只有 40.4% 撑过 0.5 秒，其中 105 段(30.5%)起步与取消在同一拍。

**Files:**
- Modify: `src/task/farm_logic.py`（在 `seek_direction` 之后新增）
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG`、`config_description`、`_reset_state`、`_detect_and_act`）
- Modify: `GETTING_STARTED.md`
- Test: `tests/test_farm_logic.py`, `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `farm_logic.seek_persist(seek_raw, prev_seek, now, last_seen, grace) -> str | None`
  - 新状态 `MapleFarmTask._last_seek_seen`（float | None，`None` = 从没检出过同层怪）
  - 新配置键 `寻怪保持(秒)`，默认 `0.5`

- [ ] **Step 1: 写失败的纯函数测试**

加到 `tests/test_farm_logic.py` 的 `TestFarmLogic` 类里：

```python
    def test_seek_persist_holds_through_a_missed_tick(self):
        # 这一拍检出了 → 直接用这一拍的方向
        self.assertEqual(fl.seek_persist('left', 'right', 100.0, 99.0, 0.5), 'left')
        # 这一拍没检出,但距上次检出还在保持窗内 → 继续按上一拍方向走
        self.assertEqual(fl.seek_persist(None, 'right', 100.3, 100.0, 0.5), 'right')
        # 边界:恰好等于保持窗 → 仍然保持
        self.assertEqual(fl.seek_persist(None, 'right', 100.5, 100.0, 0.5), 'right')
        # 超出保持窗 → 停追
        self.assertIsNone(fl.seek_persist(None, 'right', 100.6, 100.0, 0.5))

    def test_seek_persist_degrades_safely(self):
        # 上一拍本来就没在追 → 没什么可保持的
        self.assertIsNone(fl.seek_persist(None, None, 100.1, 100.0, 0.5))
        # 从没检出过同层怪
        self.assertIsNone(fl.seek_persist(None, 'right', 100.1, None, 0.5))
        # 保持窗 0 = 关掉去抖,退回旧行为(一拍判失立刻停)
        self.assertIsNone(fl.seek_persist(None, 'right', 100.0, 100.0, 0.0))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v 2>&1 | tail -20
```
Expected: FAIL —— `has no attribute 'seek_persist'`

- [ ] **Step 3: 写纯函数**

加到 `src/task/farm_logic.py` 的 `seek_direction` 之后：

```python
def seek_persist(seek_raw, prev_seek, now, last_seen, grace):
    """寻怪去抖:同层怪这一拍没检出,但距上次检出还在 grace 内 → 继续按上一拍方向走。

    攻击侧早有 丢怪保持(mob_present_debounced),寻怪侧一直没有:2026-08-08 实测
    344 段寻怪只有 40.4% 撑过 0.5 秒,其中 105 段(30.5%)起步与取消发生在同一拍
    (持续中位 0.00s)——游戏里看就是原地抽搐。怪会跳、YOLO 框高每拍都在抖,
    一拍判失就 send_key_up,角色根本走不出去(spec §2.2 / §3.3)。

    grace <= 0 → 关掉去抖,退回「一拍判失立刻停」的旧行为。
    prev_seek=None(上一拍没在追)或 last_seen=None(从没检出过同层怪)→ 不保持。
    """
    if seek_raw is not None:
        return seek_raw
    if grace <= 0 or prev_seek is None or last_seen is None:
        return None
    return prev_seek if now - last_seen <= grace else None
```

- [ ] **Step 4: 跑测试确认通过**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 5: 写接线的失败测试**

加到 `tests/test_farm_task_offline.py` 末尾：

```python
class TestSeekPersistWiring(unittest.TestCase):
    """寻怪去抖的接线(spec §3.3)。几何同 TestSeekNotBlockedByAttackGrace。"""

    def _task(self, **cfg):
        return make_task(**{'攻击模式': '检测', '寻怪开关': True,
                            '丢怪保持(秒)': 1.0, '寻怪起步宽限(秒)': 0.3,
                            '寻怪保持(秒)': 0.5, **cfg})

    @staticmethod
    def _far_mob():
        return SimpleNamespace(x=2160, y=592, width=80, height=80)

    def test_keeps_walking_when_one_tick_misses_the_mob(self):
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')
        # 下一拍 YOLO 一只都没检出 → 仍按上一拍方向走
        task.find_mobs = MagicMock(return_value=[])
        task._detect_and_act(_synthetic_frame(), 1000.3, task.config, KEYS)
        self.assertEqual(task._seek_dir, 'right')

    def test_gives_up_after_the_grace_expires(self):
        task = self._task()
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        task.find_mobs = MagicMock(return_value=[])
        task._detect_and_act(_synthetic_frame(), 1000.6, task.config, KEYS)
        self.assertIsNone(task._seek_dir)

    def test_grace_zero_restores_old_behaviour(self):
        task = self._task(**{'寻怪保持(秒)': 0.0})
        task.find_mobs = MagicMock(return_value=[self._far_mob()])
        task._detect_and_act(_synthetic_frame(), 1000.0, task.config, KEYS)
        task.find_mobs = MagicMock(return_value=[])
        task._detect_and_act(_synthetic_frame(), 1000.1, task.config, KEYS)
        self.assertIsNone(task._seek_dir)

    def test_default_is_below_the_attack_grace(self):
        # 追错方向的代价高于挥空刀,不该保持得比丢怪保持还久
        self.assertEqual(DEFAULT_CONFIG['寻怪保持(秒)'], 0.5)
        self.assertLess(DEFAULT_CONFIG['寻怪保持(秒)'], DEFAULT_CONFIG['丢怪保持(秒)'])
```

- [ ] **Step 6: 接线**

`DEFAULT_CONFIG` 里，`'寻怪起步宽限(秒)': 0.3,` 之后加：

```python
    '寻怪保持(秒)': 0.5,
```

`config_description` 里加：

```python
            '寻怪保持(秒)': '追怪途中同层怪这一拍没检出,还按上一拍的方向继续走多久。攻击侧早有「丢怪保持」,寻怪侧一直没有:2026-08-08 实测 344 段寻怪只有 40.4% 撑过 0.5 秒,其中 105 段(30.5%)起步与取消发生在同一拍——怪会跳、YOLO 框高每拍都在抖,一拍判失就松键,角色在原地抽搐而不是走过去。默认 0.5:小于「丢怪保持」的 1.0(追错方向的代价高于挥空刀,不该保持那么久),又大于两个空闲检测拍(0.3×2,一拍漏检兜得住);按行走速度 250 像素/秒算,最坏盲走 125 像素。设 0 = 关掉去抖,退回一拍判失立刻停',
```

`_reset_state` 里，`self._seek_dir = None` 那一组附近加：

```python
        self._last_seek_seen = None   # 上次真检出同层怪的时刻;None=从未检出(寻怪去抖用)
```

`_detect_and_act` 的寻怪分支改成（替换原 `self._seek_dir = farm_logic.seek_direction(...)` 那一段）：

```python
            if cfg['寻怪开关']:
                entries = [(m.x + m.width / 2, m.y + m.height) for m in mobs]
                seek_raw = farm_logic.seek_direction(entries, body[0], anchor_hit.y,
                                                     cfg['寻怪同层容差(像素)'], prev_seek)
                if seek_raw is not None:
                    self._last_seek_seen = now
                # 去抖:一拍判失不松键(见 farm_logic.seek_persist)
                self._seek_dir = farm_logic.seek_persist(
                    seek_raw, prev_seek, now, self._last_seek_seen,
                    cfg['寻怪保持(秒)'])
                if self._seek_dir is not None:
                    self._last_walk = now
                    self._last_attack_present = False
```

- [ ] **Step 7: 跑测试确认通过**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline tests.test_farm_logic -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 8: 更新 `GETTING_STARTED.md` + 全量单测 + Commit**

在「寻怪起步宽限(秒)」下面补：

```markdown
| `寻怪保持(秒)` | 0.5 | 追怪途中一拍没检出同层怪,还按原方向走多久。0 = 修复前行为(一拍判失立刻停) |
```

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
git add src/task/farm_logic.py src/task/MapleFarmTask.py tests/ GETTING_STARTED.md
git commit -m "$(cat <<'EOF'
fix: 寻怪补去抖——攻击侧一直有,寻怪侧一直没有

新配置 寻怪保持(秒)=0.5。344 段寻怪只有 40.4% 撑过 0.5 秒,
105 段(30.5%)起步与取消发生在同一拍(持续 0.00s)。怪会跳、YOLO 框高每拍都抖,
一拍判失就 send_key_up,角色在原地抽搐而不是走过去。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 同层判据并入接敌区，退休 `寻怪同层容差(像素)`

治根因 ④（spec §2.3 / §3.4）。这是**风险最高的一个任务**（spec §6 里唯一没有「调回默认即旧行为」退路的），所以排在最后，且带独立的实机数据门与截图验收。

**Files:**
- Modify: `src/task/farm_logic.py`（`seek_direction` 签名，`same_floor` 视情况删除）
- Modify: `src/task/MapleFarmTask.py`（`DEFAULT_CONFIG`、`config_description`、`_detect_and_act`、`_log_decision`、`decision_log_line`）
- Modify: `GETTING_STARTED.md`
- Test: `tests/test_farm_logic.py`（重写 ~10 个用例）, `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: `farm_logic.attack_zone`（已有）
- Produces: `farm_logic.seek_direction(centres, body_x, zone, current_dir=None) -> str | None`
  - **破坏性变更**：`(mob_entries, body_x, player_feet_y, tolerance, current_dir)` → `(centres, body_x, zone, current_dir)`
  - `centres`: `[(中心x, 中心y), ...]` —— 从「怪脚底 y」改成「怪中心 y」
  - `zone`: 接敌区 `(x0, y0, x1, y1)`，只用它的 `y0/y1`
- 退休：配置键 `寻怪同层容差(像素)`；日志字段 `同层脚=`

- [ ] **Step 1: 先过数据门（不写码）**

Task 1 的字段已经跑过实机才能做这一步。开 `决策日志开关` 挂机 **≥10 分钟**，然后：

```bash
grep '决策 src=' logs/ok-script.log | grep -o '同层脚=[0-9]* 同层心=[0-9]*' | sort | uniq -c | sort -rn | head -20
```

**门槛**：必须看到相当数量的 `同层脚=0 同层心=N(N>0)` 组合 —— 那正是 spec §2.3 推导的「攻击区罩得到却判不同层」的带。**如果几乎没有这种组合**，说明根因 ④ 在真实场景下不成立，**停下来把结论写进 spec §2.3，跳过本任务**，不要为了执行计划而改代码。

同时开 GUI 的「启用标记框」截一张图存 `screenshots/e2e/seek_same_floor/`，肉眼确认 `同层心` 多出来的那些怪确实站在**同一个平台**上，而不是上下层。

- [ ] **Step 2: 重写 `tests/test_farm_logic.py` 里的同层/寻怪用例**

删除 `test_same_floor_within_tolerance` / `test_same_floor_beyond_tolerance`，并把 `seek_direction` 相关的全部用例（原第 251-273、321-336 行附近）替换为：

```python
    # 接敌区:body=(1280, 800),宽 1007 高 200 → 水平 [776.5, 1783.5],纵向 [700, 900]
    ZONE = (776.5, 700.0, 1783.5, 900.0)

    def test_seek_direction_uses_the_zone_vertical_range(self):
        """同层 = 怪中心落在接敌区纵向范围内,与 mob_in_zone 完全同口径。

        旧口径「怪脚底 vs 名字牌 y,容差 60」与接敌区「怪中心 vs 身体中心,
        半高 100」两个基准两个量,不管怪多高 120 恒小于 200,必然存在一条
        「攻击区罩得到却判不同层」的带(spec §2.3)。"""
        self.assertEqual(fl.seek_direction([(400.0, 700.0)], 1280.0, self.ZONE), 'left')
        self.assertEqual(fl.seek_direction([(2200.0, 900.0)], 1280.0, self.ZONE), 'right')
        # 纵向出了接敌区 = 另一层,走过去也打不到 → 不追
        self.assertIsNone(fl.seek_direction([(400.0, 699.0)], 1280.0, self.ZONE))
        self.assertIsNone(fl.seek_direction([(400.0, 901.0)], 1280.0, self.ZONE))

    def test_seek_direction_picks_nearest_same_floor_mob(self):
        entries = [(400.0, 800.0), (2400.0, 800.0)]
        self.assertEqual(fl.seek_direction(entries, 1000.0, self.ZONE), 'left')
        self.assertEqual(fl.seek_direction(entries, 2000.0, self.ZONE), 'right')

    def test_seek_direction_empty_and_all_other_floors(self):
        self.assertIsNone(fl.seek_direction([], 1280.0, self.ZONE))
        self.assertIsNone(fl.seek_direction([(400.0, 300.0), (2400.0, 1300.0)],
                                            1280.0, self.ZONE))

    def test_seek_direction_locks_onto_current_side(self):
        """方向锁定:那一侧还有同层怪就继续追,不因对侧刷出更近的怪而掉头
        (寻怪刷新间隔可低至 0.1s,没有锁定会原地左右横跳且全程不攻击)。"""
        entries = [(1200.0, 800.0), (2400.0, 800.0)]   # 左边更近,右边更远
        self.assertEqual(
            fl.seek_direction(entries, 1280.0, self.ZONE, current_dir='right'), 'right')
        # 右侧真空了才换边
        self.assertEqual(
            fl.seek_direction([(1200.0, 800.0)], 1280.0, self.ZONE, current_dir='right'),
            'left')
        # 没在追 → 按最近怪定向
        self.assertEqual(
            fl.seek_direction(entries, 1280.0, self.ZONE, current_dir=None), 'left')
```

- [ ] **Step 3: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_logic -v 2>&1 | tail -20
```
Expected: FAIL —— 旧签名收到的第三个参数是 tuple 而非 float

- [ ] **Step 4: 改 `seek_direction`**

替换 `src/task/farm_logic.py` 里的整个函数：

```python
def seek_direction(centres, body_x, zone, current_dir=None):
    """自动寻怪要按的方向:同层怪中离身体水平距离最近的一个,
    在左 → 'left',在右 → 'right';没有同层怪 → None。
    centres: [(中心x, 中心y), ...] 全部怪。调用方保证当前攻击区内无怪
    (区内的早已被攻击分支原地处理,本函数只服务"区外寻怪")。

    同层 = 怪中心落在接敌区的纵向范围内 —— 与 mob_in_zone 完全同口径。
    语义因此自洽:**寻怪 = 走过去就打得到、但现在水平够不着的怪**。

    旧版用「怪脚底 y vs 名字牌 y,容差 寻怪同层容差」,与接敌区的
    「怪中心 y vs 身体中心 y,半高 攻击区高/2」两个基准两个量。换算到同一
    坐标系后,同层窗宽 120 恒小于接敌区窗宽 200(与怪多高无关),必然存在
    一条「攻击区罩得到却判不同层」的纵向带;以怪高 80 计占接敌区纵向的 44%。
    2026-08-08 实测屏幕上有怪却既不打也不追的拍占 20.1%(spec §2.3)。

    current_dir = 上一拍的寻怪方向时带方向锁定:那一侧还有同层怪就继续追,
    不因为对侧刷出更近的怪而掉头。寻怪刷新间隔可低至 0.1s,没有锁定时
    追怪途中会被对侧目标反复拽回来,原地左右横跳且全程不攻击
    (219 帧重放实测该分支方向翻转 8/28)。None = 未在寻怪,按最近怪定向。
    """
    y0, y1 = zone[1], zone[3]
    same_floor_xs = [cx for cx, cy in centres if y0 <= cy <= y1]
    if not same_floor_xs:
        return None
    if current_dir in ('left', 'right') and any(
            _on_side(cx, body_x, current_dir) for cx in same_floor_xs):
        return current_dir
    nearest = min(same_floor_xs, key=lambda cx: abs(cx - body_x))
    return 'left' if nearest < body_x else 'right'
```

然后确认 `same_floor` 是否还有调用方；没有就连同它的文档一起删掉（不留死代码）：

```bash
grep -rn "same_floor" src/ scripts/ tests/
```

- [ ] **Step 5: 改接线（`_detect_and_act`）**

寻怪分支里，`entries` 从脚底改成中心，并改传 `zone`：

```python
            if cfg['寻怪开关']:
                # 同层判据与接敌区同口径:传怪中心 + 接敌区,不再用「脚底 vs 名字牌」
                seek_raw = farm_logic.seek_direction(centres, body[0], zone, prev_seek)
                if seek_raw is not None:
                    self._last_seek_seen = now
                self._seek_dir = farm_logic.seek_persist(
                    seek_raw, prev_seek, now, self._last_seek_seen,
                    cfg['寻怪保持(秒)'])
                if self._seek_dir is not None:
                    self._last_walk = now
                    self._last_attack_present = False
```

（`centres` 在本函数上文已经算好，就是 `[(m.x + m.width / 2, m.y + m.height / 2) for m in mobs]`，不需要新变量。）

- [ ] **Step 6: 退休 `寻怪同层容差(像素)` 与 `同层脚=` 字段**

- `DEFAULT_CONFIG` 删掉 `'寻怪同层容差(像素)': 60,`
- `config_description` 删掉对应那条
- `decision_log_line`：删掉 `same_feet` 参数与 `同层脚={same_feet} ` 片段，`同层心=` 改名为 `同层=`（口径只剩一个了，不需要再区分）
- `_log_decision`：删掉 `tol` / `same_feet` 的计算，`same_center` 改名 `same_n`
- `tests/test_farm_task_offline.py::TestDecisionLogVerticalFields` 与 `tests/test_analyze_seek.py::line()` / `tests/test_analyze_facing.py::dec()`：同步去掉 `same_feet`
- `scripts/analyze_seek.py` 的 `DEC` 正则：可选组改成 `(?:同层=(\d+) 近怪dx=\S+ dy脚=\S+ dy心=\S+ )?`，`parse` 里 `same_feet` 键删除、`same_center` 改名 `same_n`。**老日志与 Task 1-6 期间的日志仍要能解析** —— 加一条兼容分支或第二个正则，并在 `tests/test_analyze_seek.py` 里为「Task 1 格式的旧行」补一个用例

⚠️ 用户现有的 `configs/MapleFarmTask.json` 里会残留 `寻怪同层容差(像素)` 键，无害（`config` 是普通 dict，多余键不参与任何分支），无需迁移。

- [ ] **Step 7: 全量单测**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```
Expected: `OK`，测试总数不低于 Task 6 结束时

- [ ] **Step 8: E2E 截图验收（AGENTS.md §11.3 铁律）**

按 AGENTS.md §11.5 的流程：停掉旧 GUI → 启动 `main_debug.py` → 开「自动打怪」+「启用标记框」→ 截图存 `screenshots/e2e/seek_same_floor/seek_zone_<日期>.png` → 用 vision-capable 模型核对：**接敌区框（细线）纵向范围内的怪，是不是都是角色走得过去的同一平台的怪**。验收结论写进本计划的 Task 7 下方。

- [ ] **Step 9: Commit**

```bash
git add src/task/farm_logic.py src/task/MapleFarmTask.py scripts/analyze_seek.py tests/ GETTING_STARTED.md
git commit -m "$(cat <<'EOF'
fix: 同层判据并入接敌区,退休 寻怪同层容差(像素)

旧版「怪脚底 vs 名字牌 y,容差 60」与接敌区「怪中心 vs 身体中心,半高 100」
两个基准两个量。换算到同一坐标系后同层窗宽恒小于接敌区窗宽(与怪高无关),
必然存在一条「攻击区罩得到却判不同层」的带,以怪高 80 计占纵向 44%。
现在寻怪 = 走过去就打得到、但水平够不着的怪,语义自洽,零旋钮。
seek_direction 破坏性签名变更,10 个用例重写。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 实弹验收 + 归档

**Files:**
- Modify: `docs/superpowers/specs/2026-08-08-seek-latency-design.md`（新增 §8 实弹结果）
- Modify: `AGENTS.md`（§11.7 基线更新）

- [ ] **Step 1: 准备**

确认 `configs/MapleFarmTask.json` 里 `决策日志开关: true`；三个新配置留默认（`空闲刷新间隔=0.3`、`寻怪起步宽限=0.3`、`寻怪保持=0.5`）。记下开跑时刻。

⚠️ **改过 `farm_logic.py`，必须重启 GUI**（Global Constraints）。

- [ ] **Step 2: 挂机 ≥20 分钟**

同一张图、同一个刷怪点，尽量与基线快照的场景一致。中途不要改配置。

- [ ] **Step 3: 复算判据**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/analyze_seek.py --since <开跑时刻 HH:MM:SS>
```

- [ ] **Step 4: 逐条对照 spec §5，把实际值填进下表**

| 判据 | 基线 | 通过线 | 实测 | 结论 |
|---|---|---|---|---|
| A 停手→起步 中位/p90 | 1.19s / 3.61s | ≤0.50 / ≤1.50 | | |
| B 寻怪段撑过 0.5s | 40.4% | ≥65% | | |
| C 连续空转累计 | 25.2% | ≤12% | | |
| D 可打拍占比 | 41.0% | ≥41.0% | | |
| E 拍间隔 p90/max | 0.946s / 9.78s | ≤0.60 / ≤5.0 | | |
| F 20 分钟内兜底守卫误停 | — | 0 次 | | |

**任一判据不过：记录实际值 + 写清哪一条没过 + 按 spec §6 的对照表选回退项，不许改通过线。**

- [ ] **Step 5: 归档**

把上表与结论写进 spec 新增的 `## 8. 实弹结果（<日期>）`，格式照 `2026-08-08-facing-observer-design.md §8`。同时更新 `AGENTS.md` §11.7 的测试基线数字（测试模块数 / 用例数 / skip 数）。

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-08-08-seek-latency-design.md AGENTS.md
git commit -m "$(cat <<'EOF'
docs: 归档寻敌延迟实弹结果——spec §8 + 基线更新

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec 覆盖**：spec §3.1 → Task 3+4；§3.2 → Task 5；§3.3 → Task 6；§3.4 → Task 7；§2.3 的观测缺口 → Task 1；§5 判据 → Task 2（脚本）+ Task 8（复算）；§6 回退表 → 每个任务的默认值都留了「调回即旧行为」，Task 7 例外并已在其 Step 1 加了数据门。**无遗漏。**

**写计划时踩到、已写进文档的坑**：
- 基线日志里有**两代格式**（今天 `8eb39ce` 才加的 `实测=` / `分值=` 尾巴）。第一版分析用的正则要求新格式的尾巴，**静默丢掉了 78% 的行**。`analyze_seek.py` 的正则三代通吃（已实测验证），Task 2 Step 5 因此必须带 `--since 14:10:00` 才能复现 spec §2.1。
- 带括号的配置键（`丢怪保持(秒)` 等）**不能当 kwargs 传**，全部写成 `make_task(**{...})`。
- 测试几何一律按 `DEFAULT_CONFIG` 算（`名字牌到身体偏移 90`、接敌区 `600x200`），**不是**用户 `configs/MapleFarmTask.json` 里的 88 / 1007x200。

**已知的顺序耦合**（执行时注意）：
- Task 6 的 Step 6 接线里 `seek_direction` 仍是旧签名（传 `entries` / `anchor_hit.y` / `寻怪同层容差`），Task 7 的 Step 5 才改成新签名。这是有意的 —— 两个任务各自可独立回退。
- Task 7 的 Step 6 要回头改 Task 1 的日志字段和 Task 2 的正则。这是「先造尺子、用完再收」的必然代价，已在该步列全清单。
- Task 7 Step 1 是**数据门不是形式**：若实机数据不支持根因 ④，正确做法是把结论写进 spec 并跳过该任务。
