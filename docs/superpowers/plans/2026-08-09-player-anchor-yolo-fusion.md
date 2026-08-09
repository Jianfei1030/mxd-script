# 怪堆丢锚治理（YOLO player 类 + 名字牌身份融合）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把丢锚拍占比从 28.5% 压到 ≤10%——给现有 YOLO 检测加 player 类（同拍一次推理），锚点阶梯在名字牌两级之后插一级「YOLO 关联」，身份仍由名字牌校准；捎带丢锚事件触发即时慢扫。

**Architecture:** 纯决策逻辑进 `farm_logic.py`（可离线单测），任务层只做接线；检测接缝保持 `find_mobs`（新增 `boxes=` 过滤参数 + `find_all` 一次全类别推理），68 处现有测试 mock 零改动。模型侧 class 1 = 任意玩家角色，身份判别完全在融合层。

**Tech Stack:** Python 3.12（`.venv-warrior`）、OpenVINO YOLOv8（onnx 1280）、cv2、unittest、yolo.exe（训练）。

**Spec:** `docs/superpowers/specs/2026-08-09-player-anchor-yolo-fusion-design.md`（判据/门/回退的唯一事实源，本计划不复述通过线数值以免抄错——验收一律回 spec §5 对）。

## Global Constraints

- 运行/测试一律用项目 venv：`.\.venv-warrior\Scripts\python.exe`，命令前加 `$env:PYTHONUTF8=1;`（Windows 控制台中文输出）。venv 缺失按 `AGENTS.md` §1.1 重建。
- **铁律 §11.1**：src/scripts/tests 禁止绝对路径，项目根用 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 推导。
- **铁律 §11.2**：新增/修改纯逻辑必须带 unittest，离线可跑；决策逻辑不许塞进 run() 里。
- **铁律 §11.4**：依赖存档帧/模型的用例环境缺失时显式 skip，不许假失败。
- 全量单测命令（本计划新增 2 个模块后）：
  ```powershell
  $env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic tests.test_warrior_debug_offline tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_calibrate_offline tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_label_boxes
  ```
- 每个 Task 一个 commit，信息用中文、前缀 feat:/fix:/test:/docs:（沿仓库惯例）。
- 分辨率恒定 2560x1440（`CALIBRATED_SIZE`），测试合成帧同尺寸。
- 工作区里已有他人未提交改动（`assets/mob_model/mob.onnx`、seek spec、turn-zone 相关未跟踪文件）——**只 `git add` 本任务列出的文件，严禁 `git add -A`**。

---

### Task 1: `scripts/analyze_anchor.py` —— 丢锚判据度量工具（尺子先行）

**Files:**
- Create: `scripts/analyze_anchor.py`
- Create: `tests/test_analyze_anchor.py`

**Interfaces:**
- Consumes: `src.task.MapleFarmTask.decision_log_line`（测试用它构造样本行——真绑定，格式一改测试立刻红；签名见 `MapleFarmTask.py:93`）
- Produces: `analyze_anchor.parse(lines) -> [dict(t, src, can_atk)]`、`sessionize(rows, gap=10.0, min_rows=20)`、`loss_episodes(sessions) -> [float]`、`metrics(sessions) -> dict`；命令行 `python scripts/analyze_anchor.py [日志] [--since HH:MM:SS] [--until HH:MM:SS]`。Task 11 验收调它。

- [x] **Step 1: 写失败测试**

`tests/test_analyze_anchor.py`（整文件）：

```python
# -*- coding: utf-8 -*-
"""analyze_anchor 的判据算术与决策行格式绑定。

样本行必须用 decision_log_line 构造(2026-08-08 评审坐实过手抄格式的假绑定,
见 MapleFarmTask.py:93 docstring):格式一改,本文件立刻红。
"""
import unittest

from scripts.analyze_anchor import parse, sessionize, loss_episodes, metrics
from src.task.MapleFarmTask import decision_log_line


def _line(ts, source, can_atk):
    """带时间戳前缀的完整日志行。除 src/可打 外全部字段取任意合法值。"""
    body = decision_log_line(source, 1230.0, 866.0, [(1.0, 2.0)] * 3, [1.0], 1,
                             0, 1, None, True, True, [1.0], can_atk,
                             'LEFT', 'LEFT', None, None, True, None, 0.0, 0.0)
    return f'{ts} DEBUG TaskExecutor MapleFarmTask:{body}\n'


def _ts(sec, ms=0):
    return f'2026-08-09 12:{sec // 60:02d}:{sec % 60:02d},{ms:03d}'


class TestParse(unittest.TestCase):

    def test_parse_extracts_src_and_can_atk(self):
        rows = parse([_line(_ts(0), 'template', True),
                      _line(_ts(1), 'cached', False),
                      'not a decision line\n'])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['src'], 'template')
        self.assertTrue(rows[0]['can_atk'])
        self.assertEqual(rows[1]['src'], 'cached')
        self.assertFalse(rows[1]['can_atk'])
        self.assertAlmostEqual(rows[1]['t'] - rows[0]['t'], 1.0)

    def test_parse_accepts_yolo_source(self):
        # 新来源标签 src=yolo 是普通值,不许被正则漏掉
        rows = parse([_line(_ts(0), 'yolo', True)])
        self.assertEqual(rows[0]['src'], 'yolo')


class TestEpisodes(unittest.TestCase):

    def _rows(self, srcs, dt=0.5):
        return [dict(t=100.0 + i * dt, src=s, can_atk=False)
                for i, s in enumerate(srcs)]

    def test_loss_episode_spans_from_first_lost_to_recovery(self):
        # template cached cached template → 一段,时长 2 拍 * 0.5s = 1.0
        eps = loss_episodes([self._rows(
            ['template', 'cached', 'cached', 'template'])])
        self.assertEqual(len(eps), 1)
        self.assertAlmostEqual(eps[0], 1.0)

    def test_fallback_counts_as_lost_and_tail_open_episode_dropped(self):
        # 段尾还在丢(没有恢复拍) → 时长未知,不计
        eps = loss_episodes([self._rows(
            ['window', 'fallback', 'cached'])])
        self.assertEqual(eps, [])

    def test_yolo_counts_as_real_position(self):
        eps = loss_episodes([self._rows(
            ['cached', 'yolo', 'cached', 'template'])])
        # yolo 是真实观测:第一段在 yolo 拍恢复(0.5s),第二段在 template 拍恢复(0.5s)
        self.assertEqual(len(eps), 2)
        for e in eps:
            self.assertAlmostEqual(e, 0.5)


class TestMetrics(unittest.TestCase):

    def test_metrics_on_synthetic_session(self):
        # 30 拍 × 0.5s:6 拍 cached(3+3 两段,各 1.5s),24 拍 template;可打前 15 拍 True
        srcs = (['template'] * 8 + ['cached'] * 3 + ['template'] * 8
                + ['cached'] * 3 + ['template'] * 8)
        rows = [dict(t=100.0 + i * 0.5, src=s, can_atk=i < 15)
                for i, s in enumerate(srcs)]
        m = metrics(sessionize(rows))
        self.assertEqual(m['ticks'], 30)
        self.assertAlmostEqual(m['A_lost_ratio'], 6 / 30)
        self.assertAlmostEqual(m['B_p90'], 1.5)
        self.assertAlmostEqual(m['C_per_hour'], 0.0)  # 两段都 < 3s
        self.assertAlmostEqual(m['D_ratio'], 15 / 30)
        self.assertAlmostEqual(m['E_median'], 0.5)

    def test_sessionize_splits_on_gap(self):
        rows = ([dict(t=100.0 + i * 0.5, src='template', can_atk=True)
                 for i in range(25)]
                + [dict(t=200.0 + i * 0.5, src='template', can_atk=True)
                   for i in range(25)])
        self.assertEqual(len(sessionize(rows)), 2)


if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_analyze_anchor -v
```
预期：`ModuleNotFoundError: No module named 'scripts.analyze_anchor'`（若整个 `scripts` 包导入失败，先看 `tests/test_calibrate_offline.py` 是怎么导入 scripts 下模块的，照同一方式解决——`scripts/` 缺 `__init__.py` 就补一个空文件并纳入本次提交）。实际报错与预期一致；namespace package 导入无需补 `__init__.py`。

- [x] **Step 3: 实现 `scripts/analyze_anchor.py`（整文件）**

