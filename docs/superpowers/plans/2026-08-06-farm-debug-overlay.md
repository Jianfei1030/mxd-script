# MapleFarmTask 调试可视化(攻击区/角色/怪物框)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打开 GUI Start 页已有的「启用标记框」(Enable Boxes)开关时,实际挂机任务 `MapleFarmTask` 在检测模式下实时画出玩家框/攻击区框(有怪变红)/怪物框+脚底点;关掉开关或切到定频模式时不画、并清掉已画的。

**Architecture:** 在 `MapleFarmTask._detect_and_act()` 里(已经算出 body/zone/mobs/mob_present,不重复检测)按 `_boxes_enabled()` 的结果调 `_draw_debug()` 或 `_clear_debug()`。`_boxes_enabled()` 直接读框架全局配置 `og.app.ok_config['use_overlay']`(与 `ok/feature/FeatureSet.py::_draw_boxes_enabled` 同一读法),不新增任务级开关。overlay 画笔风格照抄 `WarriorDebugTask._draw_debug`(`get_overlay_view().draw(key, paint_fn)` + `widget.frame_ratio()` 坐标换算),用独立 key `maple_farm_debug`,与 `WarriorDebugTask` 的 `warrior_debug` 互不干扰。

**Tech Stack:** Python, PySide6(QRectF/QColor/QPen),现有 `ok` 框架的 overlay 机制,unittest + unittest.mock(项目现有 offline 测试风格,不起真实 GUI)。

## Global Constraints

- 只改 `src/task/MapleFarmTask.py` 和 `tests/test_farm_task_offline.py`——不改 `WarriorDebugTask.py`(spec §3.5)
- 新增 overlay 画笔 key 必须是 `'maple_farm_debug'`,与 `WarriorDebugTask` 的 `'warrior_debug'` 不同
- 新增配置键 `玩家宽(像素)`(默认 60)、`玩家高(像素)`(默认 120)仅用于调试画框尺寸,不参与任何攻击判定逻辑
- 不做像素级 painter 内容单测(Qt paint 回调离线测试验证不了);测试只断言方法调用与否、调用参数
- 定频模式(`攻击模式=定频`)不画任何调试框(该模式没有锚点/攻击区概念)

---

## 现状(实现前必读)

`src/task/MapleFarmTask.py` 当前(截至本计划写作时)有一个**并行进行中、未提交**的名字牌模板匹配功能改动(`_nametag_template`/`_capture_nametag_template`/`AnchorHit` 等),与本计划无关但共享同一文件。实现本计划任何一个 Task 前,**先跑 `git diff -- src/task/MapleFarmTask.py` 确认文件当前内容**,不要假设它等于本计划里贴的代码片段逐字节一致——按"在哪个方法里加什么"去定位,而不是逐行盲搬。

`_detect_and_act()` 当前结构(锚点/找怪逻辑已存在,本计划只在其中插入调试绘制调用,不改锚点/攻击逻辑本身):

```python
def _detect_and_act(self, frame, now, cfg, keys):
    anchor_hit, source = self._resolve_anchor(frame, now, cfg)
    body = anchor.body_center(anchor_hit, cfg['名字牌到身体偏移(像素)'])
    zone = farm_logic.attack_zone(body, cfg['攻击区宽(像素)'], cfg['攻击区高(像素)'])
    try:
        mobs = self.find_mobs(frame)
    except Exception as e:
        mobs = []
        self._log_detect_error(now, 'YOLO 找怪', e)
    centres = [(m.x + m.width / 2, m.y + m.height / 2) for m in mobs]
    mob_present = farm_logic.mob_in_zone(centres, zone)
    self._last_mob_present = mob_present
    if mob_present:
        ...
    else:
        ...
```

`run()` 里攻击分支(第 4 步)当前结构:

