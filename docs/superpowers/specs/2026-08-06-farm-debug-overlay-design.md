# 打怪任务调试可视化 —— 复用「启用标记框」显示攻击区/角色/怪物框

日期：2026-08-06
状态：设计已确认，待实现
上游：`2026-08-05-ok-mxd-design.md`（MVP 设计）；参考 `WarriorDebugTask.py` 已有的同类可视化实现，及 `_reference/MapleStoryAutoLevelUp` 的 debug 画面风格（画框 + 文字标签）

## 1. 问题

`WarriorDebugTask`（独立只读调试任务）已经能画玩家框/攻击区框（怪进区变色）/怪物框+脚底点，但它用的是战士式方向性攻击区，且是独立任务，不随实际挂机任务一起跑。

真正在跑的挂机任务 `MapleFarmTask`（魔法师用，`攻击模式=检测`）没有任何可视化——攻击区/角色定位/怪物识别对不对，用户只能看日志猜。用户已确认：

- 要看的是 `MapleFarmTask` 的实时画面标注（**打开调试才看**，平时不需要）
- 复用 GUI Start 页已有的「启用标记框」（Enable Boxes，`use_overlay` 配置）开关，**不新增任务级开关**

## 2. 现状盘点

- GUI 「启用标记框」开关：`StartTab.py` 勾选后写 `og.app.ok_config['use_overlay']` 并调用 `overlay_view.set_boxes_enabled(checked)`。该状态的标准读法（`ok/feature/FeatureSet.py::_draw_boxes_enabled`）：
  ```python
  from ok import og
  app = getattr(og, 'app', None)
  ok_config = getattr(app, 'ok_config', None)
  ok_config is not None and ok_config.get('use_overlay', False)
  ```
- 该开关只控制框架内建的 `communicate.draw_box`（`find_feature` 之类用），**不影响**任务通过 `get_overlay_view().draw(key, paint_fn)` 挂的自定义画笔——`OverlayWindow.refresh_visibility` 里 `custom_painters` 非空即显示，与 `_boxes_enabled` 无关。所以本次要主动在任务里查这个配置项做门控，不能假设开关自动生效。
- `MapleFarmTask._detect_and_act`（`MapleFarmTask.py:309-352`）已经算出：`body`（身体中心）、`zone`（`farm_logic.attack_zone` 返回的 `(x0,y0,x1,y1)`）、`mobs`（YOLO 检测框列表）、`mob_present`（区内是否有怪）——本次直接复用，不重复检测。
- `_detect_and_act` 只在检测模式下、按攻击间隔/寻怪刷新间隔节流调用；定频模式（`攻击模式=定频`）不调用它，没有锚点/攻击区概念。

## 3. 设计

### 3.1 门控

新增私有方法 `_boxes_enabled()`：读 `og.app.ok_config.get('use_overlay', False)`（同 `_draw_boxes_enabled` 的读法）。每次 `_detect_and_act` 结束时调用：

- 开：画（见 3.2），并记 `self._debug_drawn = True`
- 关：若 `self._debug_drawn` 为真才调 `overlay.clear_draw('maple_farm_debug')` 并置回 `False`（避免每拍都清一次没画过的东西）

`攻击模式=定频` 时 `_detect_and_act` 不会被调用，若之前处于检测模式画过、之后切到定频，`run()` 顶部（攻击分支之前）补一次判断：非检测模式且 `self._debug_drawn` 为真 → 清一次。

### 3.2 画的内容（对齐 `WarriorDebugTask` 配色 + 参考项目的文字标签）

在 `_detect_and_act` 末尾、已算出 `body/zone/mobs/mob_present` 之后调用 `self._draw_debug(cfg, body, zone, mobs, mob_present)`：

| 元素 | 样式 | 数据来源 |
|---|---|---|
| 玩家框 | 绿色矩形 + 文字「玩家」 | `body` ± 新配置 `玩家宽(像素)`/`玩家高(像素)`（默认 60/120，纯显示用，不参与任何判定逻辑） |
| 攻击区 | 蓝框（`mob_present=False`）/ 红框（`True`）+ 文字「攻击区」 | `zone`（`_detect_and_act` 已算好的 `(x0,y0,x1,y1)`，直接转 `QRectF`） |
| 怪物框 | 黄框 + 青色脚底点，文字「怪物」 | `mobs`（已跑过的 YOLO 结果，不重复调用） |

坐标转换沿用 `WarriorDebugTask._draw_debug` 的 `widget.frame_ratio()` 换算方式。

### 3.3 新增配置

`DEFAULT_CONFIG` 加两项（仅用于画框尺寸，不影响攻击逻辑）：

| 键 | 默认 | 说明 |
|---|---|---|
| `玩家宽(像素)` | 60 | 调试可视化用的玩家框宽度（勾选 GUI「启用标记框」时显示） |
| `玩家高(像素)` | 120 | 同上，高度 |

`config_description` 补充说明，注明"仅用于调试可视化开框"。

### 3.4 清理时机

- 开关关闭（`_boxes_enabled()` 变 False）：见 3.1
- `攻击模式` 从检测切到定频：见 3.1
- `disable()` / `on_destroy()`：在现有释放长按键的位置顺带 `try: self.get_overlay_view().clear_draw('maple_farm_debug') except: 忽略`（同 `WarriorDebugTask.on_disable` 的容错写法），避免任务停止后 overlay 残影

### 3.5 与 WarriorDebugTask 的关系

互不影响：`WarriorDebugTask` 继续用自己的 `调试开关` 配置项和 `warrior_debug` 画笔 key；本次新增用独立 key `maple_farm_debug`，两者可以同时挂（不会互相清掉对方的 overlay）。不改 `WarriorDebugTask` 代码。

## 4. 验证计划

`tests/test_farm_task_offline.py` 新增（沿用现有 offline 测试对 `get_overlay_view()`/`send_key` 之类的打桩方式）：

- `use_overlay=False`：`_detect_and_act` 跑完后不调用 `overlay.draw`
- `use_overlay=True` + 检测模式：`_detect_and_act` 跑完后 `overlay.draw('maple_farm_debug', ...)` 被调用一次
- `use_overlay=True` → 中途切 `False`：下一次 `_detect_and_act` 触发 `overlay.clear_draw('maple_farm_debug')`
- `攻击模式` 从检测切到定频、且此前已画过：`run()` 触发一次 `clear_draw`

不做像素级断言（画笔是 lambda closure，离线测试跑不了真实 Qt paint），只断言「调用与否」「调用参数的 key」。

## 5. 明确不做

- 不新增任务级调试开关（用户已确认复用 GUI 全局「启用标记框」）
- 不改 `WarriorDebugTask`（独立保留，供参考/单独校准战士方向性攻击区用）
- 不做像素级 painter 内容单测（Qt paint 回调离线测试验证不了，且非本次问题）
- 不在定频模式下画任何东西（该模式无锚点/攻击区概念）