```python
# -*- coding: utf-8 -*-
"""丢锚判据 A/B/C/D/E(2026-08-09-player-anchor-yolo-fusion-design.md §5)。

判据在 spec 里事先写死,本脚本只把它算出来,不许在这里改通过线。
只依赖 决策 src= 与 可打= 两个字段:改动前后语义不变(src 只是多一个新值
yolo;丢锚定义 = src ∈ {cached, fallback} 不变),可直接对比新旧日志。

用法:
    python scripts/analyze_anchor.py [日志路径] [--since HH:MM:SS] [--until HH:MM:SS]
默认日志路径 logs/ok-script.log。基线快照(08-08 全天)见 spec §1.2。
"""
import re
import sys
from datetime import datetime

DEFAULT_LOG = 'logs/ok-script.log'
LOST = ('cached', 'fallback')

DEC = re.compile(
    r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) .*?'
    r'决策 src=(\S+) body_x=\S+ anchor_y=\S+ 怪=\d+ .*?可打=(\w+) ')


def parse(lines):
    """决策行 → dict(t, src, can_atk)。不认识的行直接跳过。"""
    rows = []
    for line in lines:
        m = DEC.match(line)
        if not m:
            continue
        ts, src, can_atk = m.groups()
        rows.append(dict(
            t=datetime.strptime(ts, '%Y-%m-%d %H:%M:%S,%f').timestamp(),
            src=src, can_atk=can_atk == 'True'))
    return rows


def sessionize(rows, gap=10.0, min_rows=20):
    """按大间隔切段:停任务/重启的长空档跨段算时长没有意义(同 analyze_seek)。"""
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


def loss_episodes(sessions):
    """连续 src∈LOST 段的时长:首个丢锚拍 → 恢复拍(首个非丢锚拍)。

    段尾仍在丢(没等到恢复拍)→ 时长未知,不计——与基线统计口径一致,
    宁可少算也不编造。
    """
    out = []
    for s in sessions:
        start = None
        for r in s:
            lost = r['src'] in LOST
            if lost and start is None:
                start = r['t']
            elif not lost and start is not None:
                out.append(r['t'] - start)
                start = None
    return [x for x in out if x > 0]


def _quantile(xs, q):
    if not xs:
        return float('nan')
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def metrics(sessions):
    rows = [r for s in sessions for r in s]
    span = sum(s[-1]['t'] - s[0]['t'] for s in sessions)
    eps = loss_episodes(sessions)
    gaps = [b['t'] - a['t'] for s in sessions for a, b in zip(s, s[1:])]
    by_src = {}
    for r in rows:
        by_src[r['src']] = by_src.get(r['src'], 0) + 1
    return dict(
        ticks=len(rows), span=span, sessions=len(sessions), by_src=by_src,
        A_lost_ratio=(sum(1 for r in rows if r['src'] in LOST) / len(rows)
                      if rows else float('nan')),
        B_n=len(eps), B_median=_quantile(eps, .5), B_p90=_quantile(eps, .9),
        C_per_hour=(sum(1 for x in eps if x >= 3.0) / (span / 3600)
                    if span else float('nan')),
        D_ratio=(sum(1 for r in rows if r['can_atk']) / len(rows)
                 if rows else float('nan')),
        E_median=_quantile(gaps, .5), E_p90=_quantile(gaps, .9))


def main(argv):
    path = DEFAULT_LOG
    since = until = None
    args = list(argv)
    for flag in ('--since', '--until'):
        if flag in args:
            i = args.index(flag)
            if flag == '--since':
                since = args[i + 1]
            else:
                until = args[i + 1]
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
    print('src 分布: ' + '  '.join(
        f'{k}={v}({v / m["ticks"]:.1%})' for k, v in
        sorted(m['by_src'].items(), key=lambda kv: -kv[1])))
    print(f'A 丢锚拍占比     {m["A_lost_ratio"]:.1%}'
          f'                          通过线: <=10%')
    print(f'B 丢锚段 p90     {m["B_p90"]:.2f}s  中位 {m["B_median"]:.2f}s'
          f'  (n={m["B_n"]})      通过线: p90<=1.0')
    print(f'C >=3s 段频次    {m["C_per_hour"]:.1f} 段/小时'
          f'                    通过线: <=6')
    print(f'D 可打拍占比     {m["D_ratio"]:.1%}'
          f'                          通过线: >=41.0%')
    print(f'E 拍间隔 中位 {m["E_median"]:.3f}s  p90 {m["E_p90"]:.3f}s'
          f'      通过线: 不高于基线(0.704/0.946)')


if __name__ == '__main__':
    main(sys.argv[1:])
```

- [x] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_analyze_anchor -v
```
预期：全绿。

- [ ] **Step 5: 用真实日志核对基线（有 08-08 日志的机器上）**（本机无 `logs/ok-script.2026-08-08.log`，已按计划跳过，提交信息注明）

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\analyze_anchor.py logs\ok-script.2026-08-08.log
```
预期：A ≈ 28.5%、B p90 ≈ 2.2s（与 spec §1.2 手工统计一致，允许 ±0.5% 级别出入——正则口径差异要查明才许过）。日志缺失的机器跳过本步并在提交信息注明。

- [ ] **Step 6: 提交**

```powershell
git add scripts/analyze_anchor.py tests/test_analyze_anchor.py
git commit -m "feat: analyze_anchor 丢锚判据 A-E 度量工具——尺子先行,基线对上 spec §1.2"
```

---

### Task 2: `farm_logic.select_player_box` —— YOLO 关联门（纯函数）

**Files:**
- Modify: `src/task/farm_logic.py`（文件末尾追加）
- Test: `tests/test_farm_logic.py`（追加测试类）

**Interfaces:**
- Consumes: 无（纯函数；player 框是任意带 `.x/.y/.width/.height` 属性的对象，与 `ok/feature/Box.py` 的 Box 同形）
- Produces: `PLAYER_GATE_HALF_W = 240`、`PLAYER_GATE_HALF_H = 120`、`gate_player_boxes(players, pred, half_w=..., half_h=...) -> [box]`（门口径的唯一事实源——决策日志的 `yolo候选` 记的就是它的长度）、`select_player_box(players, pred, identity_fresh, half_w=..., half_h=...) -> box | None`。Task 7 在 `_resolve_anchor` 调用两者。

- [x] **Step 1: 写失败测试（追加到 `tests/test_farm_logic.py`）**

```python
from types import SimpleNamespace


def _pbox(cx, cy, w=60, h=120):
    """player 框:按中心坐标构造(x/y 是左上角,与 Box 同形)。"""
    return SimpleNamespace(x=cx - w / 2, y=cy - h / 2, width=w, height=h)


class TestSelectPlayerBox(unittest.TestCase):
    """YOLO 关联门(spec §3.3):恰 1 个门内候选 → 接受;多个 → 身份新鲜才取最近;
    0 个/身份过期多候选 → None(宁可退级,不认错人)。"""

    def test_single_candidate_in_gate_accepted_even_if_identity_stale(self):
        # 恰 1 个在门内:接受,不看身份新鲜度(屏幕上只有一个玩家,几乎必是自己)
        box = _pbox(1200, 900)
        self.assertIs(fl.select_player_box([box], (1180, 880), False), box)

    def test_candidate_outside_gate_rejected(self):
        # 横向差 250 > 半宽 240 → 门外
        self.assertIsNone(fl.select_player_box(
            [_pbox(1450, 900)], (1200, 900), True))
        # 纵向差 130 > 半高 120 → 门外
        self.assertIsNone(fl.select_player_box(
            [_pbox(1200, 1030)], (1200, 900), True))

    def test_gate_boundary_inclusive(self):
        # 恰压门边算门内 —— 与 point_in_zone 的边界口径一致
        box = _pbox(1200 + fl.PLAYER_GATE_HALF_W, 900)
        self.assertIs(fl.select_player_box([box], (1200, 900), False), box)

    def test_multiple_fresh_identity_picks_nearest(self):
        near, far = _pbox(1180, 880), _pbox(1350, 900)
        self.assertIs(fl.select_player_box([far, near], (1200, 900), True), near)

    def test_multiple_nearest_breaks_horizontal_tie_by_y(self):
        # 横向同距、纵向不同(隔一层平台的路人):取合位移最近的那个
        same_floor, other_floor = _pbox(1240, 900), _pbox(1160, 1000)
        self.assertIs(fl.select_player_box(
            [other_floor, same_floor], (1200, 900), True), same_floor)

    def test_multiple_stale_identity_rejected(self):
        # 路人贴身且身份过期 → 拒绝,退给慢扫/cached,不认错人
        self.assertIsNone(fl.select_player_box(
            [_pbox(1180, 880), _pbox(1350, 900)], (1200, 900), False))

    def test_empty_players_rejected(self):
        self.assertIsNone(fl.select_player_box([], (1200, 900), True))

    def test_gate_player_boxes_returns_only_in_gate_as_list(self):
        # 决策日志 yolo候选= 记门内候选数,不是全屏数——全屏数混着门外路人,
        # 调关联门/查误认时会误导。返回列表(而非单个框),供 len() 计数
        inside, outside = _pbox(1240, 900), _pbox(1500, 900)
        self.assertEqual(fl.gate_player_boxes([inside, outside], (1200, 900)),
                         [inside])
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic -v 2>&1 | Select-String "select_player|FAILED|Error"
```
预期：`AttributeError: module ... has no attribute 'PLAYER_GATE_HALF_W'`（或 select_player_box）。实际与预期一致（select_player_box/PLAYER_GATE_HALF_W/gate_player_boxes 三处 AttributeError，8 个用例全红）。

- [x] **Step 3: 实现（追加到 `src/task/farm_logic.py` 末尾）**