```python
        # 4. 攻击
        if cfg['攻击模式'] == '检测':
            if farm_logic.should_attack(now, self._last_detect, cfg['攻击间隔(秒)']):
                self._last_detect = now
                self._detect_and_act(frame, now, cfg, keys)
            elif cfg['寻怪开关'] and self._seek_dir is not None and farm_logic.should_attack(
                    now, self._last_seek_refresh, cfg['寻怪刷新间隔(秒)']):
                self._last_seek_refresh = now
                self._detect_and_act(frame, now, cfg, keys)
            self._do_attack_hold(cfg, keys)
            self._do_seek_move(cfg, keys)
            if self._last_mob_present or self._seek_dir is not None:
                self._mark_busy(now)
        elif farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
            self.send_key(keys['攻击键'])
            self._last_attack = now
```

`disable()` / `on_destroy()` 当前都只有一行 `self._release_held_keys()` + `super().xxx()`。

`tests/test_farm_task_offline.py` 的 `make_task()` 辅助函数(第 17-34 行)用 `MapleFarmTask.__new__` 绕过框架 `__init__`,手工装配 mock 属性;本计划的测试复用它,只需按需追加 mock。姊妹文件 `tests/test_warrior_debug_offline.py` 对 `WarriorDebugTask` 的调试绘制用的是 `patch.object(TaskClass, '_draw_debug')` 断言"调用与否 + 调用参数",本计划的测试照抄这个模式(不测 Qt paint 内部)。

---

### Task 1: `_boxes_enabled()` 门控读取

**Files:**
- Modify: `src/task/MapleFarmTask.py`(新增方法,放在 `_slot_of` 附近或类内任意静态/实例方法区均可,建议紧挨 `_resolve_facing` 之前)
- Test: `tests/test_farm_task_offline.py`(新增 `TestBoxesEnabled` 测试类)

**Interfaces:**
- Produces: `MapleFarmTask._boxes_enabled(self) -> bool` —— 供 Task 2 在 `_detect_and_act` 里调用;`from ok import og`,读 `og.app.ok_config.get('use_overlay', False)`,`og.app` 或 `ok_config` 为 `None` 时返回 `False`,不抛异常。

- [ ] **Step 1: 写失败测试**

在 `tests/test_farm_task_offline.py` 顶部 import 区加一行(如尚未导入):

```python
from types import SimpleNamespace
```

在文件末尾(`if __name__ == '__main__':` 之前)新增测试类:

```python
class TestBoxesEnabled(unittest.TestCase):

    def test_no_app_returns_false(self):
        """og.app 未设置(默认 None,离线/无 GUI)→ False,不抛异常。"""
        task = make_task()
        self.assertFalse(task._boxes_enabled())

    def test_app_without_use_overlay_key_returns_false(self):
        """ok_config 里没有 use_overlay 键 → 按默认值 False。"""
        from ok import og
        task = make_task()
        with patch.object(og, 'app', SimpleNamespace(ok_config={})):
            self.assertFalse(task._boxes_enabled())

    def test_use_overlay_true_returns_true(self):
        """GUI「启用标记框」开着(use_overlay=True)→ True。"""
        from ok import og
        task = make_task()
        with patch.object(og, 'app', SimpleNamespace(ok_config={'use_overlay': True})):
            self.assertTrue(task._boxes_enabled())

    def test_use_overlay_false_returns_false(self):
        from ok import og
        task = make_task()
        with patch.object(og, 'app', SimpleNamespace(ok_config={'use_overlay': False})):
            self.assertFalse(task._boxes_enabled())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py::TestBoxesEnabled -v`
Expected: 4 个 FAIL,报 `AttributeError: 'MapleFarmTask' object has no attribute '_boxes_enabled'`

- [ ] **Step 3: 实现 `_boxes_enabled()`**

在 `src/task/MapleFarmTask.py` 里,`_resolve_facing` 方法前加:

```python
    def _boxes_enabled(self):
        """GUI Start 页「启用标记框」(Enable Boxes)全局开关的读法,
        与 ok/feature/FeatureSet.py::_draw_boxes_enabled 同一套(og.app.ok_config['use_overlay'])。
        无 GUI/未初始化(离线测试、og.app 尚为 None)时安全降级为 False,不抛异常。"""
        from ok import og
        app = getattr(og, 'app', None)
        ok_config = getattr(app, 'ok_config', None)
        if ok_config is None:
            return False
        return bool(ok_config.get('use_overlay', False))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py::TestBoxesEnabled -v`
