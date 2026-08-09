# 转向后攻击区跟不上 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「转向落地 → 攻击区真的翻到新朝向」的延迟从中位 0.179s 压到 **中位 ≤0.12s**(即打到主循环 tick 底,消掉「等满一个 `攻击间隔`」那一档),且 `corrected_back` / `re_turned` 不得恶化;同时让悬浮窗画的攻击区不再比角色朝向慢一拍。

> **2026-08-09 修订**:初版 Goal 写的是 p90 ≤0.25s / p99 ≤0.5s / >0.5s ≤5%。实弹归因后确认尾部由**丢锚与截图卡死**主导(归 `2026-08-09-player-anchor-yolo-fusion.md`),不是本计划能治的,已降为观察项。判据重心改为 p50 与两项不得恶化的比例,依据见 Task 4 与 §实现记录。

**Architecture:** 两处改动,都在接线层(`src/task/MapleFarmTask.py::_detect_and_act`),**不碰纯逻辑层**(`farm_logic.py` 一行不动)、不碰 CV(`src/detect/*`)。顺序照仓库惯例「先造尺子、再动刀」:Task 1 只加判据脚本(零行为变更),Task 2 治延迟本体,Task 3 治视觉滞后,Task 4 实弹验收。两个改动互相独立,可各自回退。

**Tech Stack:** Python 3.11(嵌入式,`H:\ok-mxd\data\apps\ok-ww\python\python.exe`),unittest。不新增依赖。

**上游 spec:** 无独立 spec —— 改动只有两行,根因与判据写在本文件 §根因 里,数据可直接复现。若日后要归档,§根因 整节可原样抬进 spec。

---

## 根因(2026-08-09 实测,数据源 `logs/ok-script.2026-08-08.log`,26,365 决策拍 / **2,526 次落地转向**)

> **2026-08-09 修订**:本节初版按「`转向=` 不是 `-`」计数,得 3,452 次。那里面有 926 次(26.8%)是「算出了 turn 但键被 转向冷却/硬直抑制窗/窗口失焦 挡下」——`_facing` 根本没变。判据已改用信念 `朝向=f0→f1`(见 Task 1 的 `landed()`),下面所有数字都已按落地口径重算。受影响最大的是 `re_turned`:28.7% → **4.7%**。

### ① 攻击区永远慢一拍 —— 结构性,不是偶发

一个检测拍内的顺序是写死的:

```
MapleFarmTask.py:583   attack_area = facing_half_zone(zone, body[0], self._facing)  ← 用转向前的朝向
MapleFarmTask.py:628   _draw_debug(..., attack_area=attack_area)                     ← 画的也是转向前的
MapleFarmTask.py:648   turn = attack_turn_direction(...)
MapleFarmTask.py:660   self._facing = 'LEFT' if turn == 'left' else 'RIGHT'          ← 到这才翻
```

`:583` 上方的注释(引 spec §5.1)说明这是**故意的**:「拿转向后的新朝向立刻判定等于又一次相信盲写信念」——转向键可能被窗口失焦/击退硬直吞掉,当拍就信它会打空。**本计划不推翻这个决定**,新朝向仍然只在下一拍生效。

### ② 真正的痛点是「下一拍什么时候来」

转向只发生在接战分支(`:648` 在 `if seek_hold:` 内),而那一拍的 `_detect_attacking` 常被 `寻怪起步宽限` 去抖撑着 `True`(`:625-626`),于是 `should_detect` 给下一拍排的是 **`攻击间隔`(0.7s)**。实测转向拍 → 下一拍的间隔分布正好卡在两个配置值上:

```
p50 = 0.319s   ← 空闲刷新间隔 0.3
p90 = 0.706s   ← 攻击间隔 0.7      ★ 这就是肉眼可见的那一档
p99 = 1.158s   max = 11.673s(截图卡死/窗口失焦,非本计划范围)
```

转向 → 攻击区真正翻过去的端到端延迟:

```
n=2359   p50=0.179s   p75=0.487s   p90=0.618s   p99=1.055s   max=7.770s
>0.5s : 20.2%      >0.8s : 2.5%      >1.0s : 1.2%
```

### ③ 已排除的嫌疑:朝向纠正不是主因

原假设是「转向盲写 `_facing`,下一拍观测器看到贴图还没翻,把信念纠正回去」。**数据不支持,不要照这个方向改**:结算前被观测器纠正回旧朝向的只有 **49 / 2526 = 1.9%**。

另有 4.7% 是「攻击区还没翻过来就又转了一次」,那是 `attack_turn_direction` 目标侧锁定的正常行为,不在本计划范围。

> 这条假设在 Task 4 实弹里被**再次验证**:Task 2 把下一拍从 ~0.7s 提前到 ~0.1s,理论上给贴图翻转留的时间更少、纠正回写的风险更大,但实测 `corrected_back` 反而降到 0.6%。不需要给朝向纠正加静默窗。

### 结论

不动 `:583` 的判定顺序(理由 ① 仍成立),改成**转向落地后作废检测节拍**,让下一拍立刻到来(主循环 10Hz → ~0.1s),而不是等满一个 `攻击间隔`。下一拍是真正重新观测过的,不需要相信任何盲写信念。

---

## Global Constraints