```python
PLAYER_GATE_HALF_W = 240   # YOLO 关联门半宽:与快通道搜索窗同宽(FAST_HALF_W,跨模块注释同步)
PLAYER_GATE_HALF_H = 120   # 关联门半高:比快窗的 80 放宽——击退/跳跃纵向位移大,
                           # 快窗为 OCR 成本收窄的理由对免费的 YOLO 不成立(spec §3.3)


def gate_player_boxes(players, pred, half_w=PLAYER_GATE_HALF_W,
                      half_h=PLAYER_GATE_HALF_H):
    """框中心落在 pred 的 ±half_w/±half_h 门内的候选(门口径唯一事实源)。

    select_player_box 的裁决与决策日志的 yolo候选= 都从这里拿,
    两处各写一遍迟早分叉。边界压线算门内,与 point_in_zone 口径一致。"""
    px, py = pred
    return [b for b in players
            if abs(b.x + b.width / 2 - px) <= half_w
            and abs(b.y + b.height / 2 - py) <= half_h]


def select_player_box(players, pred, identity_fresh,
                      half_w=PLAYER_GATE_HALF_W, half_h=PLAYER_GATE_HALF_H):
    """YOLO player 框 → 「哪个是我」的关联裁决(spec §3.3)。

    YOLO 只学「什么是玩家」,身份判别在这里:pred 是外推位置(与快窗 OCR 同一个
    搜索中心),门内候选由 gate_player_boxes 给出。
    - 恰 1 个 → 接受(不看身份新鲜度:门内只有一个玩家,几乎必是自己);
    - 多个 → identity_fresh(距上次名字牌真实命中还在保鲜窗内)才取合位移最近的,
      否则返回 None——路人贴身且身份过期,宁可退到慢扫/cached,不认错人;
    - 0 个 → None,落到阶梯下一级。
    最近取欧氏距离平方:两候选横向同距但隔层时,必须选同层那个(横向距离分不开)。
    传入已过门的列表也正确(门是幂等的,Task 7 先 gate 后 select 不改语义)。
    """
    gated = gate_player_boxes(players, pred, half_w, half_h)
    if not gated:
        return None
    if len(gated) == 1:
        return gated[0]
    if not identity_fresh:
        return None
    px, py = pred
    return min(gated, key=lambda b: (b.x + b.width / 2 - px) ** 2
               + (b.y + b.height / 2 - py) ** 2)
```

- [x] **Step 4: 跑测试确认通过**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic -v
```
预期：全绿（含既有用例）。

- [ ] **Step 5: 提交**

```powershell
git add src/task/farm_logic.py tests/test_farm_logic.py
git commit -m "feat: select_player_box 关联门——恰1接受/多候选看身份保鲜/过期拒绝"
```

---

### Task 3: `should_rescan_anchor` 加 force —— 强制慢扫（纯函数）

**Files:**
- Modify: `src/task/farm_logic.py:143-145`
- Test: `tests/test_farm_logic.py`（追加；既有 167-168 两行用例保持原样必须继续绿——向后兼容的证明）

**Interfaces:**
- Consumes: 无
- Produces: `FORCED_RESCAN_MIN_INTERVAL = 0.5`、`should_rescan_anchor(now, last_scan, interval, force=False, last_forced=0.0, forced_min_interval=FORCED_RESCAN_MIN_INTERVAL) -> bool`。Task 8 在 `_resolve_anchor` 传 `force=` 与 `last_forced=`。

- [x] **Step 1: 写失败测试（追加到 `tests/test_farm_logic.py`）**

```python
class TestForcedRescan(unittest.TestCase):
    """丢锚事件触发即时慢扫(spec §3.5):force 绕过常规节流,但自身限频 0.5s。"""

    def test_force_bypasses_regular_throttle(self):
        # 常规窗没到(0.6s < 2s),force 放行
        self.assertTrue(fl.should_rescan_anchor(100.6, 100.0, 2, force=True))

    def test_force_rate_limited_by_min_interval(self):
        # 距上次强制扫描 0.3s < 0.5s → 不放行(慢扫最坏 235ms,不许打满主循环)
        self.assertFalse(fl.should_rescan_anchor(
            100.6, 100.0, 2, force=True, last_forced=100.3))
        # 边界:恰好 0.5s → 放行(与 should_attack 同口径)
        self.assertTrue(fl.should_rescan_anchor(
            100.8, 100.0, 2, force=True, last_forced=100.3))

    def test_no_force_keeps_old_behavior(self):
        self.assertFalse(fl.should_rescan_anchor(101.0, 100.0, 2))
        self.assertTrue(fl.should_rescan_anchor(102.0, 100.0, 2))

    def test_regular_window_due_passes_even_when_forced_rate_limited(self):
        # 常规窗已到点:force 的限频不该反过来卡住常规扫描
        self.assertTrue(fl.should_rescan_anchor(
            102.0, 100.0, 2, force=True, last_forced=101.9))
```

- [ ] **Step 2: 跑测试确认失败**

预期：`TypeError: should_rescan_anchor() got an unexpected keyword argument 'force'`。实际与预期一致（3 错,`test_no_force_keeps_old_behavior` 不传 force 自然过）。

- [x] **Step 3: 实现（替换 `farm_logic.py` 的 `should_rescan_anchor`，常量放函数上方）**

```python
FORCED_RESCAN_MIN_INTERVAL = 0.5   # 强制慢扫自身限频:慢扫最坏 235ms,不许打满主循环


def should_rescan_anchor(now, last_scan, interval, force=False,
                         last_forced=0.0,
                         forced_min_interval=FORCED_RESCAN_MIN_INTERVAL):
    """是否应该重新扫描锚点。

    force=True 是丢锚事件通道(spec §3.5):击退/锚点超龄时绕过常规节流立刻扫,
    但距上次强制扫描必须 >= forced_min_interval——丢锚常由位置跳变引起,
    常规 2s 节流恰好卡在最需要慢扫的时刻(基线里慢扫只占 2.2%)。
    默认参数 = 旧行为,既有调用方不受影响。last_forced=0.0 哨兵(从未强制)天然放行。
    """
    if now - last_scan >= interval:
        return True
    return force and now - last_forced >= forced_min_interval
```

- [x] **Step 4: 跑测试确认通过（整个 test_farm_logic 全绿，含旧的 167-168 行）**

- [ ] **Step 5: 提交**

```powershell
git add src/task/farm_logic.py tests/test_farm_logic.py
git commit -m "feat: should_rescan_anchor 加 force——事件触发绕过节流,自身 0.5s 限频"
```

---

### Task 4: `decision_log_line` 追加 yolo 观测字段

**Files:**
- Modify: `src/task/MapleFarmTask.py:93-123`（`decision_log_line`）
- Test: `tests/test_farm_task_offline.py`（追加测试类）

**Interfaces:**
- Consumes: 无
- Produces: `decision_log_line(..., yolo_cands=None, yolo_dist=None)`——两个新**关键字**参数追加在 `obs_flip` 之后；行尾追加 `yolo候选=N 关联距=D`（未提供时都写 `-`，绝不写 0）。Task 7 的 `_log_decision` 传值；Task 1 的正则是前缀匹配、天然兼容。既有调用方/测试不传新参数照常工作。

- [x] **Step 1: 写失败测试（追加到 `tests/test_farm_task_offline.py`）**

```python
class TestDecisionLineYoloFields(unittest.TestCase):
    """yolo候选/关联距 字段(spec §3.6):没有 yolo 命中时写 '-',绝不写 0
    (0 会被判据脚本当真值,同 near 字段的既有纪律)。"""

    def _line(self, **kw):
        from src.task.MapleFarmTask import decision_log_line
        return decision_log_line(
            'yolo', 1230.0, 866.0, [(1.0, 2.0)], [], 0, 0, 0, None,
            False, False, [], False, 'LEFT', 'LEFT', None, None, True,
            None, 0.0, 0.0, **kw)

    def test_fields_dash_when_absent(self):
        self.assertIn('yolo候选=- 关联距=-', self._line())

    def test_fields_rendered_when_present(self):
        self.assertIn('yolo候选=2 关联距=35', self._line(yolo_cands=2, yolo_dist=35.4))

    def test_fields_appended_at_line_end(self):
        # 追加在行尾:analyze_anchor/analyze_seek 的前缀正则不受影响
        self.assertTrue(self._line().endswith('关联距=-'))
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestDecisionLineYoloFields -v
```
预期：`TypeError ... unexpected keyword argument 'yolo_cands'`。实际与预期一致（1 错 + 2 字段断言失败）。

- [x] **Step 3: 实现**

`decision_log_line` 签名末尾加 `yolo_cands=None, yolo_dist=None`；docstring 补一段：

```
    yolo候选 / 关联距 是 YOLO 关联级(spec §3.6)的观测:候选 = **门内**候选数
    (gate_player_boxes 口径——全屏数混着门外路人,调关联门/查误认会误导),
    关联距 = 命中框中心与外推位置的水平距离。
    非 yolo 来源的拍两项都写 '-',绝不写 0。追加在行尾:analyze 脚本前缀匹配。
```

return 表达式最后一行 `f'分值=...'` 之后追加：

```python
            f' yolo候选={yolo_cands if yolo_cands is not None else "-"}'
            f' 关联距={f"{yolo_dist:.0f}" if yolo_dist is not None else "-"}')
