# 丢锚完全丢失治理实施计划(2026-08-10)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复丢锚完全丢失:反向外推防护 + 外推位移封顶 + YOLO 拒绝拍观测 + 丢锚唯一框接管。

**Architecture:** 判定逻辑全部落在 farm_logic 纯函数(本仓库惯例:决策在 farm_logic、
Task 只编排),MapleFarmTask 只做接线。spec:docs/superpowers/specs/2026-08-10-anchor-loss-escape-design.md。

**Tech Stack:** Python 3 + unittest(repo 测试均为 unittest 风格,pytest 可跑)。

## Global Constraints

- 判定函数必须纯函数化放 `src/task/farm_logic.py`,Task 层只做编排与状态接线。
- `decision_log_line` 是日志格式唯一事实源:新字段只能**追加行尾**、可选参数默认
  None 输出 `-`;analyze 脚本按前缀正则解析,绝不改动既有字段。
- 学习点 `anchor_vx_update` 不动;`player_gate_size` 封顶不放宽(spec §2 被否项)。
- 测试惯例:farm_logic 单测在 `tests/test_farm_logic.py`;任务层离线测试在
  `tests/test_farm_task_offline.py`,用 `make_task(**cfg)` + patch OCR 通道 + 合成帧。
- 测试命令:`python -m pytest tests/test_farm_logic.py tests/test_farm_task_offline.py -x -q`

---

### Task 1: 反向外推防护 + 外推位移封顶(spec §3.1/§3.2)

**Files:**
- Modify: `src/task/farm_logic.py`(新增 `extrapolate_vx`)
- Modify: `src/task/MapleFarmTask.py:90-94`(新常量)、`:336-354`(`_extrapolated_anchor_x` 接线)
- Test: `tests/test_farm_logic.py`(新 TestExtrapolateVx)、`tests/test_farm_task_offline.py`(TestAnchorExtrapolation 内新增/改 1 个既有用例)

**Interfaces:**
- Produces: `farm_logic.extrapolate_vx(learned_vx: float, seek_dir: str, cfg_speed: float) -> float`
  — 学习值与寻怪方向同向才用,反向/零值用 `cfg_speed × 方向`;seek_dir 只取 `'left'/'right'`。
- Produces: `MapleFarmTask.ANCHOR_EXTRAPOLATE_MAX_DX = 500`(模块常量,px)。

- [ ] **Step 1: 写 farm_logic 失败测试**

在 `tests/test_farm_logic.py` 的 `TestAnchorTiming` 之后新增:

```python
class TestExtrapolateVx(unittest.TestCase):
    """外推速度裁决(spec 2026-08-10 §3.1):击退漂移几乎恒与寻怪反向,
    学来的反向 vx 会把外推往真人反方向推(丢失逃逸根因,08-10 19:56 钳位铁证)。"""

    def test_same_direction_uses_learned(self):
        self.assertEqual(fl.extrapolate_vx(120.0, 'right', 250), 120.0)

    def test_reverse_falls_back_to_config_speed(self):
        # 学习到 +75(击退向右),寻怪向左 → 不用学习值,用配置速度×方向
        self.assertEqual(fl.extrapolate_vx(75.0, 'left', 250), -250.0)

    def test_zero_learned_uses_config_speed(self):
        self.assertEqual(fl.extrapolate_vx(0.0, 'right', 200), 200.0)
        self.assertEqual(fl.extrapolate_vx(0.0, 'left', 200), -200.0)

    def test_none_seek_dir_returns_zero(self):
        # 契约外输入显式不外推(唯一调用点在 _seek_dir is None 时提前返回,
        # 这里防未来调用点踩坑——None 绝不能被静默当成 left)
        self.assertEqual(fl.extrapolate_vx(120.0, None, 250), 0.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_farm_logic.py::TestExtrapolateVx -v`
Expected: FAIL — `AttributeError: module 'src.task.farm_logic' has no attribute 'extrapolate_vx'`

- [ ] **Step 3: 实现 `extrapolate_vx`**