- **Python 只能用** `H:\ok-mxd\data\apps\ok-ww\python\python.exe`,**禁止 `pip install`**(嵌入式解释器,装不了也不许装)
- **测试命令**:`PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests`。**不是 pytest**,没装
- **当前基线:`Ran 415 tests in 8.063s / OK (skipped=10)`**(2026-08-09 实测)。任何任务结束时必须仍然全绿,**测试总数只增不减**
- **跑测试前先确认 `screenshots/test_frames/` 还在**:每次启动 GUI 都会清空 `screenshots/`(日志 `Screenshot:clear`)。测试帧丢了 skip 数会从 10 往上涨,那不是回归
- **禁止绝对路径**(AGENTS.md §11.1)。所有路径相对仓库根 `H:\ok-mxd\ok-mxd`
- **决策日志格式的唯一事实源是 `MapleFarmTask.decision_log_line`。** 测试里**禁止手抄格式字符串** —— 2026-08-08 评审坐实过假绑定(手抄格式,改字段名后 15 个「绑定」测试全过,commit 9016133)。样本行一律调真实格式函数构造
- **日志文件按天轮转**:当天的是 `logs/ok-script.log`,昨天的是 `logs/ok-script.<date>.log`。分析脚本默认吃当天那个,过夜跑分析要显式传文件名
- **日志编码是 UTF-8**(不是 GBK)。Python 读取一律 `encoding='utf-8'`;控制台是 cp936,**脚本的输出标签走 ASCII**,否则终端乱码
- 中文注释 / 中文日志,与现有代码风格一致
- **每个 Task 结束必须 commit**,一个 Task 一个提交,便于单独回退

---

### Task 1: 判据脚本 `scripts/analyze_turn.py`(零行为变更)

先造尺子。Task 4 的验收、以及日后回归都要靠它,不能靠人眼看悬浮窗。

**Files:**
- Create: `scripts/analyze_turn.py`
- Test: `tests/test_analyze_turn.py`(新建)

**Interfaces:**
- Consumes: `logs/ok-script*.log` 的决策行;格式绑定通过调用 `MapleFarmTask.decision_log_line` 构造样本
- Produces:
  - `analyze_turn.scan(lines) -> dict`,键:
    - `beats: int` 解析到的决策拍数
    - `turns: int` 发出转向的拍数
    - `latencies: list[float]` 每次转向到「结算拍」的秒数
    - `outcome: dict[str, int]` 五种结局计数,键固定为
      `'settled'` / `'re_turned'` / `'corrected_back'` / `'never_settled'` / `'truncated'`
      (2026-08-09 修订:`truncated` = 日志末尾不足 40 拍,结局无从判断,见 Step 4 修订说明)
    - `gaps: list[float]` 转向拍到紧接下一拍的间隔

**语义定义(实现时不许改):**
- **转向拍** = 决策行中 `转向=` 不是 `-` **且信念确实翻了(`朝向=f0→f1` 中 `f0 != f1`)**
  - 2026-08-09 修订。初版只看 `转向=` 字段是**错的**:`_detect_and_act:645` 无条件赋值 `turn`,之后才用 转向冷却/硬直抑制窗/`_key_sendable` 门控实际按键(`:646-654`),`_log_decision` 收的是那个无条件值 —— 键被挡下、`_facing` 没变,日志照样写 `转向=left`。实测 08-08 日志里 26.8% 属于这种
  - 这个坑 `scripts/analyze_facing.py:11-13` 早就记过,判据 B 因此改用信念判定。**照抄那条经验,不要再用字段计数**
  - 已知残留:先被朝向纠正翻一次、再转回原朝向的拍会出现 `f0==f1` 而被漏掉。`analyze_facing` 接受同一限制,不必另起炉灶
- **结算拍** = 该转向拍之后第一个满足「`转向=-` 且 `朝向=F→F` 且 `F` == 转向后的新朝向」的拍。`朝向=A→B` 中 A 是纠正前信念、B 是本拍结束信念,两者相等才说明这一拍的攻击区确实是用新朝向算的
- 结算之前先遇到 `转向≠-` → 计 `re_turned`,不计延迟(它是目标侧锁定的正常行为,不是缺陷)
- 结算之前先遇到 `朝向=F→非F` → 计 `corrected_back`
- 40 拍内没结算 → 计 `never_settled`

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_analyze_turn.py`:

```python
# -*- coding: utf-8 -*-
"""analyze_turn 的解析与统计绑定。

格式绑定必须调 decision_log_line 真实构造样本行 —— 手抄格式字符串是假绑定
(2026-08-08 评审坐实过,commit 9016133)。
"""
import importlib.util
import os
import unittest

from src.task.MapleFarmTask import decision_log_line

# scripts/ 不是包(没有 __init__.py),按 tests/test_analyze_seek.py 同款方式加载
_SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'analyze_turn.py')
_SPEC = importlib.util.spec_from_file_location('analyze_turn', _SCRIPT)
analyze_turn = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analyze_turn)