Expected: 4 PASS

- [ ] **Step 5: 跑全量回归确认没弄坏别的**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py -v`
Expected: 之前的用例全部照旧 PASS(本步骤只加了新方法,没改任何既有代码路径)

- [ ] **Step 6: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: MapleFarmTask 复用 GUI「启用标记框」开关读法"
```

---

### Task 2: 画/清调试 overlay,接入 `_detect_and_act`

**Files:**
- Modify: `src/task/MapleFarmTask.py`(顶部 import、模块级颜色常量、`DEFAULT_CONFIG`、`config_description`、`_reset_state`、新方法 `_draw_debug`/`_clear_debug`、`_detect_and_act` 插入调用)
- Test: `tests/test_farm_task_offline.py`(新增 `TestDebugOverlay` 测试类)

**Interfaces:**
- Consumes: `self._boxes_enabled()`(Task 1)
- Produces:
  - `MapleFarmTask._draw_debug(self, cfg, body, zone, mobs, mob_present)` —— 画玩家框(绿)/攻击区框(蓝/红)/怪物框(黄)+脚底点(青),调用一次 `self.get_overlay_view().draw('maple_farm_debug', paint_fn)`,并置 `self._debug_drawn = True`。`get_overlay_view()` 返回 `None` 时直接返回,不抛异常。
  - `MapleFarmTask._clear_debug(self)` —— `self._debug_drawn` 为 `False` 时直接返回(不做任何调用);为 `True` 时调用 `self.get_overlay_view().clear_draw('maple_farm_debug')`(`get_overlay_view()` 抛异常或返回 `None` 都容错,记一条 `log_error` 不冒泡),并置 `self._debug_drawn = False`。
  - `self._debug_drawn: bool`(实例状态,`_reset_state()` 里初始化为 `False`)—— Task 3 会读它决定要不要在模式切换/disable 时清

**Task 1 里定义的 `_boxes_enabled` 供本任务调用;Task 3 会调用本任务产出的 `_clear_debug`,签名不变。**

- [ ] **Step 1: 写失败测试**

在 `tests/test_farm_task_offline.py` 新增(放 `TestBoxesEnabled` 之前或之后均可,同一文件内):

```python
class TestDebugOverlay(unittest.TestCase):

    def test_boxes_enabled_draws_with_current_state(self):
        """检测模式一拍跑完(_detect_and_act 被触发)且开关开 → 调一次 _draw_debug,
        参数是这一拍算出的 body/zone/mob_present,不是重新检测的。"""
        task = make_task(**{'角色名': ''})  # 角色名空 → anchor 走 fallback,body=画面中心
        task._boxes_enabled = MagicMock(return_value=True)
        with patch.object(MapleFarmTask, '_draw_debug') as draw, \
             patch.object(MapleFarmTask, '_clear_debug') as clear:
            run_with_frame(task, hp=0.9, mp=0.9)
            draw.assert_called_once()
            clear.assert_not_called()
            _, kwargs = draw.call_args
            self.assertEqual(kwargs['mob_present'], False)  # find_mobs 默认 mock 返回 []
            self.assertEqual(kwargs['mobs'], [])

    def test_boxes_disabled_clears_not_draws(self):
        """开关关 → 不画,且因为之前没画过(_debug_drawn 初始 False)也不必调用清除。"""
        task = make_task(**{'角色名': ''})
        task._boxes_enabled = MagicMock(return_value=False)
        with patch.object(MapleFarmTask, '_draw_debug') as draw, \
             patch.object(MapleFarmTask, '_clear_debug') as clear:
            run_with_frame(task, hp=0.9, mp=0.9)
            draw.assert_not_called()
            clear.assert_called_once()

    def test_clear_debug_noop_when_never_drawn(self):
        """_clear_debug 本身:没画过时不碰 overlay(不调用 get_overlay_view)。"""
        task = make_task()
        task.get_overlay_view = MagicMock()
        task._clear_debug()
        task.get_overlay_view.assert_not_called()

    def test_clear_debug_calls_overlay_when_drawn(self):
        """_clear_debug 本身:画过之后清 → 调 clear_draw('maple_farm_debug') 并复位标记。"""
        task = make_task()
        overlay = MagicMock()
        task.get_overlay_view = MagicMock(return_value=overlay)
        task._debug_drawn = True
        task._clear_debug()
        overlay.clear_draw.assert_called_once_with('maple_farm_debug')
        self.assertFalse(task._debug_drawn)

    def test_draw_debug_calls_overlay_draw(self):
        """_draw_debug 本身:调用 overlay.draw,key 固定 'maple_farm_debug',并置标记。"""
        task = make_task()
        overlay = MagicMock()
        task.get_overlay_view = MagicMock(return_value=overlay)
        task._draw_debug(task.config, body=(1280, 700), zone=(1000, 600, 1500, 800),
                         mobs=[], mob_present=False)
        overlay.draw.assert_called_once()
        args, _ = overlay.draw.call_args
        self.assertEqual(args[0], 'maple_farm_debug')
        self.assertTrue(callable(args[1]))
        self.assertTrue(task._debug_drawn)

    def test_draw_debug_noop_when_no_overlay(self):
        """无 GUI(get_overlay_view 返回 None)→ 不抛异常,不置标记。"""
        task = make_task()
        task.get_overlay_view = MagicMock(return_value=None)
        task._draw_debug(task.config, body=(1280, 700), zone=(1000, 600, 1500, 800),
                         mobs=[], mob_present=False)
        self.assertFalse(task._debug_drawn)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py::TestDebugOverlay -v`