在 `src/task/farm_logic.py` 的 `anchor_vx_update` 之后新增:

```python
def extrapolate_vx(learned_vx, seek_dir, cfg_speed):
    """外推速度(像素/秒):学习值与寻怪方向**同向**才用,反向/无学习值用配置速度×方向。

    击退方向几乎恒与寻怪方向相反(朝怪走、被怪打回来),学来的反向 vx 是击退残余,
    不是行走速度——直接外推会把 pred 往真人反方向推,1s 内逃出所有关联门
    (2026-08-10 19:56 日志铁证:cached 拍 x=2560 钳位而 寻怪=left)。
    学习点(anchor_vx_update)不动:残余会在下一次真实行走观测时被低通自然替换。
    """
    if seek_dir not in ('left', 'right'):
        return 0.0   # 契约外输入:不外推(调用点已保证非 None,这里防御)
    sign = 1.0 if seek_dir == 'right' else -1.0
    if learned_vx != 0.0 and learned_vx * sign > 0:
        return learned_vx
    return cfg_speed * sign
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_farm_logic.py::TestExtrapolateVx -v`
Expected: PASS(4 个用例)

- [ ] **Step 5: 写任务层失败测试(反向逃逸 + 封顶),并改 1 个既有用例**

在 `tests/test_farm_task_offline.py` 的 `TestAnchorExtrapolation` 类内新增:

```python
    def test_reverse_learned_vx_does_not_escape(self):
        """回归(08-10 19:56 钳位铁证):学到 +vx(击退向右)但寻怪向左 →
        外推不许往右逃,退回配置速度×寻怪方向。
        速度取 150:150*3=450 < 500 不触帽——这条只测方向,与
        test_extrapolation_capped_at_max_dx 职责分离。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 150})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._anchor_vx = 75.0           # 击退残余(向右)
        task._last_anchor_hit = 102.0    # 实测速度仍新鲜
        task._seek_dir = 'left'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 103.0, task.config)
        self.assertEqual(got.x, 1280 - 150 * 3)  # 830;旧逻辑会给 1280+75*3=1505

    def test_extrapolation_capped_at_max_dx(self):
        """丢锚期外推位移封顶 ±500(拆振荡回路,08-10 21:18 外推↔寻怪反馈):
        年龄再大,位移也不超 2s 行走量。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 250})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = 'right'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 108.0, task.config)
        self.assertEqual(got.x, 1280 + 500.0)  # 250*8=2000 → 钳 500

    def test_extrapolation_clamped_to_frame_edge(self):
        """封顶与帧边界 [0,2560] 的复合(spec §6):锚点在 x=100、寻怪 left →
        dx 钳 -500 后 x=-400,再钳到 0,绝不出负坐标。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 250})
        task._anchor = (100.0, 800.0)
        task._anchor_time = 100.0
        task._seek_dir = 'left'
        with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
            got, _ = task._resolve_anchor(_synthetic_frame(), 106.0, task.config)
        self.assertEqual(got.x, 0.0)

    def test_oscillation_bounded_when_seek_flips(self):
        """回归(spec §6 振荡剧本,08-10 21:18):丢锚期寻怪方向每拍翻转,
        相邻 cached 拍 |Δbody_x| ≤ 2×500=1000(旧逻辑外推位移随年龄无界,
        实测单拍跳 ±1250px+,门中心跟着瞬移,YOLO 关联被主动压死)。"""
        task = make_task(**{'攻击模式': '检测', '角色名': 'Yufeng咕咕',
                            '寻怪外推速度(像素/秒)': 250})
        task._anchor = (1280.0, 800.0)
        task._anchor_time = 100.0
        xs = []
        for i, d in enumerate(['right', 'left', 'right', 'left']):
            task._seek_dir = d
            with patch('src.task.MapleFarmTask.anchor.find_in_window', return_value=None), \
                    patch('src.task.MapleFarmTask.anchor.find_in_region', return_value=None):
                got, source = task._resolve_anchor(_synthetic_frame(), 106.0 + i, task.config)
            self.assertEqual(source, 'cached')
            xs.append(got.x)
        self.assertTrue(all(abs(b - a) <= 1000 for a, b in zip(xs, xs[1:])),
                        xs)
```