def line(ts, facing_before, facing_now, turn):
    """用真实格式函数造一条带时间戳前缀的决策行。"""
    body = decision_log_line(
        source='window', body_x=1280, anchor_y=800, centres=[], in_zone=[], left=0,
        same_feet=0, same_center=0, near=None,
        raw_present=False, mob_present=False, attack_in=[], attack_present=False,
        facing_before=facing_before, facing_now=facing_now, turn=turn,
        seek_dir=None, key_sendable=True, observed=None, obs_s=0.0, obs_flip=0.0)
    return f'2026-08-09 {ts} DEBUG TaskExecutor MapleFarmTask:{body}\n'


class TestAnalyzeTurn(unittest.TestCase):

    def test_settled_latency_is_turn_to_first_stable_new_facing_beat(self):
        """转向拍 → 第一个 朝向=新→新 且没再转向的拍,延迟取两者时间差。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'RIGHT', None),
            line('10:00:00,700', 'RIGHT', 'LEFT', 'left'),    # 转向拍
            line('10:00:00,800', 'LEFT', 'LEFT', None),       # 结算拍
        ])
        self.assertEqual(out['turns'], 1)
        self.assertEqual(out['outcome']['settled'], 1)
        self.assertAlmostEqual(out['latencies'][0], 0.1, places=3)

    def test_re_turn_before_settling_is_not_counted_as_latency(self):
        """结算前又转了一次 → 记 re_turned,不污染延迟分布。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),
            line('10:00:00,300', 'LEFT', 'RIGHT', 'right'),
        ])
        self.assertEqual(out['outcome']['re_turned'], 1)
        self.assertEqual(out['latencies'], [])

    def test_corrected_back_by_observer(self):
        """结算前信念被纠正回旧朝向 → 记 corrected_back。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),
            line('10:00:00,300', 'LEFT', 'RIGHT', None),
        ])
        self.assertEqual(out['outcome']['corrected_back'], 1)
        self.assertEqual(out['latencies'], [])

    def test_gap_is_turn_beat_to_the_very_next_beat(self):
        """gaps 量的是节拍本身,与结算与否无关 —— 它才是 攻击间隔 的直接证据。"""
        out = analyze_turn.scan([
            line('10:00:00,000', 'RIGHT', 'LEFT', 'left'),
            line('10:00:00,706', 'LEFT', 'LEFT', None),
        ])
        self.assertAlmostEqual(out['gaps'][0], 0.706, places=3)

    def test_non_decision_lines_ignored(self):
        out = analyze_turn.scan([
            '2026-08-09 10:00:00,000 INFO TaskExecutor MapleFarmTask:随便一行\n',
            line('10:00:01,000', 'RIGHT', 'RIGHT', None),
        ])
        self.assertEqual(out['beats'], 1)
        self.assertEqual(out['turns'], 0)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_analyze_turn -v 2>&1 | tail -20
```
Expected: FAIL —— `FileNotFoundError` / `No such file or directory: '...scripts/analyze_turn.py'`(脚本还没建)

> `scripts/` 不是包,**不要**为此新建 `__init__.py`;上面的 `spec_from_file_location` 就是仓库现有惯例(`tests/test_analyze_seek.py:16-20`)。

- [ ] **Step 3: 写实现**

新建 `scripts/analyze_turn.py`:

```python
# -*- coding: utf-8 -*-
"""转向后攻击区跟上的延迟 —— 修复前后的同一把尺子。

攻击区是按本拍转向**之前**的朝向算的(MapleFarmTask.py:583,spec §5.1),
新朝向要下一拍才生效。所以这里量的不是"攻击区算错了",而是
"下一拍隔了多久才来"。判据与语义写死在 plans/2026-08-09-turn-zone-latency.md,
不许在本脚本里改。

用法: python scripts/analyze_turn.py [日志文件]
      默认 logs/ok-script.log(当天);日志按天轮转,查昨天要显式传文件名。