```

（原最后一行 `f'分值={...}/{...:.2f}')` 去掉右括号改为续接上面两行。）

- [x] **Step 4: 跑测试确认通过 + 全量单测**

全量命令见 Global Constraints。既有 `tests.test_analyze_anchor`（Task 1 用 `decision_log_line` 构造样本行）必须仍绿——它证明前缀正则真的兼容新字段。实测全量 402 绿,test_analyze_anchor 未动。

- [ ] **Step 5: 提交**

```powershell
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 决策行追加 yolo候选/关联距 字段——先造观测,行为改动在后"
```

---

### Task 5: `BaseMapleTask.find_all` + `find_mobs(boxes=)` —— 一拍一次推理的接缝

**Files:**
- Modify: `src/task/BaseMapleTask.py:18-21`
- Test: `tests/test_farm_task_offline.py`（追加测试类）

**Interfaces:**
- Consumes: `og.my_app.yolo_detect(image, threshold, label)`（`src/globals.py:26`；label=-1 = 全类别，每次调用都是完整推理）
- Produces:
  - `find_all(self, frame=None, threshold=0.5) -> [Box]`——一次全类别推理，Task 7 每检测拍调一次；
  - `find_mobs(self, frame=None, threshold=0.5, boxes=None) -> [Box]`——`boxes` 非 None 时**纯过滤**（`b.name == 'mob'`），不推理；None 时旧行为（自己推理，WarriorDebugTask 等调用方不变）。
  - **设计约束**：`_detect_and_act` 继续经 `find_mobs` 拿怪——`tests/test_farm_task_offline.py` 有 68 处 `task.find_mobs = MagicMock(...)`，接缝名一换全部报废；`boxes=` 过滤参数让 mock 与真实路径同时成立。

- [x] **Step 1: 写失败测试（追加到 `tests/test_farm_task_offline.py`）**

```python
class TestFindMobsBoxesParam(unittest.TestCase):
    """find_mobs(boxes=) 纯过滤路径:一拍一次推理(spec §3.2)的接缝。
    不碰 og/模型,boxes 路径必须完全离线可测。"""

    def _fake(self, name):
        return SimpleNamespace(x=0, y=0, width=10, height=10, name=name)

    def test_boxes_param_filters_mobs_without_inference(self):
        from src.task.BaseMapleTask import BaseMapleTask
        m, p = self._fake('mob'), self._fake('player')
        out = BaseMapleTask.find_mobs(SimpleNamespace(), boxes=[m, p, m])
        self.assertEqual(out, [m, m])

    def test_empty_boxes_gives_empty_not_inference(self):
        from src.task.BaseMapleTask import BaseMapleTask
        # boxes=[] 也是「已推理过」:绝不能落回自推理分支(那会二次推理)
        self.assertEqual(BaseMapleTask.find_mobs(SimpleNamespace(), boxes=[]), [])
```

- [ ] **Step 2: 跑测试确认失败**

预期：第二个用例 `find_mobs(boxes=[])` 走进旧分支 `from ok import og` 后 `AttributeError`（SimpleNamespace 无 frame）——或第一个用例 `TypeError: unexpected keyword 'boxes'`。实际为第一种（`TypeError: unexpected keyword 'boxes'`，2 错）。

- [x] **Step 3: 实现（替换 `BaseMapleTask.py:18-21`）**

```python
    def find_mobs(self, frame=None, threshold=0.5, boxes=None):
        """boxes= 传入同拍已推理的全类别结果时只做类别过滤,不再推理
        (一拍一次推理,spec §3.2;detect 的 label 参数是事后过滤,分两次调用
        会白付一倍推理)。不传 = 旧行为,WarriorDebugTask 等调用方不变。"""
        if boxes is not None:
            return [b for b in boxes if b.name == 'mob']
        from ok import og
        return og.my_app.yolo_detect(frame if frame is not None else self.frame,
                                     threshold=threshold, label=0)

    def find_all(self, frame=None, threshold=0.5):
        """一次推理拿全类别(mob+player),供检测拍分流。"""
        from ok import og
        return og.my_app.yolo_detect(frame if frame is not None else self.frame,
                                     threshold=threshold, label=-1)
```

- [x] **Step 4: 跑测试确认通过 + 全量单测全绿**

- [ ] **Step 5: 提交**

```powershell
git add src/task/BaseMapleTask.py tests/test_farm_task_offline.py
git commit -m "feat: find_all 一次全类别推理 + find_mobs(boxes=) 纯过滤——保留 68 处测试接缝"
```

---

### Task 6: 模型类别基建 —— dic_labels / mobs.yaml / 标注与预标脚本

**Files:**
- Modify: `src/OpenVinoYolo8Detect.py:15`
- Modify: `dataset/mobs.yaml`
- Modify: `scripts/label_boxes.py`
- Modify: `scripts/prelabel_from_onnx.py:44-49`
- Create: `tests/test_label_boxes.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `OpenVinoYolo8Detect.dic_labels == {0: 'mob', 1: 'player'}`（Box.name 由它映射，Task 5 的过滤依赖 'player' 这个名字）；
  - `label_boxes.parse_label_line(line) -> [cls, cx, cy, w, h] | None`、`label_boxes.format_label_line(box) -> str`（模块级纯函数，标注 GUI 与测试共用）；
  - 标注 GUI：`c` 键切换当前类别（0=mob 红框 / 1=player 绿框），txt 首列写类别，重存不丢类别。

- [x] **Step 1: 写失败测试 `tests/test_label_boxes.py`（整文件）**

```python
# -*- coding: utf-8 -*-
"""label_boxes 的 YOLO txt 行解析/序列化:加 player 类后,类别必须往返保真。
(风险:旧版 save 写死 '0 ',重存一次会把人工标好的 player 全改回 mob。)"""
import unittest

from scripts.label_boxes import format_label_line, parse_label_line


class TestLabelLines(unittest.TestCase):

    def test_round_trip_preserves_class(self):
        for cls in (0, 1):
            line = format_label_line([cls, 0.5, 0.25, 0.1, 0.2])
            self.assertEqual(parse_label_line(line)[0], cls)

    def test_parse_legacy_mob_line(self):
        # 现存 270 帧标注全是 0 开头的旧行,必须原样读回
        self.assertEqual(parse_label_line('0 0.500000 0.250000 0.100000 0.200000'),
                         [0, 0.5, 0.25, 0.1, 0.2])

    def test_parse_rejects_malformed(self):
        self.assertIsNone(parse_label_line(''))
        self.assertIsNone(parse_label_line('0 0.5 0.25'))

    def test_format_normalized_six_decimals(self):
        self.assertEqual(format_label_line([1, 0.5, 0.25, 0.1, 0.2]),
                         '1 0.500000 0.250000 0.100000 0.200000')


if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: 跑测试确认失败**（ImportError：函数不存在）——实际 `ImportError: cannot import name 'format_label_line'`，与预期一致。

- [x] **Step 3: 改 `scripts/label_boxes.py`**

3a. 模块级纯函数（放在 `print_usage` 前）：

```python
CLASS_NAMES = {0: 'mob', 1: 'player'}
CLASS_COLORS = {0: (0, 0, 255), 1: (0, 255, 0)}   # BGR:mob 红,player 绿


def parse_label_line(line):
    """YOLO txt 行 → [cls, cx, cy, w, h];非法行 → None。旧行(0 开头)原样读回。"""
    parts = line.strip().split()
    if len(parts) != 5:
        return None
    return [int(float(parts[0]))] + list(map(float, parts[1:]))


def format_label_line(box):
    """[cls, cx, cy, w, h] → YOLO txt 行(类别保真——旧版写死 '0 ',
    重存一次会把标好的 player 全改回 mob)。"""
    return f"{int(box[0])} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f} {box[4]:.6f}"
```

3b. GUI 内部改 5 处（boxes 元素从 `[cx,cy,w,h]` 变 `[cls,cx,cy,w,h]`）：

- `label_folder` 开头加状态 `current_cls = 0`；
- `load_image` 读框改用 `parse_label_line`：
  ```python
                for line in f:
                    box = parse_label_line(line)
                    if box is not None:
                        boxes.append(box)
  ```
- `redraw` 解包与颜色：
  ```python
        for box in boxes:
            cls, cx, cy, bw, bh = box
            ...
            cv2.rectangle(img, (x1, y1), (x2, y2),
                          CLASS_COLORS.get(cls, (0, 0, 255)), 2)
  ```
- `save_current` 写行改 `f.write(format_label_line(box) + "\n")`；
- 鼠标 `LBUTTONUP` 追加框改 `boxes.append([current_cls, cx, cy, bw, bh])`（`mouse` 需 `nonlocal current_cls`？不需要——只读）；`RBUTTONDOWN` 解包改 `for i, (cls, cx, cy, bw, bh) in enumerate(boxes):`；
- 主循环加按键（放在 `elif key in (ord('r'), ...)` 之前）：
  ```python
        elif key == ord('c'):
            current_cls = 1 - current_cls
            print(f"当前类别: {current_cls} ({CLASS_NAMES[current_cls]})")
  ```
- `print_usage` 与文件 docstring 补一行 `c = 切换标注类别（0=mob 红框, 1=player 绿框）`；
- 鼠标拖拽预览矩形颜色 `(0, 255, 0)`（`mouse` 的 MOUSEMOVE 分支）改 `(255, 255, 255)` 白——绿色已让给 player 类，预览撞色会误导当前所选类别。

3c. `scripts/prelabel_from_onnx.py:49` 类别从 Box.name 来（旧模型只出 mob，新模型出两类都对）：

```python
            cls = 1 if b.name == 'player' else 0
            lines.append(f'{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}')