**改既有用例** `test_cached_anchor_extrapolates_with_seek_speed`(封顶改变了它的旧契约):
断言从 `1280 + 200 * 3`(=1880,位移 600 超帽)改为钳位值,两处:

```python
        self.assertEqual(got.x, 1280 + 500.0)                     # 600 → 钳 500
        ...
        self.assertEqual(window.call_args[0][2], (1280 + 500.0, 800.0))
```

- [ ] **Step 6: 跑这两个新测试确认失败**

Run: `python -m pytest tests/test_farm_task_offline.py::TestAnchorExtrapolation -v`
Expected: 新用例 FAIL(pred 仍按旧逻辑 1280+75*3=1505 / 1280+2000 钳到 2560),
改过的既有用例也 FAIL(它断言的 1880 正是旧行为)

- [ ] **Step 7: 接线 `_extrapolated_anchor_x`**

`src/task/MapleFarmTask.py` 常量区(`ANCHOR_DEFAULT_SPEED` 旁)加:

```python
ANCHOR_EXTRAPOLATE_MAX_DX = 500  # 外推位移上限(px)≈2s 行走量:拆丢锚期外推↔寻怪振荡回路
```

`_extrapolated_anchor_x` 的速度选取与返回段(现 349-354 行)改为:

```python
        learned = (self._anchor_vx
                   if now - self._last_anchor_hit <= ANCHOR_VX_MAX_AGE else 0.0)
        speed = cfg.get('寻怪外推速度(像素/秒)', ANCHOR_DEFAULT_SPEED)
        vx = farm_logic.extrapolate_vx(learned, self._seek_dir, speed)
        dx = max(-ANCHOR_EXTRAPOLATE_MAX_DX,
                 min(ANCHOR_EXTRAPOLATE_MAX_DX, vx * age))
        return max(0.0, min(CALIBRATED_SIZE[0], self._anchor[0] + dx))
```

并在该函数 docstring 末尾补一行:`位移钳在 ±ANCHOR_EXTRAPOLATE_MAX_DX:丢锚期
外推随年龄线性放大会与寻怪决策形成振荡反馈(2026-08-10 21:18 日志,pred 每拍
跳 ±1250px);反向学习速度由 farm_logic.extrapolate_vx 拦截。`

- [ ] **Step 8: 全量跑两个测试文件确认通过**

Run: `python -m pytest tests/test_farm_logic.py tests/test_farm_task_offline.py -x -q`
Expected: PASS(含全部既有用例)

- [ ] **Step 9: Commit**

```bash
git add src/task/farm_logic.py src/task/MapleFarmTask.py tests/test_farm_logic.py tests/test_farm_task_offline.py
git commit -m "feat: 反向外推防护 + 外推位移封顶——治丢锚逃逸与丢失期振荡(08-10 钳位/振荡铁证)"
```

---

### Task 2: YOLO 拒绝拍补观测(spec §3.3)

**Files:**
- Modify: `src/task/MapleFarmTask.py:106-142`(`decision_log_line`)、`:291`/`:472`/`:536-558`(`_last_yolo_info` 三处)、`:919-926`(解包与传参)
- Test: `tests/test_farm_task_offline.py`(TestDecisionLineYoloFields 改 1 增 2;TestYoloAnchorFusion 增 1)

**Interfaces:**
- Consumes: 无(独立改动)。
- Produces: `self._last_yolo_info` 改为 **3 元组** `(门内候选数, 关联距 or None, 全屏 player 框数)`,
  None=本拍 YOLO 级未到达;`decision_log_line(..., yolo_full=None)` 新可选参数,
  行尾追加 ` yolo全屏=N`(None → `-`);`_resolve_anchor` 签名默认值
  `players=()` → `players=None`(None=无推理短路,[]=推理了但全屏 0 框,照常走完 YOLO 级)。
  Task 3 依赖此三元素结构;players=None 语义 Task 3 的接管同样受 guard 约束。