Expected: 6 个 FAIL(`_draw_debug`/`_clear_debug` 不存在,或 `_detect_and_act` 还没调用它们)

- [ ] **Step 3: 实现**

在 `src/task/MapleFarmTask.py` 顶部 import 区(`from qfluentwidgets import FluentIcon` 之后)加:

```python
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen
```

在 `TURN_TAP_SECONDS` 常量之后加调试可视化专用常量:

```python
DEBUG_OVERLAY_KEY = 'maple_farm_debug'
PLAYER_COLOR = QColor(0, 255, 0)
ZONE_IDLE_COLOR = QColor(0, 128, 255)
ZONE_HOT_COLOR = QColor(255, 0, 0)
MOB_COLOR = QColor(255, 255, 0)
MOB_FOOT_COLOR = QColor(0, 255, 255)
```

`DEFAULT_CONFIG` 里 `'寻怪外推速度(像素/秒)': 250,` 之后加(注意:当前文件在这行之后紧接着是模板匹配相关的两个键,见"现状"一节的提醒,按内容定位插入点,不要假设行号):

```python
    '玩家宽(像素)': 60,
    '玩家高(像素)': 120,
```

`config_description.update({...})` 字典里补两行说明(位置任意,建议跟 `'寻怪外推速度(像素/秒)'` 那条后面):

```python
            '玩家宽(像素)': '仅用于调试可视化画框(勾选 GUI「启用标记框」时显示),不影响攻击判定',
            '玩家高(像素)': '同「玩家宽(像素)」,仅调试画框用',
```

`_reset_state()` 末尾(`self._last_busy = 0.0` 那行之后)加:

```python
        self._debug_drawn = False      # 调试 overlay 当前是否已画(True 时开关关掉/模式切换才需要真的调 clear_draw)
```

新增两个方法,放在 `_resolve_facing` 之前(紧挨 Task 1 新加的 `_boxes_enabled` 之后):