```

3d. `src/OpenVinoYolo8Detect.py:15`：

```python
        self.dic_labels = {0: 'mob', 1: 'player'}
```

3e. `dataset/mobs.yaml`：

```yaml
path: dataset
train: images/train
val: images/val
names:
  0: mob
  1: player
```

- [ ] **Step 4: 跑测试 + 编译检查**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_label_boxes -v
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\label_boxes.py dataset\raw\map1 --check
```
预期：单测绿；编译 OK；`--check` 打印 sanity 通过。dic_labels 无独立单测（实例化要载模型，铁律 §11.4 环境依赖）——由 Task 10 部署验证覆盖。实测全绿；`--check` 对 dataset/raw/map1 通过。

- [ ] **Step 5: 提交**

```powershell
git add src/OpenVinoYolo8Detect.py dataset/mobs.yaml scripts/label_boxes.py scripts/prelabel_from_onnx.py tests/test_label_boxes.py
git commit -m "feat: 模型类别基建——class1=player(任意玩家),标注器加类别切换,txt 类别往返保真"
```

---### Task 7: `_resolve_anchor` 插 YOLO 关联级 —— 运行时融合（核心）

**Files:**
- Modify: `src/task/MapleFarmTask.py`（DEFAULT_CONFIG、config_description、`_reset_state`、`_detect_and_act`、`_resolve_anchor`、`_log_decision`）
- Test: `tests/test_farm_task_offline.py`（`make_task` 加一行 + 追加测试类）

**Interfaces:**
- Consumes: `farm_logic.gate_player_boxes` / `select_player_box`（Task 2）、`find_all` / `find_mobs(boxes=)`（Task 5）、`decision_log_line(yolo_cands=, yolo_dist=)`（Task 4）
- Produces: 锚点来源新标签 `'yolo'`；配置键 `'YOLO角色定位开关'`(True)、`'身份保鲜(秒)'`(10)；状态 `self._last_identity_hit`、`self._last_yolo_info`；`_resolve_anchor(self, frame, now, cfg, players=())` 新签名。**签名影响面**：src 内唯一调用点 `MapleFarmTask.py:561`；但 `tests/test_farm_task_offline.py:1118-1450` 另有 18 处 3 参直呼——`players=()` 默认值让它们不传新参照旧走老阶梯（空 players → YOLO 块短路），这些旧用例必须原样保持全绿，不许改。Task 8 在同函数内接慢扫强制门。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_farm_task_offline.py`）**

```python
class TestYoloAnchorFusion(unittest.TestCase):
    """YOLO 关联级(spec §3.3/§3.4):名字牌两级都失效时接管位置;
    身份规则、冷启动、开关、伪锚点换算全在这里锁死。
    OCR 两条通道一律 patch 成 None——测的是阶梯裁决,不是 OCR。"""

    def _player(self, cx, cy, w=60, h=120):
        return SimpleNamespace(x=cx - w / 2, y=cy - h / 2,
                               width=w, height=h, name='player')

    def _task(self, players, identity_age=1.0, anchored=True, **cfg):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '决策日志开关': True, **cfg})
        task.find_all = MagicMock(return_value=list(players))
        task._boxes_enabled = MagicMock(return_value=False)
        task._key_sendable = MagicMock(return_value=True)
        if anchored:
            task._anchor = (1200.0, 900.0)
            task._anchor_time = 99.8      # 新鲜(<0.5s),不外推:搜索中心就是 1200
            task._last_anchor_hit = 99.8
        task._last_anchor_scan = 99.9     # 慢扫节流窗内 → 慢扫不参战
        task._last_identity_hit = 100.0 - identity_age
        return task

    def _beat(self, task, now=100.0):
        frame = _synthetic_frame()
        with patch.object(anchor, 'find_in_window', return_value=None), \
                patch.object(anchor, 'find_in_region', return_value=None), \
                patch('time.time', return_value=now):
            task._detect_and_act(frame, now, task.config,
                                 task.get_global_config())
        return [c.args[0] for c in task.log_debug.call_args_list
                if '决策 ' in c.args[0]]

    def test_occluded_nametag_yolo_takes_over(self):
        # 名字牌两级全失,门内一个 player 框 → src=yolo,伪锚点=框中心+偏移
        lines = self._beat(self._task([self._player(1180, 880)]))
        self.assertTrue(any('src=yolo' in l for l in lines), lines)
        # body_x = 框中心 x(伪锚点往返,spec §3.4);关联距 = |1180-1200| = 20
        self.assertTrue(any('body_x=1180' in l for l in lines), lines)
        self.assertTrue(any('yolo候选=1 关联距=20' in l for l in lines), lines)

    def test_yolo_hit_recenters_next_window(self):
        # 伪锚点喂 _update_anchor:遮挡一散名字牌在正确位置重新咬住(spec §3.4)
        task = self._task([self._player(1180, 880)])
        self._beat(task)
        self.assertEqual(task._anchor, (1180.0, 880.0 + task.config['名字牌到身体偏移(像素)']))
        self.assertEqual(task._last_anchor_hit, 100.0)

    def test_yolo_does_not_refresh_identity(self):
        # yolo 不验名,不许刷新身份时间戳(spec §3.4)
        task = self._task([self._player(1180, 880)], identity_age=5.0)
        self._beat(task)
        self.assertEqual(task._last_identity_hit, 95.0)

    def test_two_players_stale_identity_falls_to_cached(self):
        lines = self._beat(self._task(
            [self._player(1180, 880), self._player(1300, 880)],
            identity_age=30.0))
        self.assertTrue(any('src=cached' in l for l in lines), lines)
        self.assertFalse(any('src=yolo' in l for l in lines))

    def test_two_players_fresh_identity_picks_nearest(self):
        lines = self._beat(self._task(
            [self._player(1300, 880), self._player(1180, 880),
             self._player(2000, 880)],   # 第三个在门外(|2000-1200|>240):不参与,也不计入候选数
            identity_age=1.0))
        self.assertTrue(any('src=yolo' in l for l in lines), lines)
        # 候选数 = 门内 2,不是全屏 3(gate_player_boxes 口径)
        self.assertTrue(any('yolo候选=2' in l for l in lines), lines)
        self.assertTrue(any('body_x=1180' in l for l in lines), lines)

    def test_cold_start_never_uses_yolo(self):
        # 从未有过名字牌命中:没有先验位置就没有门,首个身份必须由慢扫建立
        task = self._task([self._player(1180, 880)], anchored=False)
        task._last_anchor_scan = 0.0   # 让慢扫真的跑(mock 返回 None → miss)
        lines = self._beat(task)
        self.assertTrue(any('src=fallback' in l for l in lines), lines)
        self.assertFalse(any('src=yolo' in l for l in lines))

    def test_switch_off_restores_old_ladder(self):
        lines = self._beat(self._task([self._player(1180, 880)],
                                      **{'YOLO角色定位开关': False}))
        self.assertTrue(any('src=cached' in l for l in lines), lines)

    def test_mobs_come_from_find_mobs_filter_players_from_find_all(self):
        # 分流接线:mob 走 find_mobs(boxes=find_all结果),player 走 find_all(spec §3.2)
        mob = SimpleNamespace(x=1400, y=850, width=60, height=50, name='mob')
        task = self._task([self._player(1180, 880), mob])
        task.find_mobs = MagicMock(return_value=[mob])
        lines = self._beat(task)
        task.find_mobs.assert_called_once()
        _, kwargs = task.find_mobs.call_args
        # 同一对象:分流必须吃 find_all 的结果,不许自己再推理
        self.assertIs(kwargs.get('boxes'), task.find_all.return_value)
        self.assertTrue(any('怪=1' in l for l in lines), lines)
```

- [ ] **Step 2: `make_task` 加 find_all 默认 mock（`tests/test_farm_task_offline.py:36` 的 `task.find_mobs = MagicMock(return_value=[])` 之后加一行,find_mobs 那行已存在勿重复）**

```python
    task.find_all = MagicMock(return_value=[])
```

- [ ] **Step 3: 跑测试确认失败**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_task_offline.TestYoloAnchorFusion -v
```
预期：`KeyError: 'YOLO角色定位开关'` 或 src=yolo 断言失败。

- [ ] **Step 4: 实现**

4a. `DEFAULT_CONFIG`（`'模板匹配阈值': 0.2,` 之后插入）：

```python
    'YOLO角色定位开关': True,
    '身份保鲜(秒)': 10,
```

4b. `config_description` 追加两条（放在 `'模板匹配阈值'` 条目后）：