- [ ] **Step 1: 写格式层失败测试 + 改行尾断言**

`tests/test_farm_task_offline.py` 的 `TestDecisionLineYoloFields`:

把 `test_fields_appended_at_line_end` 的断言改为新行尾:

```python
    def test_fields_appended_at_line_end(self):
        # 追加在行尾:analyze_anchor/analyze_seek 的前缀正则不受影响
        self.assertTrue(self._line().endswith('关联距=- yolo全屏=-'))
```

新增:

```python
    def test_full_count_rendered_when_present(self):
        self.assertIn('yolo候选=0 关联距=- yolo全屏=1',
                      self._line(yolo_cands=0, yolo_full=1))

    def test_full_count_dash_when_absent(self):
        self.assertIn('yolo全屏=-', self._line(yolo_cands=2, yolo_dist=35.4))
```

- [ ] **Step 2: 跑确认失败**

Run: `python -m pytest tests/test_farm_task_offline.py::TestDecisionLineYoloFields -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'yolo_full'`;行尾断言也 FAIL

- [ ] **Step 3: `decision_log_line` 加字段**

`src/task/MapleFarmTask.py` 签名加 `yolo_full=None`(放 `yolo_dist=None` 后),
返回值行尾(142 行括号内)追加:

```python
            f' yolo全屏={yolo_full if yolo_full is not None else "-"}'
```

docstring 中「yolo候选 / 关联距 是 YOLO 关联级(spec §3.6)的观测」一段末尾补:
`yolo全屏 = 同拍全屏 player 框数(含门外):候选=0 全屏≥1 = 检出被门拒,
候选=0 全屏=0 = YOLO 跑了但全屏无 player 框,全=- = YOLO 级未到达
(模板/快窗命中)或定频无推理(2026-08-10 spec §3.3)。`

- [ ] **Step 4: 跑确认通过**

Run: `python -m pytest tests/test_farm_task_offline.py::TestDecisionLineYoloFields -v`
Expected: PASS

- [ ] **Step 5: 写行为层失败测试(拒绝拍记观测)**

在 `TestYoloAnchorFusion` 内新增(复用该类 `_task`/`_beat`/`_player`):

```python
    def test_rejected_beat_records_full_screen_count(self):
        # 多候选 + 身份过期 → 拒裁退 cached,但观测必须留痕:
        # yolo候选=2(门内) yolo全屏=2,不再是 '-/-' 的盲区(spec §3.3)
        lines = self._beat(self._task(
            [self._player(1180, 880), self._player(1300, 880)],
            identity_age=30.0))
        self.assertTrue(any('src=cached' in l for l in lines), lines)
        self.assertTrue(any('yolo候选=2 关联距=- yolo全屏=2' in l
                            for l in lines), lines)

    def test_empty_screen_records_zero_not_dash(self):
        # YOLO 跑了但全屏 0 个 player 框 → 候选=0 全屏=0(可达状态:
        # 「推理了没框」与「YOLO 级未到达」必须分得开,这正是排查被挡两次的盲区)
        lines = self._beat(self._task([]))
        self.assertTrue(any('src=cached' in l for l in lines), lines)
        self.assertTrue(any('yolo候选=0 关联距=- yolo全屏=0' in l
                            for l in lines), lines)

    def test_window_beat_yolo_fields_all_dash(self):
        # YOLO 级未到达(快窗命中)→ 三个字段全 '-'
        task = self._task([self._player(1180, 880)])
        hit = AnchorHit(1200.0, 900.0, 130, 'Yufeng咕咕')
        frame = _synthetic_frame()
        with patch.object(anchor, 'find_in_window', return_value=hit), \
                patch.object(anchor, 'find_in_region', return_value=None), \
                patch('time.time', return_value=100.0):
            task._detect_and_act(frame, 100.0, task.config, task.get_global_config())
        lines = [c.args[0] for c in task.log_debug.call_args_list
                 if '决策 ' in c.args[0]]
        self.assertTrue(any('src=window' in l for l in lines), lines)
        self.assertTrue(all('yolo候选=- 关联距=- yolo全屏=-' in l
                            for l in lines), lines)
```