```python
    def _clear_debug(self):
        """清掉已画的调试 overlay(没画过则什么都不做)。get_overlay_view 失败/返回 None
        都容错——清理动作不能把主循环搞崩。"""
        if not self._debug_drawn:
            return
        try:
            overlay = self.get_overlay_view()
            if overlay is not None:
                overlay.clear_draw(DEBUG_OVERLAY_KEY)
        except Exception as e:
            self.log_error(f'调试 overlay 清除失败: {e!r}')
        self._debug_drawn = False

    def _draw_debug(self, cfg, body, zone, mobs, mob_present):
        """画玩家框(绿)/攻击区框(蓝=无怪,红=有怪)/怪物框(黄)+脚底点(青)。
        画法照抄 WarriorDebugTask._draw_debug 的 get_overlay_view().draw + frame_ratio 换算,
        用独立 key(DEBUG_OVERLAY_KEY),与 WarriorDebugTask 的 overlay 互不影响。"""
        overlay = self.get_overlay_view()
        if overlay is None:
            return
        pw, ph = cfg['玩家宽(像素)'], cfg['玩家高(像素)']
        zx0, zy0, zx1, zy1 = zone
        zone_color = ZONE_HOT_COLOR if mob_present else ZONE_IDLE_COLOR

        def paint(painter, widget):
            ratio = widget.frame_ratio()

            def rect(x, y, w, h):
                return QRectF(x * ratio, y * ratio, w * ratio, h * ratio)

            painter.setPen(QPen(PLAYER_COLOR, 2))
            painter.drawRect(rect(body[0] - pw / 2, body[1] - ph / 2, pw, ph))
            painter.drawText(rect(body[0] - pw / 2, body[1] - ph / 2 - 20, 100, 20), '玩家')

            painter.setPen(QPen(zone_color, 3))
            painter.drawRect(rect(zx0, zy0, zx1 - zx0, zy1 - zy0))
            painter.drawText(rect(zx0, zy0 - 20, 100, 20), '攻击区')

            for mob in mobs:
                painter.setPen(QPen(MOB_COLOR, 2))
                painter.drawRect(rect(mob.x, mob.y, mob.width, mob.height))
                painter.drawText(rect(mob.x, mob.y - 20, 100, 20), '怪物')
                fx, fy = farm_logic.mob_feet(mob)
                painter.setPen(QPen(MOB_FOOT_COLOR, 4))
                painter.drawPoint(rect(fx, fy, 1, 1))

        overlay.draw(DEBUG_OVERLAY_KEY, paint)
        self._debug_drawn = True
```

在 `_detect_and_act()` 里,`self._last_mob_present = mob_present` 这行之后、`if mob_present:` 之前插入:

```python
        if self._boxes_enabled():
            self._draw_debug(cfg, body=body, zone=zone, mobs=mobs, mob_present=mob_present)
        else:
            self._clear_debug()
```

调用故意全用关键字参数(仅 `cfg` 除外)——`TestDebugOverlay.test_boxes_enabled_draws_with_current_state` 靠 `draw.call_args` 的 `kwargs['mob_present']`/`kwargs['mobs']` 断言,位置参数会让这些 kwargs 变空字典、断言必挂,照抄 `WarriorDebugTask._draw_debug` 调用点(`facing=`/`in_zone=`/`mobs=`)的同款写法。

- [ ] **Step 4: 跑测试确认通过**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py::TestDebugOverlay -v`
Expected: 6 PASS

- [ ] **Step 5: 跑全量回归**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py -v`
Expected: 全部 PASS(默认 `_boxes_enabled()` 为 False,新插入的 `else: self._clear_debug()` 分支在 `_debug_drawn` 恒为 `False` 时是纯 no-op,不影响任何既有断言)

