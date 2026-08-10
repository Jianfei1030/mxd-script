# AGENTS.md — mxd-script 项目实战经验与踩坑记录

> **本文件汇总自 2026-08-06 ~ 08-07 实战中积累的所有坑与正确做法。**  
> **每个 agent 会话启动前必读，避免重复踩坑。**  
> 路径：`C:\projects\mxd-script\AGENTS.md`（项目根目录）

---

## 1. 环境与运行

### 1.1 Python 版本
- 本项目 **要求 Python 3.12**（`pyside6==6.9.1` 限制 Requires-Python <3.13）
- 系统 Python 3.14 **不能用**，会装不上 pyside6
- 本机已装独立 **Python 3.12.10**：`C:\Users\40759\AppData\Local\Programs\Python\Python312\python.exe`
- 项目 venv：`C:\projects\mxd-script\.venv-warrior`（3.12 重建）
- `.venv-warrior/` 已加入 `.gitignore`

### 1.2 GPU / PyTorch
- `pip install ultralytics` 默认装 **torch 2.13.0+cpu**（CUDA 不可用）
- **必须手动换装**：`pip install --force-reinstall --index-url https://download.pytorch.org/whl/cu126 torch torchvision`
- 本机 NVIDIA RTX 4090（driver 610.88），换装后 `torch.cuda.is_available()=True`

### 1.3 启动 GUI（main_debug.py）
- **前台直跑会阻塞**，用 `Start-Process` 独立进程：
  ```
  $p = Start-Process -FilePath ".\.venv-warrior\Scripts\python.exe" -ArgumentList "main_debug.py" -WorkingDirectory "C:\projects\mxd-script" -PassThru -RedirectStandardError "logs\main_debug_err.log" -RedirectStandardOutput "logs\main_debug_out.log"
  ```
- ⛔ **铁律：启动 GUI 必须用管理员身份**——pydirect 的 `is_admin()` 检查是硬门槛，非管理员 GUI 检测只读可用但**按键发送被禁用**。管理员启动命令：
  ```
  Start-Process -FilePath ".\.venv-warrior\Scripts\python.exe" -ArgumentList "main_debug.py" -WorkingDirectory "C:\projects\mxd-script" -Verb RunAs
  ```
- `pythonw.exe` 启动 GUI 会**静默崩溃**（进程秒退无输出），用 `python.exe` + 重定向捕获错误
- GUI 可能产生**双进程**（stub + 真实 GUI），判断真实 GUI 看 WorkingSet 大小（>100MB 才是真身）
- stderr `RefreshAdb pydirect:You must be an admin to use Win32Interaction` **无害**（只影响按键任务，检测是只读的）
- `configs/WarriorDebugTask.json` 等配置文件是合法 UTF-8——PowerShell `Get-Content` 显示乱码是 **GBK 显示假象**，`json.loads` 正常

### 1.4 WGC 抓帧（capture_frame.py / build_capture）
- **前台直跑可能无限挂起**（WGC 初始化等游戏窗口前台）
- **必须后台化**：
  1. 抓帧逻辑写成独立 `.py` 脚本（不用 `-c` 内联，避免转义问题）
  2. `cmd /c start /B` 后台启动
  3. 独立短命令（5-15s）轮询输出文件
- GUI 运行时持有 WGC 会话，**抓帧前先停 GUI**
- `build_capture()` 用 `_FakeDeviceManager` → 日志会打 `AttributeError`，**不影响采集**

---

## 2. 数据采集与标注

### 2.0 数据集结构（重要！）

```
dataset/
├── mobs.yaml                 ← YOLO 配置文件（path: ., train: images/train, val: images/val）
├── images/
│   ├── train/                ← 训练集图片（60张）
│   └── val/                  ← 验证集图片（10张）
├── labels/
│   ├── train/                ← 训练集标注（YOLO txt: 0 cx cy w h）
│   └── val/                  ← 验证集标注
├── raw/
│   ├── patrol_ground/        ← 原始采集帧 + 标注 txt（单地图切分法的源）
│   └── patrol_val/           ← 验证集原始帧
├── preview/
│   └── boxed/                ← 画框预览图（QC 用）
└── runs/                     ← 训练输出（yolo train 自动创建）
```