```python
            'YOLO角色定位开关': '锚点阶梯第三级:名字牌模板与快窗 OCR 都没拿到时,用同一拍 YOLO 检出的 player 框接管角色位置(检测的是角色本体,任何名字牌遮挡都不影响;推理与找怪同拍共享,零额外开销)。身份仍由名字牌校准:该级只在已有锚点时参战,认错人风险由「身份保鲜(秒)」兜底。关掉 = 完全退回旧阶梯。丢锚拍占比 28.5%(2026-08-08 全天)的主解,详见 specs/2026-08-09-player-anchor-yolo-fusion-design.md',
            '身份保鲜(秒)': '距上次名字牌真实命中(模板/快窗/慢扫)超过此时长后,若屏幕上有多个玩家框,YOLO 级拒绝裁决(宁可退到慢扫/缓存,不认错路人);恰好只有一个玩家框时不受此限。调小 = 收紧防误认,调大 = 怪堆重度遮挡下更少丢锚。绿框跳到别的玩家身上时,先调小它',
```

4c. `_reset_state` 追加：

```python
        self._last_identity_hit = 0.0  # 上次名字牌真实命中(template/window/region)时刻;0.0=从未。多候选裁决只在保鲜窗内放行;yolo 不刷新它(它不验名,spec §3.4)
        self._last_yolo_info = None    # 本拍 YOLO 关联观测 (门内候选数, 关联水平距);None=本拍非 yolo 来源(决策日志用)
```

4d. `_detect_and_act`：行 561 前插入推理分流，行 585-589 的旧 find_mobs try 块改造。改后开头为：

```python
        try:
            all_boxes = self.find_all(frame)
        except Exception as e:
            all_boxes = []
            self._log_detect_error(now, 'YOLO 检测', e)
        players = [b for b in all_boxes if getattr(b, 'name', None) == 'player']
        anchor_hit, source = self._resolve_anchor(frame, now, cfg, players)
```

原 `try: mobs = self.find_mobs(frame) ...` 处改为：

```python
        try:
            mobs = self.find_mobs(frame, boxes=all_boxes)
        except Exception as e:
            mobs = []
            self._log_detect_error(now, 'YOLO 找怪', e)
```

（异常上下文字符串 `'YOLO 找怪'` 保持原样——`test_find_mobs_exception_stops_attack_not_task` 依赖该路径行为。）

4e. `_resolve_anchor`：签名改 `def _resolve_anchor(self, frame, now, cfg, players=()):`，函数体第一行加 `self._last_yolo_info = None`。三处名字牌命中路径（`return hit, 'template'`、`return hit, 'window'`、慢扫命中 `return hit, 'region'` 之前）各加一行 `self._last_identity_hit = now`（紧跟各自的 `self._update_anchor(hit, now)`）。快窗 OCR 的 `return hit, 'window'` 块结束之后、慢扫 `if farm_logic.should_rescan_anchor(...)` 之前（仍在 `if self._anchor is not None:` 块内）插入：

```python
            # YOLO 关联级(spec §3.3):名字牌两条通道都没拿到,用同拍 player 框接管。
            # 放在 OCR 之后——名字牌可读时身份持续刷新;放最前快通道永远轮不到,
            # 身份就再也不校准。冷启动(_anchor is None)不进本块:外层 if 已保证。
            if cfg.get('YOLO角色定位开关') and players:
                gated = farm_logic.gate_player_boxes(players, center)
                pbox = farm_logic.select_player_box(
                    gated, center,
                    now - self._last_identity_hit <= cfg['身份保鲜(秒)'])
                if pbox is not None:
                    pseudo = anchor.Anchor(
                        pbox.x + pbox.width / 2,
                        pbox.y + pbox.height / 2 + cfg['名字牌到身体偏移(像素)'],
                        pbox.width)
                    # 伪锚点 y = 框中心 + 名字牌偏移:body_center() 反算回来
                    # 正好是框中心,下游(接敌区/同层/朝向)全部不用改(spec §3.4)
                    self._last_yolo_info = (len(gated),
                                            abs(pseudo.x - center[0]))
                    self._update_anchor(pseudo, now)
                    return pseudo, 'yolo'
```

同时更新 `_resolve_anchor` docstring 的阶梯描述（模板 → 快窗 OCR → **YOLO 关联** → 慢扫 → cached → fallback）。

4f. `_log_decision`（`MapleFarmTask.py:726` 的 `self.log_debug(decision_log_line(...))`）末尾传新字段：

```python
        yolo_cands, yolo_dist = self._last_yolo_info or (None, None)
        self.log_debug(decision_log_line(
            source, body[0], anchor_hit.y, centres, in_zone, left,
            same_feet, same_center, near,
            raw_present, mob_present, attack_in, attack_present,
            facing_before, self._facing, turn, self._seek_dir,
            self._key_sendable(), observed, obs_s, obs_flip,
            yolo_cands=yolo_cands, yolo_dist=yolo_dist))
```

- [ ] **Step 5: 跑新测试类 + 全量单测**

全量必须全绿：既有 68 处 `find_mobs` mock 用例与 18 处 `_resolve_anchor` 3 参直呼用例是「接缝未破坏」的回归证明。任何一个红都说明分流动了不该动的行为——修实现，不许改旧测试。

- [ ] **Step 6: 提交**

```powershell
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 锚点阶梯插 YOLO 关联级——名字牌失效拍由 player 框接管,身份保鲜防认错"
```

---

### Task 8: 丢锚事件触发即时慢扫 —— 接线

**Files:**
- Modify: `src/task/MapleFarmTask.py`（DEFAULT_CONFIG、config_description、`_reset_state`、`_update_anchor`、`_resolve_anchor` 慢扫门、run() 受击分支 `MapleFarmTask.py:925-943`）
- Test: `tests/test_farm_task_offline.py`（追加测试类）

**Interfaces:**
- Consumes: `should_rescan_anchor(force=, last_forced=)`（Task 3）、Task 7 后的 `_resolve_anchor` 结构
- Produces: 配置键 `'丢锚立即重扫开关'`(True)；状态 `self._force_rescan`、`self._last_forced_rescan`。
- **对既有 18 处 `_resolve_anchor` 3 参直呼用例（tests:1118-1450）的影响已逐一核过为零**：`:1083` 一带角色名空短路、`:1135` 一带锚点年龄 1s < 刷新间隔 2s 不触发 force，其余慢扫用例 `_last_anchor_scan=0.0` 常规窗本就到点（force 与否同一结果）。全量绿灯的预期成立；红了修实现，不许改旧测试。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_farm_task_offline.py`）**

```python
class TestForcedRescanWiring(unittest.TestCase):
    """事件触发即时慢扫(spec §3.5):三级全失 +(受击 或 锚点超龄)→ 绕过 2s 节流。"""

    def _task(self, **cfg):
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕', **cfg})
        task.find_all = MagicMock(return_value=[])
        task._boxes_enabled = MagicMock(return_value=False)
        task._key_sendable = MagicMock(return_value=True)
        task._anchor = (1200.0, 900.0)
        task._anchor_time = 99.8
        task._last_anchor_hit = 99.8
        task._last_anchor_scan = 99.4   # 常规 2s 节流窗内:0.6s 前刚扫过
        return task

    def _beat(self, task, now=100.0):
        with patch.object(anchor, 'find_in_window', return_value=None), \
                patch.object(anchor, 'find_in_region', return_value=None) as region, \
                patch('time.time', return_value=now):
            task._detect_and_act(_synthetic_frame(), now, task.config,
                                 task.get_global_config())
        return region

    def test_knockback_flag_forces_immediate_rescan(self):
        task = self._task()
        task._force_rescan = True
        region = self._beat(task)
        region.assert_called_once()          # 节流窗内照样扫了
        self.assertFalse(task._force_rescan)  # 消费即清
        self.assertEqual(task._last_forced_rescan, 100.0)

    def test_forced_rescan_rate_limited(self):
        task = self._task()
        task._force_rescan = True
        task._last_forced_rescan = 99.7      # 0.3s 前刚强制扫过
        self._beat(task).assert_not_called()

    def test_stale_anchor_age_forces_rescan_without_knockback(self):
        task = self._task()
        task._anchor_time = 97.0             # 超龄 3s > 锚点刷新间隔 2s
        task._last_anchor_hit = 97.0
        self._beat(task).assert_called_once()

    def test_cold_start_not_forced(self):
        # 从未有锚点:保持旧 2s 节奏,不许 0.5s 高频扫(spec §3.5 冷启动例外)
        task = self._task()
        task._anchor = None
        task._anchor_time = None
        self._beat(task).assert_not_called()

    def test_switch_off_restores_throttle(self):
        task = self._task(**{'丢锚立即重扫开关': False})
        task._force_rescan = True
        self._beat(task).assert_not_called()

    def test_any_hit_clears_pending_force(self):
        # 位置重新观测到(此处 yolo 命中)→ 跳变已消化,悬着的强制扫描作废
        task = self._task()
        task._force_rescan = True
        task.find_all = MagicMock(return_value=[SimpleNamespace(
            x=1150, y=820, width=60, height=120, name='player')])
        self._beat(task)
        self.assertFalse(task._force_rescan)

    def test_knockback_sets_flag_via_run(self):
        # run() 级接线:HP 掉 2%+(受击)→ 置 _force_rescan。
        # 角色名留空:锚点通道全程短路(_scan 空目标直接 None),
        # 不 patch OCR 也绝不会真的加载 OCR 引擎(本用例只测受击接线)
        task = make_task(**{'攻击模式': '检测', '角色名': ''})
        task.find_all = MagicMock(return_value=[])
        task._boxes_enabled = MagicMock(return_value=False)
        run_with_frame(task, hp=1.0, now=100.0)
        run_with_frame(task, hp=0.9, now=100.3)
        self.assertTrue(task._force_rescan)