输出标签一律 ASCII:控制台是 cp936,中文会乱码。
"""
import re
import sys

LOG = 'logs/ok-script.log'
MAX_LOOKAHEAD = 40   # 40 拍还没结算就当没结算,避免一次异常拖垮整个分布

TS = re.compile(r'^\d{4}-\d\d-\d\d (\d\d):(\d\d):(\d\d),(\d{3})')
DEC = re.compile(r'决策 src=(\S+) .*?朝向=(\S+)→(\S+) 转向=(\S+) 寻怪=(\S+) '
                 r'可发键=(\w+) 实测=(\S+) 分值=')


def _seconds(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
            + int(m.group(3)) + int(m.group(4)) / 1000)


def parse(lines):
    """行 → 决策拍列表 [{t, src, f0, f1, turn}]。非决策行直接跳过。"""
    rows = []
    for line in lines:
        ts, dec = TS.match(line), DEC.search(line)
        if ts and dec:
            rows.append(dict(t=_seconds(ts), src=dec.group(1),
                             f0=dec.group(2), f1=dec.group(3), turn=dec.group(4)))
    return rows


def scan(lines):
    """算统计。语义见计划文档 Task 1,四种结局互斥且必然命中其一。"""
    rows = parse(lines)
    out = dict(beats=len(rows), turns=0, latencies=[], gaps=[],
               outcome=dict(settled=0, re_turned=0, corrected_back=0, never_settled=0))
    for i, row in enumerate(rows):
        if row['turn'] == '-':
            continue
        out['turns'] += 1
        new = row['f1']
        if i + 1 < len(rows):
            out['gaps'].append(rows[i + 1]['t'] - row['t'])
        for j in range(i + 1, min(i + 1 + MAX_LOOKAHEAD, len(rows))):
            nxt = rows[j]
            if nxt['turn'] != '-':
                out['outcome']['re_turned'] += 1
                break
            if nxt['f0'] == new and nxt['f1'] == new:
                out['outcome']['settled'] += 1
                out['latencies'].append(nxt['t'] - row['t'])
                break
            if nxt['f1'] != new:
                out['outcome']['corrected_back'] += 1
                break
        else:
            out['outcome']['never_settled'] += 1
    return out


def _q(values, p):
    return values[min(len(values) - 1, int(len(values) * p))]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else LOG
    with open(path, encoding='utf-8', errors='ignore') as f:
        out = scan(f)
    print(f'log        : {path}')
    print(f'beats      : {out["beats"]}')
    print(f'turn beats : {out["turns"]}')
    if not out['turns']:
        return
    print('\n== outcome after each turn ==')
    for k, v in out['outcome'].items():
        print(f'  {k:<16} {v:>6}  ({100 * v / out["turns"]:5.1f}%)')
    lat = sorted(out['latencies'])
    if lat:
        print('\n== latency: turn -> first beat whose zone uses the NEW facing ==')
        print(f'  n={len(lat)}  p50={_q(lat, .5):.3f}s  p75={_q(lat, .75):.3f}s  '
              f'p90={_q(lat, .9):.3f}s  p99={_q(lat, .99):.3f}s  max={lat[-1]:.3f}s')
        for thr in (0.25, 0.5, 0.8, 1.0):
            n = sum(1 for x in lat if x > thr)
            print(f'  > {thr}s : {n:>5}  ({100 * n / len(lat):5.1f}%)')
    gaps = sorted(out['gaps'])
    if gaps:
        print('\n== gap: turn beat -> the very next beat ==')
        print(f'  p50={_q(gaps, .5):.3f}s  p90={_q(gaps, .9):.3f}s  '
              f'p99={_q(gaps, .99):.3f}s  max={gaps[-1]:.3f}s')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 跑测试确认通过 + 对历史日志跑一遍**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_analyze_turn -v 2>&1 | tail -10
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/analyze_turn.py logs/ok-script.2026-08-08.log
```

Expected:测试 PASS;脚本对 2026-08-08 日志的输出必须**复现下面这组基线数**(误差 ≤1 拍),否则解析写错了,不许往下做:

```
turn beats : 3452
settled  2407 (69.7%)   re_turned  989 (28.7%)   corrected_back  55 (1.6%)   never_settled  0 (0.0%)   truncated(40拍内日志到头)  1
latency  p50=0.212  p75=0.488  p90=0.627  p99=1.103  max=11.673
gap      p50=0.319  p90=0.706  p99=1.158
```

> **2026-08-09 修订**:初版把那条 `never_settled: 1` 当成真没结算,实为文件末尾
> 那拍正好是转向拍(索引 26364)被 `for...else` 误判。修复后单列 `truncated`
> 结局(日志在本拍之后不足 40 拍就到底,结局无从判断),百分比分母改为
> `turns - truncated`,结尾转向拍不再污染通过线。语义定义里的结局键由此变为
> 五个:`settled` / `re_turned` / `corrected_back` / `never_settled` / `truncated`。

- [ ] **Step 5: Commit**

```bash
git add scripts/analyze_turn.py tests/test_analyze_turn.py
git commit -m "$(cat <<'EOF'
feat: 转向延迟判据脚本 analyze_turn —— 先造尺子再动刀

量「转向落地 → 攻击区真的用上新朝向」的延迟。2026-08-08 基线:
p90=0.627s / p99=1.103s,>0.5s 占 21.5%;转向拍到下一拍的间隔
p90=0.706s，正好一个攻击间隔。零行为变更。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 转向落地 → 作废检测节拍(本计划的主改动)

**Files:**
- Modify: `src/task/MapleFarmTask.py`(`_detect_and_act` 的转向块,`:658-663` 附近)
- Test: `tests/test_farm_task_offline.py`

**Interfaces:**
- Consumes: 已有的 `self._last_detect`(`run()` 在 `:993` 先写 `now` 再调 `_detect_and_act`,所以在 `_detect_and_act` 里改它一定生效)
- Produces: 无新接口。`_last_detect = 0.0` 沿用 `_reset_state` 里同一个「从未检测过」哨兵

- [ ] **Step 1: 写失败的测试**

加到 `tests/test_farm_task_offline.py`,紧跟在 `test_detect_cadence_stays_at_attack_rate_while_mob_in_zone` 之后(第 534 行后):

```python
    def test_turn_invalidates_detect_cadence(self):
        """转向落地 → 作废检测节拍,下一拍不再按 攻击间隔 等。

        攻击区是按本拍转向**之前**的朝向算的(:583 的 spec §5.1 注释,本计划
        不推翻),新朝向要下一拍才生效;而转向只发生在接战分支,那一拍
        _detect_attacking 常被 寻怪起步宽限 撑着 True → 下一拍按 攻击间隔 排,
        攻击区因此要等 0.7s 才翻过去。2026-08-08 实弹:端到端延迟 p90=0.627s、
        p99=1.103s,转向拍到下一拍的间隔 p90=0.706s(正好一个攻击间隔)。

        寻怪起步宽限 调到 1.0 是为了把「节拍仍在攻击档」这个前提坐实
        (默认 0.3 时 100.7 已出宽限,会退化成空闲档,测不到最坏情况)。
        变异验证:删掉实现里的 `self._last_detect = 0.0`,本用例转红。
        """
        task = make_task(**{'攻击模式': '检测', '攻击间隔(秒)': 0.7,
                            '寻怪起步宽限(秒)': 1.0})
        task._facing = 'RIGHT'
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')):
            # 100.0 面朝右、右侧有怪:在打
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=1500, y=700, width=60, height=50)])
            run_with_frame(task)
            self.assertTrue(task._last_attack_present)   # 前提
            # 100.7 怪换到左侧:发左转向。此拍 _detect_attacking 仍被 1.0s 宽限撑着,
            # 攻击区还锚在右半边(本拍决策照旧,这是设计)
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=960, y=700, width=60, height=50)])
            run_with_frame(task, now=100.7)
            self.assertEqual(task._facing, 'LEFT')
            self.assertTrue(task._detect_attacking)      # 前提:节拍仍在攻击档
            # 100.8 距上一拍仅 0.1s < 攻击间隔 —— 修复前这一拍根本不跑检测
            run_with_frame(task, now=100.8)
        self.assertEqual(task._last_detect, 100.8)       # 检测拍真的跑了
        self.assertTrue(task._last_attack_present)       # 攻击区已翻到左半边,罩住了怪
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v 2>&1 | tail -20
```
Expected: FAIL —— `AssertionError: 100.7 != 100.8`(第三拍被 `攻击间隔` 挡掉,没跑检测)

- [ ] **Step 3: 写实现**

`src/task/MapleFarmTask.py`,在转向块里 `self._last_walk = now` 之后追加两行注释 + 一行代码:

```python
                key = '左移键' if turn == 'left' else '右移键'
                self.send_key(keys[key], down_time=TURN_TAP_SECONDS)
                self._last_turn = now
                self._facing = 'LEFT' if turn == 'left' else 'RIGHT'
                # 转向本身就是"活动":走位倒计时从头算,不紧跟着又走位
                # (刚转完向立刻两段走位会显得很怪;且正在打怪就不是挂机闲逛)
                self._last_walk = now
                # 作废检测节拍,让下一拍立刻来。攻击区是按转向「前」的朝向算的
                # (见上面 :583 的 spec §5.1 注释,那个决定不变),新朝向要下一拍
                # 才生效;而转向只发生在接战分支,那一拍 _detect_attacking 常被
                # 寻怪起步宽限 撑着 True,下一拍就按 攻击间隔(0.7s)排 ——
                # 攻击区因此要等满一个攻击拍才翻过去(2026-08-08 实测端到端
                # p90=0.627s、>0.5s 占 21.5%,转向拍到下一拍间隔 p90=0.706s)。
                # 0.0 是 _reset_state 同款「从未检测过」哨兵:下一次主循环 tick
                # (10Hz)必然放行,而且那一拍是真正重新观测过的,不需要相信盲写信念。
                self._last_detect = 0.0
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v 2>&1 | tail -10
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```
Expected: 全绿,`Ran 421 tests`(415 + Task 1 的 5 条 + 本条 1 条),skipped 仍是 10

- [ ] **Step 5: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "$(cat <<'EOF'
fix: 转向后作废检测节拍——攻击区不再等满一个攻击拍才翻

攻击区按转向前的朝向算(spec §5.1,不变),新朝向下一拍才生效;
而转向只发生在接战分支,那一拍 _detect_attacking 被寻怪起步宽限撑着,
下一拍按攻击间隔 0.7s 排 → 攻击区要 0.7s 后才翻过去。
实测端到端 p90=0.627s、>0.5s 占 21.5%。改成转向后把 _last_detect
打回哨兵,下一次 10Hz tick 就重测,且那一拍是真观测过的。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 悬浮窗的攻击区画在转向之后

Task 2 把延迟压到 ~0.1s,但只要 `_draw_debug`(`:628`)还在转向块**之前**,画出来的就永远是这一拍转向前的那半边。排查时会把「节拍慢」误读成「转了但攻击区没跟上」——这正是本次问题被发现的方式。

**语义边界(实现时必须守住):** 只改**画什么**,不改**判什么**。决策与决策日志用的仍是 `attack_area`(转向前);悬浮窗画的是「转完之后生效的那个区」。悬浮窗是实时视图,决策日志才是决策的存证,两者本来就不必逐字相同。

**Files:**
- Modify: `src/task/MapleFarmTask.py`(`_detect_and_act`:把 `:627-632` 的画框块下移到接战/寻怪分支之后)
- Test: `tests/test_farm_task_offline.py`(`TestDebugOverlay` 类)

**Interfaces:** 无变更。`_draw_debug` 签名与关键字名(`attack_area=`)保持不动,现有 `test_boxes_enabled_draws_with_current_state` / `test_boxes_disabled_clears_not_draws` 必须原样通过

- [ ] **Step 1: 写失败的测试**

加到 `tests/test_farm_task_offline.py` 的 `TestDebugOverlay` 类里:

```python
    def test_overlay_draws_the_zone_that_takes_effect_after_the_turn(self):
        """转向那一拍,悬浮窗画的是转向**之后**生效的攻击区。

        决策仍用转向前的 attack_area(spec §5.1,Task 2 也没动它),
        但画框若跟着用它,悬浮窗就永远比角色朝向慢一拍,排查时会把
        「节拍慢」误读成「转了但攻击区没跟上」。
        变异验证:把 draw_area 改回 attack_area,本用例转红。
        """
        task = make_task(**{'攻击模式': '检测'})   # 默认 单体(面朝)
        task._facing = 'RIGHT'
        task._boxes_enabled = MagicMock(return_value=True)
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')), \
                patch.object(MapleFarmTask, '_draw_debug') as draw:
            # 怪在左侧、面朝右 → 本拍发左转向
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=960, y=700, width=60, height=50)])
            run_with_frame(task)
        self.assertEqual(task._facing, 'LEFT')
        draw.assert_called_once()
        _, kwargs = draw.call_args
        # 左半区:右边界 = 身体 x(1280)。修复前画的是右半区,左边界才是 1280
        self.assertEqual(kwargs['attack_area'][2], 1280)

    def test_overlay_group_shape_unaffected_by_turn(self):
        """群体(对称)下攻击区就是整个接敌区,转向不该把它砍成一半。"""
        task = make_task(**{'攻击模式': '检测', '攻击区形状': '群体(对称)'})
        task._facing = 'RIGHT'
        task._boxes_enabled = MagicMock(return_value=True)
        with patch('src.detect.anchor.find_in_region',
                   return_value=AnchorHit(1280, 800, 130, 'Yufeng咕咕')), \
                patch.object(MapleFarmTask, '_draw_debug') as draw:
            task.find_mobs = MagicMock(
                return_value=[MagicMock(x=960, y=700, width=60, height=50)])
            run_with_frame(task)
        _, kwargs = draw.call_args
        self.assertEqual(kwargs['attack_area'], kwargs['zone'])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest tests.test_farm_task_offline -v 2>&1 | tail -20
```
Expected: 第一条 FAIL(`1783.5 != 1280`,画的还是右半区);第二条应当已经通过(护栏)

- [ ] **Step 3: 写实现**

1. **删除** `_detect_and_act` 中现有的画框块(`:627-632`):

```python
        if self._boxes_enabled():
            self._draw_debug(cfg, body=body, zone=zone, attack_area=attack_area,
                             mobs=mobs, mob_present=mob_present,
                             attack_present=self._last_attack_present)
        else:
            self._clear_debug()
```

2. **加回**到接战/寻怪 `if seek_hold: ... else: ...` 整块**之后**、`if cfg.get('决策日志开关'):` 之前:

```python
        # 画框放在转向之后:attack_area 是按本拍转向「前」的朝向算的(决策必须如此,
        # 见上面 spec §5.1 的注释),直接画它,悬浮窗就永远比角色朝向慢一拍 ——
        # 排查时会把「节拍慢」误读成「转了但攻击区没跟上」(2026-08-09 就是这么发现的)。
        # 这里只改画什么、不改判什么:决策与决策日志用的仍是 attack_area。
        # 群体(对称)下攻击区本就等于整个接敌区,转向不参与,原样画。
        draw_area = (attack_area
                     if turn is None or cfg.get('攻击区形状') == '群体(对称)'
                     else farm_logic.facing_half_zone(zone, body[0], self._facing))
        if self._boxes_enabled():
            self._draw_debug(cfg, body=body, zone=zone, attack_area=draw_area,
                             mobs=mobs, mob_present=mob_present,
                             attack_present=self._last_attack_present)
        else:
            self._clear_debug()
```

> `turn` 在 `if seek_hold:` 之前已由 `facing_before, turn = belief_before_obs, None` 初始化,寻怪分支下恒为 `None`,不会未定义。

- [ ] **Step 4: 跑测试确认通过 + 全量**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" -m unittest discover -s tests 2>&1 | tail -5
```
Expected: 全绿,`Ran 423 tests`,skipped 仍是 10

- [ ] **Step 5: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "$(cat <<'EOF'
fix: 悬浮窗攻击区画在转向之后——别再比角色朝向慢一拍

_draw_debug 原本在转向块之前,画的是本拍转向前那半边,悬浮窗因此
恒慢一拍,排查时会把「节拍慢」误读成「转了但攻击区没跟上」。
只改画什么、不改判什么:决策与决策日志用的仍是 attack_area。

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 实弹验收 + 归档

**Files:**
- Modify: `docs/superpowers/plans/2026-08-09-turn-zone-latency.md`(本文件,补「实现记录」一节)

**前置:** 改过 `src/task/MapleFarmTask.py` 后**必须重启 GUI**(框架的调试文件监视器只 `importlib.reload` 任务模块自身,不递归重载依赖,见 `ok/gui/tasks/TaskManger.py:333-349`)。

- [ ] **Step 1: 实弹采样**

1. 重启 `main_debug.py`,确认配置里 `决策日志开关=True`、`攻击模式=检测`、`攻击区形状=单体(面朝)`
2. **在与 2026-08-08 基线同一张图上**连续挂机 ≥30 分钟,期间不要手动干预(基线数据来自那天的常规挂机;换图会改变转向频率,两组数不可比)
3. 目标样本量:**`turn beats ≥ 150`**(2026-08-09 修订)。原定 ≥1000 是照着虚高的 3452 条定的;实测落地转向率约 5.2 次/分,1000 次要连挂 3.2 小时,不现实。150 次足以判 `corrected_back`:0 事件时三原则给出的 95% 置信上界是 3/150 = 2.0%,已低于下面的 3% 线

- [ ] **Step 2: 跑判据**

```bash
PYTHONUTF8=1 "H:/ok-mxd/data/apps/ok-ww/python/python.exe" scripts/analyze_turn.py logs/ok-script.log
```

**通过线(2026-08-09 按修正后的尺子重设,基线一并重算):**

> ⚠️ 本表的基线数与初版不同。初版把「算出了 turn 但键被 转向冷却/硬直/失焦 挡下」的拍也当成转向(26.8% 是虚的),`re_turned` 因此虚高到 28.7%。判据修正见 Task 1 的 `landed()`,基线随之从 3452 → **2526 次落地转向**。

**核心判据(全部满足才算过):**

| 指标 | 2026-08-08 基线 | 通过线 |
|---|---|---|
| latency **p50** | 0.179s | **≤ 0.12s**(打到主循环 tick 底) |
| gap **p50** | 0.200s | **≤ 0.12s** |
| `corrected_back` 占比 | 1.9% | **≤ 3%**(不得恶化) |
| `re_turned` 占比 | 4.7% | **≤ 10%**(不得明显恶化) |

**观察项(记录,不作为通过/失败依据):**

| 指标 | 2026-08-08 基线 | 说明 |
|---|---|---|
| latency p90 / p99 | 0.618s / 1.055s | 尾部由**丢锚与截图卡死**主导,不是本计划的根因 |
| latency > 0.5s 占比 | 20.2% | 同上 |
| gap p90 | 0.627s | 同上 |
| `max` | 7.770s | 截图卡死(`no frame for 10 sec`),明确不在范围内 |

- **为什么 p90 从判据降为观察项**:2026-08-09 实弹里超过 0.25s 的转向后拍,锚点来源是 `cached` 6 / `region` 3 / `window` 3 / `template` 2 —— 慢的是**那一拍本身**(丢锚后的慢通道分块扫描、截图卡死),不是节拍排得晚。最慢的 2.430s 紧挨着一条 `no frame for 10 sec, try to restart`。这条尾巴归 `2026-08-09-player-anchor-yolo-fusion.md` 管,在本计划里追是追错对象
- `re_turned` 若冲到 >10%,说明下一拍来得太快导致左右反复横跳 —— **立刻停下,回退 Task 2,不要靠调 `转向冷却(秒)` 掩盖**。那是另一个根因,要单开 spec

- [ ] **Step 3: 肉眼验收(判据 D 同款)**

开启悬浮窗标记框(GUI 操作流程见 AGENTS.md §4.1,**必须先开「启用标记框」再启动任务**),观察 ≥10 次转向:每次转向后攻击区(粗框)应当**当拍**就画在新的面朝侧,不再有可见的滞后。按 AGENTS.md §11.3 存证:截图 2 张(转向前 / 转向后相邻两拍)放 `screenshots/e2e/turn_zone_latency/`,文件名带日期。

- [ ] **Step 4: 归档**

在本文件末尾追加「实现记录」:实际测得的 latency 分位数、gap 分位数、四种结局占比、样本量、采样时段与地图,以及肉眼验收截图路径。**数字照实写,没达标就写没达标**。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-08-09-turn-zone-latency.md screenshots/e2e/turn_zone_latency/
git commit -m "$(cat <<'EOF'
docs: 归档转向延迟修复的实弹结果

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**这个计划刻意没做的事:**

- **没有推翻 `:583` 的判定顺序。** 「当拍就用转向后的新朝向判怪」看起来更直接,但那等于相信一次盲写信念 —— 转向键会被窗口失焦(日志有 `can't click on left/right` 实录)和击退硬直吞掉,`:653-657` 的 `_key_sendable` / `stun_suppressed` 守卫就是为此加的。改成「让下一拍立刻来」拿到的是同样的效果,而下一拍是真观测过的。
- **没有动 `朝向纠正`。** 原假设(观测器把转向纠正回去)已被数据否掉:1.6%。照那个方向改是修错东西。
- **没有动 `转向冷却(秒)` / `寻怪起步宽限(秒)` 等默认值。** 本计划一个配置项都不新增、不修改。

**已知风险:**

1. **转向后多跑一次检测拍**,即多一次 OCR + YOLO。按 2026-08-08 的 3452 次转向 / 全天算,增量很小,但 Task 4 若发现 CPU 占用明显上升,记在归档里。
2. **`re_turned` 可能上升**:下一拍来得快,左右横跳的机会也变多。`attack_turn_direction` 的目标侧锁定本来就是为治这个加的,理论上挡得住;通过线里已经设了监控项,超了就回退而不是打补丁。
3. **Task 3 让悬浮窗与决策日志在转向那一拍不完全一致。** 这是有意的(实时视图 vs 决策存证),注释里已写明。若日后有人排查时被绕进去,应当加一个 debug 字段,而不是把画框改回去。

---

## 实现记录(2026-08-09)

### 交付

| 提交 | 内容 |
|---|---|
| `85b5fa8` | Task 1 `scripts/analyze_turn.py` + `tests/test_analyze_turn.py` |
| `a87304a` | Task 2 转向后作废检测节拍(`self._last_detect = 0.0`) |
| `18fc9c9` | Task 3 悬浮窗攻击区画在转向之后 |
| (本次) | 判据修正:`landed()` 落地转向判定;基线与通过线按修正口径重算 |

测试:`Ran 428 tests / OK (skipped=8)`。两处改动都做过变异验证 —— 删掉 `self._last_detect = 0.0` 转红,画框改回 `attack_area` 转红,不是假绑定。

### 判据修正(评审发现,已修)

初版 `scan()` 按「`转向=` 不是 `-`」计数,把被 转向冷却/硬直/失焦 挡下、`_facing` 根本没变的拍也算成转向。08-08 日志上 3452 条里 926 条(**26.8%**)属于此类,`re_turned` 因此虚高到 28.7%,离初版设的 32% 回退红线只差 3.3 个点 —— 而 Task 2 让下一拍提前到 ~0.1s、`转向冷却` 仍是 1.5s,"算出一个仍被冷却挡着的 turn"的拍恰恰更可能是紧接的下一拍。**不修的话这条红线会因为纯统计假象误杀一个正常工作的修复。**

同一个坑 `scripts/analyze_facing.py:11-13` 早有记载,本计划初版写语义时把它丢了。已改用信念 `f0 != f1` 判定并补两条绑定测试。

### 实弹结果

采样:2026-08-09 13:03–13:35(32 分钟),4752 决策拍,**180 次落地转向**,采样期间会话未中断、未手动干预。

**核心判据 —— 全部通过:**

| 指标 | 08-08 基线 | 08-09 实弹 | 通过线 | |
|---|---|---|---|---|
| latency p50 | 0.179s | **0.084s** | ≤ 0.12s | ✅ |
| gap p50 | 0.200s | **0.084s** | ≤ 0.12s | ✅ |
| `corrected_back` | 1.9% | **0.6%**(1/180) | ≤ 3% | ✅ |
| `re_turned` | 4.7% | **2.2%**(4/180) | ≤ 10% | ✅ |
| `settled` | 93.4% | **97.2%** | — | — |

latency 与 gap 的 p50 双双落在 0.084s —— 转向后的下一拍就是紧接的那个主循环 tick,与 Task 2 的设计意图完全吻合。原先「等满一个 `攻击间隔`(0.706s)」的那一档消失了。

**观察项 —— 未达初版判据,已归因,不阻塞验收:**

| 指标 | 08-08 基线 | 08-09 实弹 | 初版判据 |
|---|---|---|---|
| latency p90 | 0.618s | 0.546s | ~~≤0.25s~~ |
| latency > 0.5s | 20.2% | 10.3% | ~~≤5%~~ |
| gap p90 | 0.627s | 0.546s | ~~≤0.2s~~ |
| max | 7.770s | 2.430s | 不作判据 |

归因(2026-08-09 逐拍查过):转向后超过 0.25s 的那些拍,锚点来源是 `cached` 6 / `region` 3 / `window` 3 / `template` 2 —— **慢的是那一拍本身**(丢锚后走慢通道分块扫描、或截图卡死),不是节拍排得晚。最慢的 2.430s(@13:04:38)紧挨着一条 `no frame for 10 sec, try to restart`。这条尾巴属于丢锚与截图,归 `2026-08-09-player-anchor-yolo-fusion.md`,在本计划里继续追是追错对象。

注:p90 随样本增大而抬升(0.335 → 0.400 → 0.482 → 0.546),与"尾部由丢锚事件驱动、随时长累积"的解释一致。

**风险复核:**

- 计划 §已知风险 ②(`re_turned` 上升导致左右横跳):**未发生**,2.2% 低于基线 4.7%。
- 评审提出的「下一拍提前到 0.1s → 贴图没翻完 → 朝向纠正把信念写回去」:**未发生**,`corrected_back` 0.6% 低于基线 1.9%。不需要给朝向纠正加静默窗。
- 负载:可归因于本改动的增量 = 180 次转向 / 32 分钟 ≈ 5.6 拍/分,占同期约 148 拍/分 的 **3.8%**。(不要拿本次的"拍/分"与 08-08 的 46 拍/分 直接比 —— 后者跨 9.5 小时、活动构成不同,不是因果对比。)

### 未完成

- **Step 3 肉眼验收截图未做**:需要人在 GUI 前开悬浮窗标记框实拍,`screenshots/e2e/turn_zone_latency/` 目前为空。判据 D 的视觉确认尚缺,验收依据全部来自决策日志。
- **Task 3 的已知副作用未处理**:落地转向那一拍,`draw_area` 用新朝向重算了,但 `attack_present` 仍是按转向前的 `attack_area` 算的(且该拍必为 `False`),于是"装着怪的新半区"会被画成蓝框,下一拍(~0.1s)转红。评审判定为 LOW。做肉眼验收时**这属正常现象,不要当成 bug**。