**关键点**：
- `mobs.yaml` 的 `path: .` 要求**从 dataset 目录执行** yolo train
- `raw/` 目录存放原始帧，`images/` 和 `labels/` 是训练用的正式数据
- 标注文件与图片同名不同后缀（`frame_0001.png` → `frame_0001.txt`）
- 单地图切分法：raw 目录取全部帧为 train，后 N 帧复制重命名为 val

**当前数据量**：70 张标注（60 train + 10 val），对于 yolov8m 偏少，建议补采到 200+

### 2.1 采集命令
```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\record_frames.py <地图名> [间隔秒] [数量]
```
- 产出 `dataset/raw/<地图名>/frame_{existing+i:04d}.png`（帧号接续已有文件）
- 采集时**必须模拟巡逻视角走动**（不站桩、不攻击），帧间隔 1~2s
- 必须有**纯背景负样本帧**（当前巡逻地图 60 帧仅 1 帧负样本，偏少）

### 2.2 预标注（prelabel_from_onnx.py）
- 用**现有旧 mob.onnx** + `OpenVinoYolo8Detect`（不用 ultralytics，会超时）
- 写 YOLO txt：`0 cx cy w h`（归一化），无框写空 txt（负样本），已有非空 txt 跳过
- ⚠️ **ultralytics 加载 onnx 卡死 120s+**，自动预标必须走 OpenVINO

### 2.3 标注工具（label_boxes.py）
```powershell
.\.venv-warrior\Scripts\python.exe scripts\label_boxes.py dataset\raw\<地图名>
```
- **已修复 `load_image` 不重绘 bug**：原读入 txt 后不调 `redraw()`，打开任意图都不显示红框
- 键盘 `r`/`d` 删最后一个框**依赖窗口焦点**（需先单击 GUI 窗口）
- **已加右键点击删除**（`RBUTTONDOWN` 按归一化坐标命中框中心删除，解决"只能删最后"问题）
- 鼠标左键拖拽=添加框，`n`/空格=保存并下一张（0 框存空 txt=负样本），`p`=上一张，`q`=退出

### 2.4 QC 画框查看
- **看 `dataset/preview/boxed/`**（非 raw 目录）
- raw 目录有 `draw_yolo_boxes.py` 单张测试残留（`frame_0000_boxed.png`），需清理
- 红像素检测验证：preview/boxed 所有图 61/61 有红框

---

## 3. 训练与部署

### 3.1 切分（final_split.py）
- `--train` 地图**取全部帧**（copy_map_all），`--frames` **仅作用于 val 地图**
- 单地图切分法：后 N 帧复制成新地图目录（重命名 frame_0000 起）作 val

### 3.2 训练命令（必须从 dataset 目录执行）

**yolov8n（轻量级，3.2M 参数）**：
```powershell
..\.venv-warrior\Scripts\yolo.exe train data=mobs.yaml model=..\yolov8n.pt imgsz=1280 epochs=200 batch=4 device=0 project=runs name=<名>
```
- 从 **dataset 目录**执行（`mobs.yaml` 的 `path: .` 相对 cwd 解析）
- RTX 5070 Ti 训练 200 epochs ~30 分钟（10s/epoch）

**yolov8m（更强，25.9M 参数，推荐用于正式训练）**：
```powershell
..\.venv-warrior\Scripts\yolo.exe train data=mobs.yaml model=yolov8m.pt imgsz=1280 epochs=200 batch=4 device=0 project=runs name=<名>
```
- `yolov8m.pt` 用裸名，ultralytics 自动联网下载；离线用 `model=..\yolov8n.pt` 退级
- **注意**：mob.onnx（12MB）**已入库**（spec §M3），训练新模型后记得提交；备份 `.onnx.bak_*` 在 .gitignore 不入库

**共同要求**：
- `python -m ultralytics` **报 No module named ultralytics.__main__**，必须用 `yolo.exe`
- `mobs.yaml` 的 `path: .` 要求**从 dataset 目录执行**