- [ ] **Step 6: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: MapleFarmTask 检测模式下按「启用标记框」画攻击区/角色/怪物调试框"
```

---

### Task 3: 模式切换 & 任务停止时清理残影

**Files:**
- Modify: `src/task/MapleFarmTask.py`(`run()` 第 4 步攻击分支、`disable()`、`on_destroy()`)
- Test: `tests/test_farm_task_offline.py`(新增 3 个测试,加进 `TestDebugOverlay` 类)

**Interfaces:**
- Consumes: `self._clear_debug()`(Task 2)、`self._debug_drawn`(Task 2)

- [ ] **Step 1: 写失败测试**

在 `TestDebugOverlay` 类里追加:

```python
    def test_switch_to_fixed_rate_clears_previous_overlay(self):
        """之前检测模式画过 → 切到定频模式 → run() 里清一次。"""
        task = make_task(**{'攻击模式': '定频'})
        task._debug_drawn = True
        with patch.object(MapleFarmTask, '_clear_debug') as clear:
            def fake_clear():
                task._debug_drawn = False
            clear.side_effect = fake_clear
            run_with_frame(task, hp=0.9, mp=0.9)
            clear.assert_called_once()

    def test_fixed_rate_mode_no_clear_when_never_drawn(self):
        """定频模式、从没画过 → 不必调用清除(_debug_drawn 恒 False 时是 no-op,
        这里直接断言真实 _clear_debug 不触发 get_overlay_view)。"""
        task = make_task(**{'攻击模式': '定频'})
        task.get_overlay_view = MagicMock()
        run_with_frame(task, hp=0.9, mp=0.9)
        task.get_overlay_view.assert_not_called()

    def test_disable_clears_debug_overlay(self):
        """MapleFarmTask.disable() 真正执行(不是 mock 掉),但 super().disable()
        (MRO 上下一个是 TriggerTask.disable)打桩掉——make_task 是裸 __new__ 出来的,
        没有框架其余状态,真跑 TriggerTask.disable 会因为缺属性炸掉,与本测试无关。"""
        from ok.task.task import TriggerTask
        task = make_task()
        overlay = MagicMock()
        task.get_overlay_view = MagicMock(return_value=overlay)
        task._debug_drawn = True
        with patch.object(TriggerTask, 'disable'):
            MapleFarmTask.disable(task)
        overlay.clear_draw.assert_called_once_with('maple_farm_debug')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py::TestDebugOverlay -v`
Expected: 新增 3 个用例里,`test_switch_to_fixed_rate_clears_previous_overlay` 和 `test_disable_clears_debug_overlay` FAIL(`_clear_debug` 还没接进 run()/disable());`test_fixed_rate_mode_no_clear_when_never_drawn` 可能已经 PASS(定频分支目前确实不碰 overlay)——这一条是回归保护,不是本任务新增行为,PASS 也保留在套件里

- [ ] **Step 3: 实现**

`run()` 第 4 步攻击分支,把:

```python
        elif farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
            self.send_key(keys['攻击键'])
            self._last_attack = now
```

改成:

```python
        else:
            self._clear_debug()  # 定频模式没有锚点/攻击区,之前检测模式画过的框清掉
            if farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
                self.send_key(keys['攻击键'])
                self._last_attack = now
```

(等价于把原来的 `elif ...:` 拆成 `else:` 包一个 `if ...:`,逻辑分支不变,只是多了一行 `self._clear_debug()`)

`disable()` 改成:

```python
    def disable(self):
        """停任务前松开可能还按着的长按键,防止角色在任务停止后继续走/打。"""
        self._release_held_keys()
        self._clear_debug()
        super().disable()
```

`on_destroy()` 改成:

```python
    def on_destroy(self):
        """应用退出/executor 销毁前松键(interaction 在任务之后才销毁,此时松键仍可用)。"""
        self._release_held_keys()
        self._clear_debug()
        super().on_destroy()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py::TestDebugOverlay -v`
Expected: 全部 PASS

- [ ] **Step 5: 跑全量回归**

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/test_farm_task_offline.py -v`
Expected: 全部 PASS,包括既有的 `disable()`/定频模式相关用例(改动只是在已有分支里插入一行容错的 `_clear_debug()` 调用)

再跑一次全仓库测试确认没有跨文件回归:

Run: `H:\ok-mxd\data\apps\ok-ww\python\python.exe -m pytest tests/ -v`
Expected: 全部 PASS(含 `test_warrior_debug_offline.py`——本计划未改 `WarriorDebugTask.py`,理应不受影响)

- [ ] **Step 6: Commit**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: 定频模式/任务停止时清理调试 overlay,避免残影"
```

---

## 完成后手动验证(可选,非自动化测试覆盖范围)

1. 提权启动 GUI(`elevated_launch.cmd`,本仓库挂机必须提权,见 `[[ok-mxd-project]]` 记忆)
2. 勾选 Start 页「启用标记框」
3. 打开「自动打怪」任务,攻击模式=检测,填角色名,启用任务
4. 期望看到:绿色玩家框、蓝/红攻击区框(怪进区变红)、黄色怪物框+青色脚底点,随攻击间隔节奏刷新
5. 取消勾选「启用标记框」→ 框应消失
6. 攻击模式切到「定频」→ 框应消失且不再出现
7. 停用任务 → 框保持消失(无残影)