```

- [ ] **Step 2: 跑测试确认失败**（`KeyError: '丢锚立即重扫开关'` / assert_called 失败）

- [ ] **Step 3: 实现**

3a. `DEFAULT_CONFIG`（`'身份保鲜(秒)': 10,` 之后）：

```python
    '丢锚立即重扫开关': True,
```

3b. `config_description` 追加：

```python
            '丢锚立即重扫开关': '本拍模板/快窗OCR/YOLO 三级全没拿到位置,且(刚受击 或 锚点已超过「锚点刷新间隔」没更新)时,立刻跑一次慢扫,不等 2 秒节流——丢锚常由击退位置跳变引起,常规节流恰好卡在最需要慢扫的时刻(基线里慢扫只占 2.2%)。强制扫描自身限频 0.5 秒(慢扫最坏 235ms,不许打满主循环)。关掉 = 旧节流行为',
```

3c. `_reset_state` 追加：

```python
        self._force_rescan = False        # 受击置位:下一检测拍绕过慢扫节流(spec §3.5);任一通道命中即清(跳变已消化)
        self._last_forced_rescan = 0.0    # 上次强制慢扫时刻;0.0 哨兵=从未,配合 FORCED_RESCAN_MIN_INTERVAL 限频
```

3d. `_update_anchor` 末尾加一行（任一通道命中 = 位置重新观测到）：

```python
        self._force_rescan = False
```

3e. `_resolve_anchor` 慢扫门（`MapleFarmTask.py:433` 一带）替换为：

```python
        force = (cfg.get('丢锚立即重扫开关')
                 and (self._force_rescan
                      or (self._anchor_time is not None
                          and now - self._anchor_time > cfg['锚点刷新间隔(秒)'])))
        if farm_logic.should_rescan_anchor(now, self._last_anchor_scan,
                                           cfg['锚点刷新间隔(秒)'], force=force,
                                           last_forced=self._last_forced_rescan):
            self._last_anchor_scan = now
            if force:
                self._last_forced_rescan = now
            self._force_rescan = False   # 消费:这次扫描就是它要的那次
```

（`self._last_anchor_scan = now` 原本就在块内第一行，保持；其余慢扫体不动。锚点超龄条件排除 `_anchor_time is None`——冷启动保持旧 2s 节奏，避免无锚常态下 0.5s 高频扫。）

3f. run() 受击分支（`MapleFarmTask.py:942` 的 `self._last_turn = 0.0` 之前或之后均可，同分支内）追加：

```python
            self._force_rescan = True   # 击退=位置跳变:下一检测拍绕过慢扫节流立刻重扫(spec §3.5)