### 3.3 导出 ONNX
```powershell
..\.venv-warrior\Scripts\yolo.exe export model=runs\detect\runs\<名>\weights\best.pt format=onnx imgsz=1280
```
- 从 **dataset 目录**执行；产物路径带 `detect/runs/` 层（ultralytics 8.4.x 自动嵌套）

### 3.4 部署
- 实机加载路径：`assets/mob_model/mob.onnx`（`src/globals.py:21`）
- 部署前**备份旧模型**：`Copy-Item "assets\mob_model\mob.onnx" "assets\mob_model\mob.onnx.bak_<日期>"`
- 训练产物在 `dataset/runs/detect/runs/<名>/weights/`

---

## 4. WarriorDebugTask（Phase 1 调试可视化）

### 4.1 GUI 操作流程（精确，勿凭印象！）
1. 启动 `main_debug.py` → 等 GUI 弹出
2. 切到**「截图方式」tab** → 打开「**调试悬浮窗**」卡片 → 打开「**启用标记框**」（use_overlay）
   - ⚠️ **必须先开「启用标记框」再启动**——否则 overlay 窗口不创建，即使任务跑了也无框
3. 切到**「实时触发」tab** → 找到**「战士调试」任务卡片**→ 下拉展开区：
   - 填「**角色名**」（必须与游戏内名字牌一字不差）
   - 打开「**调试开关**」（debug switch，run() 首行 gate）
4. 点 **Start 按钮**（在 StartCard 右侧，与截图/刷新按钮并排）
   - 按钮变「Pause」+ 状态栏显示 "Running: 1 Trigger Tasks" = 成功
5. **退出时**：先点 Stop 或关闭游戏窗口，再关 GUI（避免 overlay 残影）

### 4.2 关键 UI 名称（zh_CN 翻译）
| 代码英文 | 界面显示 |
|---|---|
| `Debug Overlay` 卡片 | 「调试悬浮窗」 |
| `Enable Boxes` 开关 | 「启用标记框」 |
| `Disable Boxes` 开关 | 「禁用标记框」 |
| `Start` 按钮 | 「Start」或快捷键后缀 |

### 4.3 双开关机制
- **任务 toggle**（卡片右侧开关）= `_enabled`，标记可调度
- **「调试开关」**（下拉展开区）= run() 首行 gate
- **「启用标记框」**（StartTab）= `use_overlay`，控制 overlay 窗口创建
- **Start 按钮** = 启动 executor 执行循环（`og.executor.start()`）
- **四个都要开，run() 才执行、overlay 才显示**

### 4.4 标记含义
| 颜色 | 含义 |
|---|---|
| 🟡 黄框 | 检测到的怪物（新模型） |
| 🟢 绿框 | 玩家角色（名字牌锚定） |
| 🔵 蓝框 | 攻击区（无怪进入） |
| 🔴 红框 | 攻击区（**有怪进入攻击距离**） |
| ⚪ 青点 | 怪物脚底点 |

---

## 5. 绘制 Bug 与修复记录

### 5.1 「只画一个黄框」（drawPoint 崩溃中断循环）
- **根因**：`painter.drawPoint(rect(fx, fy, 1, 1))` 传 `QRectF`，Qt 的 `drawPoint` 只接受 `QPointF`/坐标对
- **症状**：paint 回调里 for 循环画完第一个 mob 的 drawRect 后 drawPoint 崩溃 → 被 `paint_custom` 的 try/except 吞掉 → 剩余 mob 全不画
- **证据**：日志刷屏 `custom overlay painter warrior_debug failed: 'PySide6.QtGui.QPainter.drawPoint' called with wrong argument types`
- **修复**：`painter.drawPoint(QPointF(fx * ratio, fy * ratio))`（需要 `from PySide6.QtCore import QPointF`）

### 5.2 「关闭启用标记框后残留绘制」
- **根因**：`set_boxes_enabled(False)` 只清 `_boxes_enabled`（boxes 通道），custom painter 不受影响
- **修复**：`_draw_debug` 开头检查 `ok_config.get('use_overlay', False)`，False 时 `overlay.clear_draw('warrior_debug')` + return