- [ ] **Step 6: 跑确认失败**

Run: `python -m pytest tests/test_farm_task_offline.py::TestYoloAnchorFusion -v`
Expected: `test_rejected_beat_records_full_screen_count` 与
`test_empty_screen_records_zero_not_dash` FAIL(现在拒绝拍/空屏拍都记 `-`)

- [ ] **Step 7: `_last_yolo_info` 三元素化 + 到达即留痕**

`src/task/MapleFarmTask.py`:

① 签名 `:454` 改为 `def _resolve_anchor(self, frame, now, cfg, players=None):`,
docstring 中「players 为空(旧 3 参调用/定频模式)时 YOLO 级短路」改为:
`players=None(旧 3 参调用/定频模式,本拍无推理)时 YOLO 级短路、行为完全退回
旧阶梯;players=[](推理了但全屏无 player 框)正常走完 YOLO 级并记 yolo全屏=0。
生产唯一调用点(:725)恒传真实 list,None 默认值只服务旧测试调用。`
（用 None/[] 区分「没推理」与「推理了没框」——全屏=0 要可达,否则
「YOLO 到底有没有看见人」仍是盲区。)

② `:291` 与 `:471` 的注释改为 `(门内候选数, 关联距 or None, 全屏框数);None=本拍 YOLO 级未到达`(赋值仍是 None,不用改)。

③ YOLO 关联级(`:538` 的 guard 与 `:543-546` 的 gated/pbox 段)改为**到达即留痕、
拒绝拍更新门内数**:

```python
            if cfg.get('YOLO角色定位开关') and players is not None:
                # 到达即留痕(spec §3.3):全屏数含 0——「没检出 vs 未到达」不再盲区;
                # 门内数算出后更新,接受拍再用真实关联距覆盖
                self._last_yolo_info = (0, None, len(players))
                # 门随「距上次真观测的时长」缩放(位移合理性,spec §3.3):相邻拍
                # 收到 ~170px,路人挤不进来;久未观测再放回固定上限
                gate_w, gate_h = farm_logic.player_gate_size(
                    now - self._last_anchor_hit if self._last_anchor_hit else None)
                gated = farm_logic.gate_player_boxes(players, center, gate_w, gate_h)
                self._last_yolo_info = (len(gated), None, len(players))
                pbox = farm_logic.select_player_box(
                    gated, center, identity_fresh, gate_w, gate_h)
```

（guard 从 `and players` 改为 `and players is not None`:players=[] 时
gated=[]、select 返回 None,行为与旧短路一致,只多了留痕。)

④ 接受分支现 `:555-556` 改为三元素:

```python
                    self._last_yolo_info = (len(gated),
                                            abs(pseudo.x - center[0]),
                                            len(players))
```

⑤ `:919` 解包与 `:926` 传参改为:

```python
        yolo_cands, yolo_dist, yolo_full = self._last_yolo_info or (None, None, None)
        ...
            yolo_cands=yolo_cands, yolo_dist=yolo_dist, yolo_full=yolo_full))
```

- [ ] **Step 8: 全量跑确认通过**

Run: `python -m pytest tests/test_farm_task_offline.py tests/test_analyze_anchor.py tests/test_analyze_facing.py tests/test_analyze_seek.py tests/test_analyze_turn.py -x -q`
Expected: PASS(analyze 系列验证格式追加不破坏前缀解析)