```

- [ ] **Step 4: 跑新测试类 + 全量单测全绿**

- [ ] **Step 5: 提交**

```powershell
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 丢锚立即重扫——受击/超龄触发绕过慢扫节流,命中即清,0.5s 限频"
```

---

### Task 9: 数据采集与标注（人机协作，需要游戏在前台）

**Files:**
- 产出数据：`dataset/raw/<新地图名>/*.png + *.txt`、更新 `dataset/images|labels/train|val`
- 不改代码。

**Interfaces:**
- Consumes: Task 6 的标注器（`c` 键切类别）、`scripts/record_frames.py`、`scripts/final_split.py`（用法见 `AGENTS.md` §2-3）
- Produces: 含 player 标注的完整训练集，Task 10 直接训练。

- [ ] **Step 1: 补采实战帧（用户操作游戏；本步与 §2.1 巡逻采集规范相反——要的就是战斗姿态）**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\record_frames.py combat_<地图名> 1 150
```
覆盖要求（spec §3.1，缺一类补一轮）：挥砍特效/伤害数字盖身、被击退瞬间、坐椅、怪压身，以及**有路人/队友同屏**的帧（20+ 张——融合层的「多候选拒绝」要有东西可学可测）。

- [ ] **Step 2: 旧模型预标 mob（player 第一轮没有预标，纯手标）**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\prelabel_from_onnx.py combat_<地图名> --conf 0.25
```

- [ ] **Step 3: 人工标注新帧 + 在 raw 源头给存量帧补 player 框**

**路径纪律**：`label_boxes.py` 的 txt 与 png 同目录读写（`txt_path_for`，`label_boxes.py:53-55`）；`dataset/labels/{train,val}/` 是 `final_split.py` 从 raw **拷贝**出来的产物。对 `dataset/images/train` 跑标注器会看不到既有 mob 框、还在 images 下写一套永远进不了训练集的孤儿 txt——**存量标注的唯一源头是 `dataset/raw/<地图>/`，补标只在 raw 做，改完重跑切分**。

```powershell
# 先确认哪些地图参与当前切分(看 train/val 文件名前缀,raw 现有 map1..map5)
Get-ChildItem dataset\images\train -Name | ForEach-Object { ($_ -split '_frame_')[0] } | Sort-Object -Unique
Get-ChildItem dataset\images\val -Name | ForEach-Object { ($_ -split '_frame_')[0] } | Sort-Object -Unique
# 新采的实战帧
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\label_boxes.py dataset\raw\combat_<地图名>
# 上面前缀清单里的每个存量地图逐个补标(示例 map1,其余同理)
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\label_boxes.py dataset\raw\map1
```
规则：`c` 切到 1(player,绿框) 框**所有**玩家角色（自己+路人+队友，整身含发型武器，不含名字牌文字）；**宠物不标 player**；mob 预标框逐张过目纠错。存量帧角色几乎每帧都在，逐张补一个 player 框。

- [ ] **Step 4: 重跑切分 + QC**

`final_split.py`（`scripts/final_split.py:98-113`）会先**清空** train/val 再从 raw 全量重拷——所以 Step 3 必须先在 raw 完成。`--train`/`--val` 都收多个地图名，以 Step 3 查到的前缀清单为准（脚本默认 train=map1 map2 / val=map3，**不许凭默认值猜**）：

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\final_split.py --train <既有train地图...> combat_<地图名> --val <既有val地图> --frames 50
```
QC 在 raw 做（不是 train/val——`images/` 旁没有 txt，对它开标注器一个框都看不到，正是 Step 3 的坑）：对每个参与切分的 `dataset/raw/<地图>/` 用 label_boxes 抽开 10 张目检（png+txt 同目录，红=mob、绿=player），确认 player 绿框贴身、无宠物误标、mob 框未丢类别；再抽 3 张核对切分产物——`dataset/labels/<split>/<地图>_frame_XXXX.txt` 与 raw 同名 txt 内容一致（`final_split` 是纯拷贝，`Compare-Object (Get-Content a) (Get-Content b)` 应为空）。

- [ ] **Step 5: 完成判据（无 git 产物）**

`dataset/` 整目录在 `.gitignore`（第 6-10 行按子目录、第 15 行 `/dataset`；`git ls-files dataset` 只有 `classes.txt` 与 `mobs.yaml` 两个被跟踪文件，且 mobs.yaml 已在 Task 6 提交）——**本任务没有可提交之物，不执行 git 操作**。完成判据 = Step 4 的 QC 通过 + train/val 重切分完成，向协调者报告帧数与地图清单即可。

---

### Task 10: 训练、回归门、部署

**Files:**
- 产出：`dataset/runs/mob_player_v1/weights/best.pt|best.onnx` → 部署 `assets/mob_model/mob.onnx`
- Modify: `AGENTS.md`（§3.2-3.4 过时路径顺手修正——本计划初稿照抄它踩过坑）

**Interfaces:**
- Consumes: Task 9 的数据集、`AGENTS.md` §3.2-3.4 的训练/导出/部署流程（**产物路径以下一行实证为准，不以 AGENTS.md 为准**）
- Produces: 双类别 onnx 模型；Task 11 实机验收依赖它。
- **产物路径实证**：`yolo train project=runs name=<名>`（从 dataset 目录执行）产物在 `dataset/runs/<名>/`——现有 `dataset/runs/mob_bootstrap/`（args.yaml、曲线图直接在内）就是这个结构；AGENTS.md §3.4 的 `runs/detect/runs/<名>/` 嵌套与实际不符，照抄会在 export/冒烟时找不到 best.pt。

- [ ] **Step 1: 记录现役基线 + 备份模型**

```powershell
Get-Content dataset\runs\mob_bootstrap\results.csv -Tail 3   # 现役训练(目录名以 dataset\runs\ 下实际为准),抄下 mob mAP50/mAP50-95
Copy-Item assets\mob_model\mob.onnx ("assets\mob_model\mob.onnx.bak_" + (Get-Date -Format yyyyMMdd))
```

- [ ] **Step 2: 训练（必须从 dataset 目录执行；yolov8m 200ep，4090 约 8 分钟）**

**权重注意**：项目根只有 `yolov8n.pt`，**没有 yolov8m.pt**。`model=yolov8m.pt` 用裸名（不带路径前缀）——ultralytics 对裸官方名会自动联网下载到当前目录（dataset/）；带 `..\` 前缀则按本地文件找、直接报不存在。离线环境退用 `model=..\yolov8n.pt`（n 跑通全流程，回归门照跑；player mAP50 不过门再补 m 重训）。

```powershell
Set-Location dataset
..\.venv-warrior\Scripts\yolo.exe train data=mobs.yaml model=yolov8m.pt imgsz=1280 epochs=200 batch=4 device=0 project=runs name=mob_player_v1
Set-Location ..
```

- [ ] **Step 3: 回归门（spec §3.1，不过门不许部署）**

看 `dataset/runs/mob_player_v1/` 的 per-class 指标（results.csv 末行 + 训练输出的 per-class 表）：
- mob：mAP50/mAP50-95 **不低于 Step 1 抄下的现役值**（怕加类别把找怪弄坏）；
- player：**mAP50 ≥ 0.90**。
不过 → 回 Task 9 补数据/纠标注重训。把两组数字记进提交信息。

- [ ] **Step 4: 导出 + 部署 + 冒烟**

```powershell
Set-Location dataset
..\.venv-warrior\Scripts\yolo.exe export model=runs\mob_player_v1\weights\best.pt format=onnx imgsz=1280
Set-Location ..
Copy-Item dataset\runs\mob_player_v1\weights\best.onnx assets\mob_model\mob.onnx -Force
```

冒烟（OpenVINO 路径加载新模型，双类别都出框；ultralytics 加载 onnx 会卡死 120s+，必须走 OpenVINO——AGENTS.md §2.2）：

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -c "
import cv2
from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
det = OpenVinoYolo8Detect(weights='assets/mob_model/mob.onnx', model_h=1280, model_w=1280)
img = cv2.imread('dataset/raw/map1/frame_0000.png')
boxes = det.detect(img, threshold=0.5)
names = sorted({b.name for b in boxes})
print('classes:', names, 'boxes:', len(boxes))
assert 'player' in names, 'player 类没出框'
assert 'unknown' not in names, 'dic_labels 缺映射'
"
```

- [ ] **Step 5: 修正 AGENTS.md 过时路径 + 提交（模型 99MB 在 .gitignore,不入库）**

AGENTS.md 三处按实际布局修正（其余原样，`dataset/mobs.yaml` 已在 Task 6 提交过、此处无改动）：
- §3.2 两条训练命令：`C:\projects\mxd-script\.venv-warrior\Scripts\yolo.exe` → `..\.venv-warrior\Scripts\yolo.exe`（从 dataset 执行）、`model=C:\projects\mxd-script\yolov8n.pt` → `model=..\yolov8n.pt`；
- §3.3 导出命令：`model=runs\detect\runs\<名>\weights\best.pt` → `model=runs\<名>\weights\best.pt`；
- §3.4：`训练产物在 runs/detect/runs/<名>/weights/` → `训练产物在 dataset/runs/<名>/weights/`。

```powershell
git add AGENTS.md
git commit -m "train: mob_player_v1 部署——mob mAP50 <旧→新>,player mAP50 <值>,旧模型已备份;顺手修正 AGENTS §3.2-3.4 训练路径(实证 dataset/runs/<名>/)"
```

---

### Task 11: E2E + 数据门验收（实机 ≥20 分钟）

**Files:**
- 产出：`screenshots/e2e/player-anchor-fusion/*.png`、spec 追加「执行记录」小节
- Modify: `docs/superpowers/specs/2026-08-09-player-anchor-yolo-fusion-design.md`（只追加记录，不改判据）

**Interfaces:**
- Consumes: Task 1 的 `analyze_anchor.py`、全部已合入改动、部署后的模型
- Produces: spec §5 判据 A-F 的实测结论（过/不过 + 数字）。

- [ ] **Step 1: 起 GUI 实机挂机（按 AGENTS.md §1.3/§4.1 流程）**

「实时触发」tab → 自动打怪卡片：填角色名、攻击模式=检测、打开 `决策日志开关`；到怪堆图挂 ≥20 分钟；其中**站到路人/队友旁边打 ≥3 分钟**（误认场景）。开「启用标记框」观察绿框。

- [ ] **Step 2: 数据门复算**

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\analyze_anchor.py logs\ok-script.log --since <挂机开始 HH:MM:SS>
```
判据 A/B/C/D/E 对照 spec §5 通过线；F = 20 分钟内无停机守卫触发（`Select-String '停止打怪' logs\ok-script.log`）。**任一不过：记录实际值，不许改通过线，回 spec §3 重新设计。**

- [ ] **Step 3: E2E 截图取证（按 AGENTS.md §11.5 流程,视觉模型验收）**

三张必备：怪堆遮挡中绿框咬住角色本体、路人同屏绿框没跳、决策日志里 `src=yolo` 拍的同时刻画面。存 `screenshots/e2e/player-anchor-fusion/`，文件名带日期。误认抽查：`Select-String 'src=yolo' logs\ok-script.log`（全篇命令均为 PowerShell）看 `关联距=` 分布，>150 的拍逐个对截图。

- [ ] **Step 4: 归档 + 提交**

spec 文件末尾追加「§10 执行记录（2026-08-XX 实弹）」：判据表实测值、src 分布前后对比、截图路径、遗留问题。

```powershell
git add docs/superpowers/specs/2026-08-09-player-anchor-yolo-fusion-design.md screenshots/e2e/player-anchor-fusion/
git commit -m "docs: 丢锚治理实弹验收——判据 A-F 实测归档"
```

---

## 计划自检记录

- **Spec 覆盖**：§1.3 工具→Task 1；§3.1 数据/类别→Task 6/9/10；§3.2 一拍一次推理→Task 5/7；§3.3 关联门→Task 2/7；§3.4 伪锚点/身份→Task 7；§3.5 强制慢扫→Task 3/8；§3.6 可观测→Task 1/4/11；§5 数据门→Task 11；§6 回退开关→Task 7/8 配置项 + Task 10 备份。
- **占位符**：无 TBD/TODO；所有代码块给全文或精确插入点。
- **类型一致**：`select_player_box(players, pred, identity_fresh)`（Task 2 定义 = Task 7 调用）；`gate_player_boxes`（Task 2 定义 = Task 7 计数 = Task 4 字段口径）；`should_rescan_anchor(..., force, last_forced)`（Task 3 = Task 8）；`find_mobs(boxes=)`/`find_all`（Task 5 = Task 7）；`decision_log_line(yolo_cands=, yolo_dist=)`（Task 4 = Task 7）；来源标签 `'yolo'`（Task 1 测试 = Task 7 实现）。

## 评审修订记录（2026-08-09，用户评审 7 项全部核实）

1. Task 9 补标路径：`label_boxes` txt 与 png 同目录读写，存量标注源头在 `dataset/raw/`——对 `images/` 跑标注器会产生进不了训练集的孤儿 txt。已改为 raw 源头补标 + `final_split` 重切分（其会先清空 train/val，实证 `final_split.py:98-113`）。
2. Task 9 原 `git add dataset/` 必然失败：`.gitignore` 第 6-10/15 行整目录忽略，`git ls-files dataset` 仅 classes.txt/mobs.yaml。已改为「无 git 产物」。
3. Task 10 产物路径：实证 `dataset/runs/mob_bootstrap/` 结构，`runs/detect/runs/` 嵌套是 AGENTS.md 的过时记录。已全部改为 `dataset/runs/<名>/`，并把 AGENTS.md §3.2-3.4 的修正折入 Task 10 Step 5。
4. yolov8m.pt 不在项目根（仅 n）：改用裸名 `model=yolov8m.pt` 触发 ultralytics 自动下载，离线退 n。
5. `yolo候选` 语义从全屏数改为门内候选数：新增 `gate_player_boxes` 作为门口径唯一事实源（Task 2/4/7 三处同步）。
6. `_resolve_anchor` 在 tests:1118-1450 有 18 处 3 参直呼：`players=()` 默认值保证兼容，Task 7/8 的 Interfaces 已写明影响面与 force 门零影响的逐条分析。
7. Task 7 Step 2 只加 `find_all` 一行（`find_mobs` mock 已存在于 make_task:36）；另修正 mock 计数 ~80→68、Task 11 grep→Select-String、标注器拖拽预览色让位 player 绿。

**第二轮（2026-08-09，阻断项）**：并行会话的合并 `ffc16a3` 把第一轮对 Task 2 的三处编辑（Produces/门测试/实现）与 Architecture 行盖回了旧版，导致 `gate_player_boxes` 全计划被引用却无定义——执行到 Task 7 必然 `AttributeError`。已重新打上：门控抽成 `gate_player_boxes` 独立函数（门口径唯一事实源）、`select_player_box` 首行改调它（幂等，Task 7 先 gate 后 select 语义不变）、补「返回列表」测试。同轮修正：Task 9 Step 4 的 QC 从 train/val 改到 raw 源头（旧坑复发——`images/` 旁没有 txt，标注器开了也看不到框），并补 labels/ 与 raw 同名 txt 的拷贝一致性核对；Architecture 行与 Task 5 提交信息的「80」→「68」。已知不改项：`copy_map_frames` 要求 val 地图前 N 帧连续存在（`final_split.py:55-59` 缺帧 raise），执行 Task 9 时留意 val 地图帧数 ≥ `--frames`。