### 5.3 「日志疯狂刷屏」
- **根因**：调试日志放在 paint 回调里，而 paint 回调**每次 GUI repaint 都执行**（~10ms 一次，鼠标移动也触发）
- **证据**：200ms 内产生 40+ 条 `WarriorDebug mob rect` 日志（实测 01:56:33 时间段）
- **规则**：paint 回调**禁止 logger.info/重活**，调试日志放 run() 等低频调用点或直接移除

### 5.4 「调试开关/角色名没反应」
- 调试开关（`调试开关=False`）默认关，run() 首行 `if not cfg.get('调试开关'): return` 静默退出
- 角色名填在「实时触发」tab 任务卡片下拉展开区（**不是**设置页）

---

## 6. Overlay 机制

### 6.1 overlay 创建条件
- `use_overlay=True` 或 `blur_area` callable 时才预建 overlay 窗口（`ok/__init__.py:354`）
- `use_overlay=False`（默认）→ overlay 窗口不创建 → WarriorDebugTask 的 custom painter 无法绘制
- ⚠️ **懒创建时序坑**：overlay 可由 `get_overlay_view()` 懒创建，但 `communicate.window` 信号只在创建时连接一次——如果创建发生在窗口 geometry 更新事件之后，overlay 不会收到 `_source_visible=True`，窗口永远不会 show()。**必须先开「启用标记框」再启动 executor**

### 6.2 overlay 两通道
- **boxes 通道**：`communicate.draw_box` → `on_draw_box` → 需 `_boxes_enabled=True`
- **custom painter 通道**：`overlay.draw(key, callback)` → `custom_draw_requested` QueuedConnection → `custom_painters[key]` → `paint_custom` 遍历执行，**不依赖 `_boxes_enabled`**，但需 overlay 窗口已创建

### 6.3 overlay 窗口几何
- `update_overlay(visible, x, y, width, height, scaling)` 设置窗口位置/大小
- `frame_ratio()` = `self.width() / og.device_manager.width`（正常=1.0）
- 窗口标志：`FramelessWindowHint | WindowStaysOnTopHint | Tool | WindowTransparentForInput`

---

## 7. 检测与模型

### 7.1 OpenVinoYolo8Detect
- `weights` / `model_h=1280` / `model_w=1280` / `iou_thres=0.45`
- `detect(image, threshold=0.5, label=-1)` → 返回 `Box` 列表（`.x/.y/.width/.height` 为**像素坐标**）
- 写 YOLO txt 需自行除以图宽高归一化
- **懒加载**：首次 detect 调用才编译模型（日志出现 "OpenVINO model compiled" = 首次执行 detect）

### 7.2 find_mobs 阈值
- `BaseMapleTask.find_mobs(threshold=0.5)` → `yolo_detect(threshold=0.5)`
- 默认 0.5，可根据需要调整（训练验收用 0.25）
- `sort_boxes`（`ok/feature/Box.py:314`）就地 sort 返回 **list**（非生成器），`any()` 不会消费迭代器

### 7.3 绘制刷新节奏
- `调试刷新间隔(秒)` 配置（默认 0.3s）控制 `_last_draw` 节流 → 内容更新频率
- 降低到 0.1~0.03 可消除延迟感（paint 回调本身每帧 GUI repaint 执行，~10ms）
- 检测耗时：1280 推理 ~22ms + 名字牌 OCR ~118ms（首次）→ 后续快通道小窗 <50ms