- [ ] **Step 9: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: YOLO 拒绝拍留痕 yolo全屏=——区分没检出/检出被拒/多候选拒裁"
```

---

### Task 3: 丢锚唯一框接管 + 配置开关(spec §3.4)

**Files:**
- Modify: `src/task/farm_logic.py`(新常量 + `select_lost_unique_box`)
- Modify: `src/task/MapleFarmTask.py:67` 附近(配置默认值)、`:219` 附近(配置说明)、`:536-558`(YOLO 级内接线)
- Test: `tests/test_farm_logic.py`(新 TestSelectLostUniqueBox)、`tests/test_farm_task_offline.py`(TestYoloAnchorFusion 增 3)

**Interfaces:**
- Consumes: `farm_logic.player_box_anchor`(既有);Task 2 的 `_last_yolo_info` 三元素结构。
- Produces: `farm_logic.LOST_UNIQUE_MIN_AGE = 1.0`、`farm_logic.LOST_UNIQUE_GATE_Y = 300`;
  `farm_logic.select_lost_unique_box(players, pred_y, anchor_age, min_age=1.0, gate_y=300) -> box | None`;
  配置键 `丢锚唯一框接管开关`(默认 True)。

- [ ] **Step 1: 写 farm_logic 失败测试**

`tests/test_farm_logic.py` 末尾新增(伪框惯例见该文件既有 `type('Box', (), {...})()`):

```python
class TestSelectLostUniqueBox(unittest.TestCase):
    """丢锚唯一框接管(spec 2026-08-10 §3.4):丢锚超 1s 且全屏唯一 player 框
    且同层(±300) → 直接接管。唯一性=身份判据;横向不看门(pred 已逃逸,
    横向先验已死),纵向先验仍活(外推只推 x)。"""

    def _player(self, cx, cy):
        return type('Box', (), {'x': cx - 30, 'y': cy - 60,
                                'width': 60, 'height': 120})()

    def test_accepts_unique_same_layer_box(self):
        box = self._player(2000, 880)   # 横向距 pred 800px(门外),纵向同层
        got = fl.select_lost_unique_box([box], pred_y=900.0, anchor_age=2.0)
        self.assertIs(got, box)

    def test_rejects_when_age_insufficient(self):
        box = self._player(2000, 880)
        self.assertIsNone(
            fl.select_lost_unique_box([box], pred_y=900.0, anchor_age=0.9))

    def test_age_boundary_accepts(self):
        # 压线:年龄恰好 1.0s 算丢锚(与 anchor_expired 的 >= 口径一致)
        box = self._player(2000, 880)
        self.assertIs(
            fl.select_lost_unique_box([box], pred_y=900.0, anchor_age=1.0), box)

    def test_rejects_multiple_boxes(self):
        # 多框 = 可能多人图,宁可慢扫不认错(行为不变)
        boxes = [self._player(2000, 880), self._player(600, 880)]
        self.assertIsNone(
            fl.select_lost_unique_box(boxes, pred_y=900.0, anchor_age=5.0))

    def test_rejects_off_layer_box(self):
        # 隔层路人:|by - pred_y| > 300 拒(实测层高差 240-300)
        box = self._player(2000, 1200)  # by = 1200+64 = 1264,差 364
        self.assertIsNone(
            fl.select_lost_unique_box([box], pred_y=900.0, anchor_age=5.0))

    def test_layer_boundary_accepts(self):
        # 压线:|dy| 恰 300 算同层(与 gate_player_boxes 边界算门内一致)
        box = self._player(2000, 1136)  # by = 1136+64 = 1200,差恰 300
        self.assertIs(
            fl.select_lost_unique_box([box], pred_y=900.0, anchor_age=5.0), box)
```

- [ ] **Step 2: 跑确认失败**

Run: `python -m pytest tests/test_farm_logic.py::TestSelectLostUniqueBox -v`
Expected: FAIL — `AttributeError: ... 'select_lost_unique_box'`

- [ ] **Step 3: 实现 `select_lost_unique_box`**

`src/task/farm_logic.py` 的 `select_player_box` 之后新增:

```python
LOST_UNIQUE_MIN_AGE = 1.0   # 丢锚超此时长(秒)才允许唯一框接管:新鲜丢失先走常规门
LOST_UNIQUE_GATE_Y = 300    # 唯一框纵向门(px):实测层高差 240-300,换层接得住、隔层挡得住


def select_lost_unique_box(players, pred_y, anchor_age,
                           min_age=LOST_UNIQUE_MIN_AGE, gate_y=LOST_UNIQUE_GATE_Y):
    """丢锚末级安全网(spec 2026-08-10 §3.4):常规门裁决失败后,
    丢锚超 min_age 且全屏**恰好 1 个** player 框且同层 → 直接接管。

    唯一性就是身份判据(单人挂机全屏 1 框几乎恒是自己,与 select_player_box
    「门内恰 1 个不看身份」同理,范围扩到全屏)。横向不看门:pred 已逃逸,
    横向先验已死;纵向先验仍活(外推只推 x),±gate_y 挡住隔层路人。
    多框拒裁:多人图宁可慢扫不认错。认错上界 = 名字牌下次可读 + 复验间隔,
    身份时间戳不由本通道刷新(yolo 级既有纪律)。
    """
    if anchor_age is None or anchor_age < min_age or len(players) != 1:
        return None
    _, by = player_box_anchor(players[0])
    if abs(by - pred_y) > gate_y:
        return None
    return players[0]
```

- [ ] **Step 4: 跑确认通过**

Run: `python -m pytest tests/test_farm_logic.py::TestSelectLostUniqueBox -v`
Expected: PASS(6 个用例)

- [ ] **Step 5: 写任务层失败测试**

在 `TestYoloAnchorFusion` 内新增:

```python
    def test_lost_unique_box_takes_over_beyond_gate(self):
        # 丢锚 3s + 全屏唯一框在门外(横向 800px)→ 末级接管,一拍 src=yolo
        # (08-09/08-10 两次完全丢失的主修复:不再等名字牌可读的慢扫)
        task = self._task([self._player(2000, 880)], identity_age=30.0)
        task._anchor_time = 97.0        # 丢锚 3s(now=100)
        lines = self._beat(task)
        self.assertTrue(any('src=yolo' in l for l in lines), lines)
        self.assertTrue(any('body_x=2000' in l for l in lines), lines)
        # 接管不刷身份时间戳:认错路人靠复验慢扫兜底,整条风险章都押在这行上
        self.assertEqual(task._last_identity_hit, 70.0)
        # 已知且接受:接管瞬移会被 anchor_vx_update 学习(dx=800/dt=3=267px/s,
        # 在 600 跳变门内)——由外推 ±500 封顶与反向防护兜底(spec §5 已记),
        # 这条断言锁的是「我们知道它在学」,不是「它不该学」
        self.assertAlmostEqual(task._anchor_vx, 0.7 * 800 / 3, places=5)

    def test_lost_unique_box_respects_switch_off(self):
        task = self._task([self._player(2000, 880)], identity_age=30.0,
                          **{'丢锚唯一框接管开关': False})
        task._anchor_time = 97.0
        lines = self._beat(task)
        self.assertFalse(any('src=yolo' in l for l in lines), lines)

    def test_lost_unique_box_rejects_multiple_players(self):
        # 丢锚再久,全屏 ≥2 框也不接管(多人图保守,spec §3.4)
        task = self._task([self._player(2000, 880), self._player(600, 880)],
                          identity_age=30.0)
        task._anchor_time = 97.0
        lines = self._beat(task)
        self.assertFalse(any('src=yolo' in l for l in lines), lines)
```

- [ ] **Step 6: 跑确认失败**

Run: `python -m pytest tests/test_farm_task_offline.py::TestYoloAnchorFusion -v`
Expected: `test_lost_unique_box_takes_over_beyond_gate` FAIL(现逻辑门外拒收)

- [ ] **Step 7: 接线 + 配置键**

① `src/task/MapleFarmTask.py` 默认配置 `'丢锚立即重扫开关': True,` 之后加:

```python
    '丢锚唯一框接管开关': True,