### 7.4 击退受击检测（朝向信念修复，2026-08-07 实测）
- **实测结论**：冒险岛被怪碰到 → 往**远离怪物**方向击退 + **翻转朝向来面对怪物**（用户实测确认）
- **玩家朝向不是服务端状态**：`MapleCharacter` 无 facing 字段（只有 `MapleMonster` 有），抓包/读内存读不到，像素是唯一可观测面
- **`_facing` 是盲写信念**（MapleFarmTask.py:158），只在转向轻点/寻怪走动/走位后更新 → **击退是唯一破坏源**。挥砍中 body_x 跳变 >80px 的拍占 19%，击退高频
- **修复**：`farm_logic.knockback_detected(hp, prev_hp, ...)` 检测受击（HP 掉 >2% 主信号 + 锚点位移辅助），触发时 `_facing = None` + `_last_turn = 0.0`（重置转向冷却），下一检测拍 `attack_turn_direction(None,...)` 按最近怪定向重建朝向
- **为什么置 None 而非直接猜朝向**：对"击退翻不翻朝向"两种机制同时正确——翻了补 tap 是纠错；没翻，朝怪 tap 50ms 是 no-op（已面朝该侧按方向键零代价）
- **受击检测放 run() 高频路径**（每拍 10Hz，不等 1.5s 检测拍节流），位置在保命之后、喝药之前
- **WarriorDebugTask `_auto_facing` 两拍确认**：连续 2 拍同向位移(>15px)才翻转，单拍位移/OCR 噪声(±5px)不翻——避免调试 overlay 朝向抖动

---

## 8. 标定（calibrate_warrior_zone.py）

### 8.1 标定流程
1. **先停 GUI**（GUI 持有游戏窗口 WGC 会话，抓帧会无限挂起）
2. 抓帧：`scripts/_capture_calib.py` → 后台运行 → `screenshots/calib_frame.png`
3. 运行标定：`.\.venv-warrior\Scripts\python.exe scripts\calibrate_warrior_zone.py screenshots\calib_frame.png --name <角色名>`
4. 交互输入：攻击距离/攻击区高/名字牌偏移/玩家宽高
5. 画框图 → 对照游戏实际挥刀范围 → `y` 写配置 / `n+20` 调整重画

### 8.2 写入路径（已修正）
- **正确**：`configs/WarriorDebugTask.json` 顶层键（与 GUI `Config(name)` 加载一致）
- **错误（旧）**：`configs/config.json` 的 `task_configs['战士调试']`（GUI 读不到）

### 8.3 需标定的参数
| 参数 | 默认值 | 说明 |
|---|---|---|
| `名字牌到身体偏移` | 90 | 名字牌中心 → 角色身体中心的 Y 偏移（像素，上移） |
| `玩家宽` | 60 | 玩家 bbox 宽度 |
| `玩家高` | 120 | 玩家 bbox 高度 |
| `攻击距离` | 120 | 攻击区宽度（武器距离不一，**必须标定**） |
| `攻击区高` | 200 | 攻击区高度 |

---

## 9. 常见错误速查

| 症状 | 原因 | 解决 |
|---|---|---|
| GUI 启动崩（FluentIcon.EYE） | qfluentwidgets 无 EYE 成员 | 改 `FluentIcon.VIEW` |
| "无框"但 OpenVINO compiled | overlay 未创建（`use_overlay=False`） | 打开「启用标记框」 |
| "无框"但 overlay 红边框有 | tasks 没 enable 或 executor 没 start | 先 toggle + Start |
| 只画一个黄框 | `drawPoint(QRectF)` 类型错误，循环中断 | 改 `QPointF(fx*ratio, fy*ratio)` |
| 关标记框后残留 | custom painter 不受 `set_boxes_enabled` 控制 | `_draw_debug` 检查 `use_overlay` |
| `r`/`d` 删框无效 | cv2 窗口没焦点 | 先单击窗口；或用右键删框 |
| WGC 抓帧超时 | 前台直跑 / GUI 占 WGC 会话 | 后台化 + 停 GUI |
| `python -m ultralytics` 报错 | 无 `__main__` | 用 `yolo.exe` |
| 标定结果读不到 | 写了 config.json 而非 WarriorDebugTask.json | 检查写入路径 |
| 绿框/攻击区偏移 | 名字牌锚点偏移/参数不对 | 用 `calibrate_warrior_zone.py` 标定 |
| paint 日志爆炸 | paint 回调每帧执行 | 回调内禁日志 |
| **绿框飘到右侧组队列表** | **组队血量显示 UI 干扰名字牌匹配** | **⛔ 必须关闭组队血量显示（UI 设置里关）** |

---

## 10. 文件清单（关键脚本）