```

② 配置说明区(`'丢锚立即重扫开关': '...'` 条目后)加:

```python
            '丢锚唯一框接管开关': '丢锚超过 1 秒、常规关联门裁决失败时,若全屏恰好只有 1 个玩家框且与最后已知层高同层(±300px),直接认定是自己接管位置——唯一性就是身份判据(单人挂机全屏 1 框几乎恒是自己),横向不再看已失效的外推门。认错路人的上界 = 名字牌下次可读 + 身份复验间隔(秒级),复验慢扫会纠正;全屏 ≥2 个玩家框时不接管(多人图保守)。关掉 = 只靠慢扫找回(旧行为)',
```

③ YOLO 关联级接线(`pbox = farm_logic.select_player_box(...)` 之后、`if pbox is not None:` 之前)插入:

```python
                if pbox is None and cfg.get('丢锚唯一框接管开关'):
                    # 末级安全网(spec 2026-08-10 §3.4):丢锚超 1s + 全屏唯一框
                    # + 同层 → 直接接管。pred_y 用搜索中心 y(=最后锚点 y,
                    # 外推不推 y,纵向先验仍可信)
                    pbox = farm_logic.select_lost_unique_box(
                        players, center[1], now - self._anchor_time)
```

接受分支(`if pbox is not None:` 内)不用改:pseudo 换算、`_update_anchor`、
`_last_yolo_info` 三元素都对唯一框接管天然成立(门内候选数记 0,关联距
记真实偏差,全屏记 1,日志可区分接管来源)。

- [ ] **Step 8: 全量跑确认通过**

Run: `python -m pytest tests/test_farm_logic.py tests/test_farm_task_offline.py -x -q`
Expected: PASS。重点盯三条既有用例必须保持绿:
- `test_two_players_stale_identity_falls_to_cached`(多框不接管);
- `test_gate_narrows_with_fresh_observation`(:2815,单框在门外 200px 拒收——
  它只凭 anchor_age=0.2 < LOST_UNIQUE_MIN_AGE 躲过接管,是「接管是否过于
  激进」的金丝雀,它红 = 接管条件太松);
- `test_gate_widens_after_long_loss`(久丢宽门收人,与末级接管不冲突)。

- [ ] **Step 9: Commit**

```bash
git add src/task/farm_logic.py src/task/MapleFarmTask.py tests/test_farm_logic.py tests/test_farm_task_offline.py
git commit -m "feat: 丢锚唯一框接管——全屏唯一玩家框+同层直接认定,不再苦等名字牌慢扫"
```

---

## 自审记录(写计划时已做;评审后修订)

- spec 覆盖:§3.1→Task 1 Steps 1-4;§3.2→Task 1 Steps 5-9(含帧边界复合与振荡
  剧本两个用例);§3.3→Task 2(含全屏=0 可达化);§3.4→Task 3;§4 配置键→
  Task 3 Step 7;§6 测试→各 Task 的 TDD 步骤;§3.5 可观测性验收为实测项,不进代码任务。
- 既有契约变更只有两处,都已显式列入步骤:`test_cached_anchor_extrapolates_with_seek_speed`
  (封顶 600→500,Task 1 Step 5)、`test_fields_appended_at_line_end`(行尾新增字段,
  Task 2 Step 1)。
- 类型一致性:`_last_yolo_info` 三元素在 Task 2 定义、Task 3 复用;
  `select_lost_unique_box` 签名在 Task 3 的测试/实现/接线三处一致。
- 评审修订(2026-08-10):①反向逃逸用例速度 200→150,与封顶用例职责分离
  (原断言 680 会被 ±500 帽钳成 780,自相矛盾);②`players=()` 改 `players=None`,
  全屏=0 状态可达化,docstring 三态语义同步;③接管用例补「不刷身份」与
  「vx 瞬移学习已知且接受」两条断言;④Step 8 金丝雀名单补
  `test_gate_narrows_with_fresh_observation`/`test_gate_widens_after_long_loss`;
  ⑤`extrapolate_vx` 补 None 防御与显式测试;⑥常量名统一
  LOST_UNIQUE_MIN_AGE/LOST_UNIQUE_GATE_Y(spec §4 已回改)。