| 文件 | 用途 |
|---|---|
| `scripts/record_frames.py` | 采集帧（需要游戏在前台） |
| `scripts/label_boxes.py` | 人工标注/纠错 GUI |
| `scripts/draw_yolo_boxes.py` | 单帧画框抽查 |
| `scripts/prelabel_from_onnx.py` | 用旧模型批量预标注 |
| `scripts/final_split.py` | 切分 train/val |
| `scripts/calibrate_warrior_zone.py` | 攻击区/玩家框标定 |
| `scripts/_capture_calib.py` | 后台抓帧 helper |
| `scripts/_diag_anchor.py` | 锚点定位诊断 |
| `src/OpenVinoYolo8Detect.py` | YOLO OpenVINO 推理 |
| `src/detect/anchor.py` | 名字牌 OCR 锚点定位 |
| `src/detect/ocr_engine.py` | OCR 引擎（onnxocr 封装） |
| `src/task/WarriorDebugTask.py` | Phase 1 调试可视化任务 |
| `src/task/BaseMapleTask.py` | 任务基类（find_mobs 入口） |
| `src/task/farm_logic.py` | 战士攻击区/怪物脚底点纯函数 |
| `src/globals.py` | 全局配置/模型加载 |
| `ok/feature/Box.py` | Box 类 + sort_boxes（检测结果容器） |
| `assets/mob_model/mob.onnx` | 当前部署的检测模型 |

---

## 11. 测试标准（铁律，2026-08-07 设立）

> 本项目的测试纪律。**每条都是硬性要求**，违反即视为交付不合格。
> 背景：曾出现"改了代码没测就上实机、出问题靠肉眼排"的教训（击退朝向、overlay 等），
> 从此立规：**没有测试证据的特性不算完成**。

### 11.1 禁止 hard code 本地路径（铁律）

- **所有代码（src/ scripts/ tests/）禁止出现绝对路径**（`C:/`、`D:/`、`H:/`、`/Users/`、`AppData` 等）
- 项目根一律由脚本自身推导：`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
- 例外：仅注释/文档中允许出现示例路径；`ok/` 框架第三方代码除外
- 违反示例（已修复）：`scripts/_diag_anchor.py` / `scripts/_capture_calib.py` 曾写死
  `'C:/projects/mxd-script'`，换机器即挂

### 11.2 新特性必须带单元测试（铁律）

- **任何新增/修改的纯逻辑（farm_logic.py 等）必须同步加 unittest**，断言覆盖正常/边界/异常路径
- 测试文件命名 `tests/test_*.py`，离线可跑（不依赖 GUI/游戏/网络）
- 纯逻辑放 `farm_logic.py` 等可单测模块；不许把决策逻辑塞进 run() 无法离线测
- 合入前必须 `python -m unittest discover -s tests` 全绿（允许显式 skip）

### 11.3 新特性必须带 E2E 测试 + 截图证据（铁律）

- **E2E = 启动真实 GUI（main_debug.py）→ 打开对应功能 → 截图留证**
- 截图必须**经过视觉模型验收通过**才生效（本仓库用 vision-capable 模型核对截图内容，
  例如检测框颜色/位置是否符合预期；模型验证工具见 11.5）
- 截图存 `screenshots/e2e/<特性名>/`，文件名带日期；验收结论（通过/失败+原因）写进
  特性说明或 AGENTS.md
- 界面必须能正常打开（无编译错误、无启动崩溃）——这是 E2E 的最低门槛

### 11.4 环境缺失的处理规则

- **依赖存档帧/数据的测试，环境缺失时必须显式 skip**（`skipUnless` / `SkipTest`），
  不允许 assert 报错假失败——否则无截图机器上测试套件永远红
- 合成帧兜底（如黑帧）只用于"行为逻辑"测试；涉及真实像素读数的用例必须 skip
- 已按此修复：`test_bars` / `test_potions` / `test_anchor_offline` / `run_with_frame`(hp 兜底)

### 11.5 E2E 截图验收流程

1. 停掉占用 WGC 的旧 GUI → 启动 `main_debug.py`（后台 + 日志重定向，见 §1.3）
2. 等 GUI 弹出 → 按特性操作路径打开功能 → 截图
3. 用 vision-capable 模型（`actor models --vision` 查看可用项）检查截图：
   - 界面元素是否出现/位置正确
   - 检测框颜色/数量/位置是否符合预期（黄=怪、绿=玩家、蓝/红=攻击区）
4. 验收通过 → 截图归档 + 结论写入文档；失败 → 修复后重跑，不许带病合入

### 11.6 运行单测的命令

```powershell
# 全量单测(排除重型 live/yolo 测试;它们只做编译检查)
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -m unittest tests.test_farm_logic tests.test_warrior_debug_offline tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_calibrate_offline tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine
# 编译检查(全源码)
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```

### 11.7 当前基线（2026-08-07）

- 单测：10 个测试模块全绿（146+ 用例），7 个显式 skip（存档帧缺失 ×5、OCR 限制 ×2）
- 编译：src/ scripts/ tests/ ok/ 全源码 + 入口脚本 py_compile 通过
- E2E（2026-08-07 本机验收）：
  - **通过**：`main_debug.py` 启动 GUI 成功，主窗口「OK-MXD v0.1.0 开发工具」完整渲染
    （标题栏/左侧 6 项导航/截图方式卡片/交互方式/调试悬浮窗开关），无崩溃无错误弹窗
  - **通过**：两个 trigger task（MapleFarmTask / WarriorDebugTask）在 GUI 内成功注册加载，
    含本次新增受击检测代码——证明新代码在真实 GUI 运行路径无导入/编译错误
  - **通过**：截图经视觉模型验收 PASS（`screenshots/e2e/gui_launch/gui_main_20260807.png`，
    1200x800 与日志 geometry 一致）
  - 已知无害 stderr：`pydirect:You must be an admin`（非管理员按键限制，检测只读不受影响）、
    `install translations error for zh_CN`（qfluentwidgets 翻译缺失，界面英文可用）
  - 截图工具：`scripts/_e2e_capture.py <pid> <out_path>`（按 PID 截窗口，E2E 取证用）

#### 群攻功能验收（2026-08-10，`feat/aoe-attack`）

spec `2026-08-09-aoe-attack-design.md` §5.3 定了 A/B/C/D 四条门槛。**实际只有 A 跑完并通过，D/B/C 由用户判定豁免、直接验收。** 如实记在这里，将来回看这个功能的行为时不要误以为它过了全部四条。

- **A（确实生效且计数自洽）— 通过，有证据**
  - 数据源 `logs/ok-script.log`，2026-08-10 19:44–21:13，约 31 分钟有效挂机，2470 个检测拍
  - 「群攻」行 **71** 条（要求 > 0）
  - 每行 `区内 ≥ 阈值` **违例 0**：56×`2≥2`、11×`3≥2`、2×`3≥3`、2×`4≥2`
- **D（E2E 截图视觉验收）— 未做**（spec 原文写的是「合入门槛」）。`screenshots/e2e/aoe_attack/` 不存在，overlay 的群攻态（接敌区框 1→3 加粗、标签 `接敌区(群攻)`）**从未在真实 GUI 上看过**，只有离线单测覆盖传参。
- **B（不变差，经验对照）— 未做**。没有「群攻键留空」的基准组。**且当前缺仪器**：日志里没有任何经验读数（`exp=` 零命中），经验只被停滞守卫在内存里读，要跑 B 得先加一行低频经验日志或人肉抄表。
- **C（症状消失）— 未确认**。「被围时放得出群攻」由 A 的 71 次触发间接支持；「不再左右扭」只有一个无对照的旁证：同一份日志里 208 次转向中 103 次与上次反向（**49.8%**），而 spec §1 引用的历史基线是 12/17 = 70.6% —— 样本只有 17 次且非同图同配置对照，**不足以当结论**。

离线证据（这部分是完整的）：全量 552 用例，仅 `test_anchor_offline.test_b_anchor_y_in_expected_band` 红且为既有失败（在本分支起点 `651e155` 上复跑同样红）；`py_compile` 全量通过。
