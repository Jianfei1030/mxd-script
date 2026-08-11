# ok-mxd 全流程操作手册:从训练到自动打怪

> 适用版本:v0.1.0。本手册覆盖完整链路:**采集 → 标注 → 训练 → 看 bbox 效果 → 标定 → 实机打怪**。
> 所有命令在**项目根目录** `H:\ok-mxd\ok-mxd` 下执行。
> 训练/推理脚本需要 `ultralytics`;采集/标注/标定脚本只依赖 `cv2` + 项目自带依赖。
>
> ⚠️ 本仓库含**站桩打怪**（`MapleFarmTask`）与**战士巡逻扩展**（Phase 2 开发中,实机为「左右巡逻打怪」）。
> 战士用户训练数据**按巡逻视角采集**(见 1.1),与未来巡逻实机对齐;
> 站桩用户可跳过 1.1 的巡逻视角要求与第 2 节标定、第 3.4/3.5 节战士相关章节。

---

## 0. 环境准备(一次性的)

### 0.1 Python 环境

项目依赖 ok-ww 自带的 Python(自带的 3.10 缺 PySide6/qfluentwidgets,跑不了任务代码)。

```powershell
# 主仓库已验证的 ok-ww 嵌入式 Python
$PY = "H:\ok-mxd\data\apps\ok-ww\python\python.exe"
```

已装好的依赖(2026-08-06 验证):

```
pyside6-fluent-widgets==1.8.3   # GUI 框架
opencv-python==4.12.0.88        # 视觉
numpy==2.2.6
psutil / comtypes / pycaw / pydirectinput / pynput / pywin32   # 输入/系统
openvino==2026.2.1              # 模型推理加速
```

> **训练/推理脚本(`autolabel.py` / `detect_and_draw.py` / `yolo train`)还需要 `ultralytics`**:
> `pip install ultralytics`。训练较吃 GPU,建议在有独显/云 GPU 的环境跑,本机只做采集+标注。

### 0.2 运行约束(游戏相关,不可违背)

- 游戏必须是**冒险岛怀旧服**(进程 `Maplestory_Classic.exe` / 窗口类 `UnityWndClass`)
- 分辨率校准值 **2560x1440**(不符只提醒、不自动停;但 ROI 全偏)
- **必须以管理员身份运行** GUI(按键走 PyDirect 驱动级,非管理员被 BlackCipher 拦截)
- 挂机期间**游戏窗口保持前台**,不要动键盘鼠标;不要拖动/缩放游戏 UI
- **急停快捷键:F9**(全局)

### 0.3 游戏内按键设置(与 `config.py` 一致,可在 GUI 改)

| 功能 | 默认键 | 说明 |
|---|---|---|
| 攻击键 | `ctrl` | 与游戏内设置一致 |
| 血药键 | `home` | 快捷栏对应槽位 |
| 蓝药键 | `insert` | 快捷栏对应槽位 |
| 回城卷键 | (空) | 留空则低血只停不逃 |
| 拾取键 | `z` | 默认关拾取 |
| 宠物食物键 | (空) | 喂宠物用;留空不喂。先在游戏内把宠物食物拖到快捷键再绑定 |
| 椅子键 | (空) | 坐椅用;留空不坐。先在游戏内把椅子拖到快捷键再绑定 |

---

## 1. 训练流程(新地图从零开始)

> 目标:给新地图训练(或微调)怪物检测模型,产出 `best.pt`,供实机识别怪物。

### 1.1 采集帧 —— `record_frames.py`

在游戏里**进入目标地图**,开着游戏跑:

```powershell
& $PY scripts\record_frames.py <地图名> [间隔秒] [数量]
```

示例(地图叫 `training_ground`,2 秒一帧,采 50 帧):

```powershell
& $PY scripts\record_frames.py training_ground 2 50
```

- 输出到 `dataset/raw/<地图名>/frame_0000.png ... frame_0049.png`
- 单帧截图(不连续采集):`& $PY scripts\capture_frame.py <输出.png>`

**怎么采:模拟实机巡逻,不要站桩**

> ⚠️ 你的实机是**左右巡逻打怪**,不是站桩。采集必须模拟巡逻时的真实画面:角色在动、背景在滚、怪从各个方向进入——模型学到的画面分布要和实机一致,否则实机识别会掉链子。

- **沿着巡逻路径边走边采**:在目标地图里左右来回走动(和你 Phase 2 巡逻的路线一致),采集脚本在走的过程中自动抓帧
- **不要攻击**:只移动,让怪自然出现在画面里(被打退/移动中的怪画面后面补)
- 走完一段换一条路径(上下层/不同刷怪走廊),覆盖更多背景和怪的相对位置
- 帧间隔建议 **1~2 秒**(移动中画面变化快,间隔太大会漏掉怪出现的瞬间)

**采多久 / 采多少**

- **1 条巡逻路线:50 帧 ≈ 1~2 分钟**(1~2 秒间隔 × 50 = 50~100 秒,走完 1~2 个来回)
- **总量建议:3 条路线 × 50 帧 = 150 帧**(原管线标准)。想更稳 → 3~4 条路线 × 50~80 帧
- 不够就补采:训练后看哪些帧误检/漏检,专门补那类画面再重训

**最好采集到什么(检查清单)**

- [ ] 角色**在移动中**的帧(巡逻视角,非静止)—— 实机常态
- [ ] 怪多:满屏 5+ 只的帧
- [ ] 怪少:零星 1~2 只的帧
- [ ] **没怪:纯背景帧(负样本)—— 必须要有,越多越好,模型靠它区分"有怪/没怪"**
- [ ] 怪在画面**左侧 / 右侧 / 高处 / 低处**都出现过
- [ ] 3 条巡逻路线背景不同
- [ ] 同图有多种怪 → 每种都采到
- [ ] 含 NPC / 装饰物 / 地形特征的帧 → 让模型学会不把它们当怪

### 1.2 人工标注 —— `label_boxes.py`

```powershell
& $PY scripts\label_boxes.py dataset\raw\<地图名>
```

**标注快捷键**:

| 按键 | 功能 |
|---|---|
| 鼠标左键**拖拽** | 添加一个怪物框 |
| `r` / `d` | 删除最后一个框 |
| `n` / `空格` | 保存当前图标注,进入下一张(0 框会存空 txt = 负样本) |
| `p` / `Backspace` | 保存并返回上一张 |
| `q` / `Esc` | 退出 |

- 标注保存为与图片同名的 `.txt`(YOLO 归一化格式 `0 cx cy w h`),放图片同目录
- **至少标 30 帧以上**(标注质量直接决定模型好坏;标错了后面很难救)
- 怪物很小/被遮挡时,框尽量包住完整怪物身体

### 1.3 抽查标注(训练前必做)—— `draw_yolo_boxes.py`

把标注框画回图上,肉眼核对是否贴怪:

```powershell
& $PY scripts\draw_yolo_boxes.py dataset\raw\<地图名>\frame_0000.png
```

- 输出 `..._boxed.png`(红框),打开看图
- 框明显错位/漏标 → 回到 1.2 修正

### 1.4 切分 train/val —— `bootstrap_split.py` / `final_split.py`

```powershell
# 快速试跑:每地图前 10 帧
& $PY scripts\bootstrap_split.py --train <图A> <图B> --val <图C> --frames 10

# 正式全量:每地图前 50 帧(须先完成 1.2 标注)
& $PY scripts\final_split.py --train <图A> <图B> --val <图C> --frames 50
```

- `--train`:训练集地图(建议 2 个,怪分布不同),`--val`:验证集地图(1 个,模型没见过的)
- **按地图整块切分,不随机混洗**(防止同一屏的帧同时进 train/val 造成假高分)
- 输出到 `dataset/images/{train,val}/` + `dataset/labels/{train,val}/`
- 不带参数时默认 `--train map1 map2 --val map3 --frames 10|50`(向后兼容)

### 1.5 训练 —— `yolo train`(ultralytics)

```powershell
# 在有 ultralytics + GPU 的环境执行(本机不需要跑)
yolo train data=dataset/mobs.yaml model=yolov8n.pt imgsz=1280 epochs=50
```

- `dataset/mobs.yaml` 已修为相对路径(`path: .`),从仓库根跑即可
- 产出模型在 `dataset/runs/<本次运行名>/weights/best.pt`
- **弱模型自举(可选)**:先用前 10 帧训练一个弱模型,再用它自动标注其余帧,人工只纠错:

```powershell
# 1) 弱模型:只切前 10 帧训练
& $PY scripts\bootstrap_split.py --train <图A> <图B> --val <图C> --frames 10
yolo train data=dataset/mobs.yaml model=yolov8n.pt imgsz=1280 epochs=50 project=dataset/runs name=mob_bootstrap

# 2) 弱模型自动标注剩余帧(写 txt,无检测不留 txt)
& $PY scripts\autolabel.py --maps <图A> <图B> <图C> --start 10 --end 49 --model dataset/runs/mob_bootstrap/weights/best.pt

# 3) 人工抽查修正(draw_yolo_boxes / label_boxes)
# 4) 全量重切 + 正式训练
& $PY scripts\final_split.py --train <图A> <图B> --val <图C> --frames 50
yolo train data=dataset/mobs.yaml model=yolov8n.pt imgsz=1280 epochs=50
```

### 1.6 看模型识别 bbox 效果(训练后验收)—— `detect_and_draw.py`

**离线看框**(训练好的模型跑在帧上画红框):

```powershell
# 单张
& $PY scripts\detect_and_draw.py dataset\runs\mob_bootstrap\weights\best.pt dataset\raw\<地图名>\frame_0000.png

# 整目录批量(输出 _detected.png)
& $PY scripts\detect_and_draw.py dataset\runs\mob_bootstrap\weights\best.pt dataset\raw\<地图名> --conf 0.25
```

- 输出红框 + 类别 + 置信度(`mob 0.87`)
- 看效果要点:
  - **框是否套住怪物本体**(过大/过小/偏移)
  - **是否漏检**(该框的没框) / **是否误检**(背景被框成怪)
  - 置信度阈值可调:`--conf 0.4` 更严格(少误检),`--conf 0.1` 更宽松(少漏检)
  - 效果差 → 回 1.2 补标出问题的帧 → 重训(自举循环)

**实机看框**(最直观):开 GUI + 勾选「启用标记框」→ overlay 直接显示实时怪物黄框 + 玩家绿框 + 接敌/攻击范围框(见第 3 节)。调试可视化已内化进 `MapleFarmTask`,不再需要独立的「战士调试」任务。

---

## 2. 攻击区标定 —— `calibrate_attack_zone.py`

> 战士武器不同,攻击距离不同。**攻击区必须你自己标定**,不能直接用默认 600x200。
> 流程:画一张标注图(锚点/身体中心/攻击区/怪物框)→ 肉眼对照实际挥刀范围 → 调整参数直到贴合。

### 2.1 准备一张帧

```powershell
& $PY scripts\capture_frame.py screenshots\calib_frame.png
# 或直接截屏/用已有截图,要求 2560x1440、角色名字牌在画面内
```

### 2.2 跑标定工具

```powershell
& $PY scripts\calibrate_attack_zone.py --frame screenshots\calib_frame.png --name <你的角色名>
```

参数:`--name 角色名`(可选,用于 OCR 定位名字牌,留空则锚在画面中心)/ `--width 600` / `--height 200` / `--offset 90`(名字牌到身体偏移)/ `--out <输出PNG>`

流程:

1. 脚本 OCR 定位名字牌 → 推算身体中心 → 画出搜索区(橙)/名字牌框(红)/身体中心点(黄)/攻击区(黄粗框)/怪物框(绿=区内,灰=区外)
2. 打开 `screenshots/calibrate_attack_zone.png` 肉眼对照:
   - **攻击区黄框 = 实际挥刀能打到的范围** → 贴合
   - 打不到那么远 → 调小 `--width`;打超了 → 调大
3. 调好的值填进 GUI「自动打怪」任务配置的「攻击区宽/高(像素)」「名字牌到身体偏移(像素)」

---

## 3. 实机挂机

### 3.1 启动 GUI

```powershell
# 管理员 PowerShell 里(右键"以管理员身份运行")
& $PY main_debug.py
```

> `main_debug.py` 启动会**清空 `screenshots/` 目录**(框架行为)。存档测试帧在 git 里,误删用 `git checkout -- screenshots/test_frames/` 恢复。

### 3.2 GUI 里要做的事

1. **Start 页**:点启动(连接游戏窗口)
2. **设置页「游戏按键」**:核对攻击/血药/蓝药/拾取键与游戏内一致
3. **触发任务页**:
   - 启用「**自动打怪**」(MapleFarmTask)—— 真正打怪挂机的任务;勾选 Start 页「启用标记框」可看实时可视化(玩家/接敌区/攻击区/怪物框)

### 3.3 「自动打怪」任务配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| 攻击模式 | 定频 | `定频`=间隔按键;`检测`=YOLO 框在攻击区内才打 |
| 攻击间隔(秒) | 1.5 | 定频模式:攻击按键节奏。检测模式:完整检测拍(锚点OCR+YOLO)的节流——攻击本身长按持续,不再受此限制 |
| 攻击区宽 / 高 | 0.6 / 0.6 | 检测模式:画面中心 ±30% 的矩形 |
| 攻击区中心X / Y | 0.5 / 0.5 | 检测模式:以站桩点为锚(帧比例),换点后重标 |
| 喝血阈值 / 喝蓝阈值 | 0.7 / 0.35 | HP/MP 低于此比例喝药 |
| 保命血线 | 0.25 | 低血:喝血 → 回城(若有卷)→ 停任务 |
| 死亡判定线 / 死亡确认帧数 | 0.02 / 20 | 连续 20 帧空血判定死亡 |
| 喝药无效上限 | 5 | 连喝 5 次 HP 不涨 → 停(药可能没了) |
| 药水检查间隔(秒) / 药水耗尽保护 | 30 / True | 低频 OCR 查快捷栏药数 |
| 拾取开关 / 拾取间隔(秒) | False / 30 | 默认关(掉平台风险,靠宠物) |
| 喂宠物开关 / 喂宠物间隔(秒) | True / 900 | 15 分钟按一次宠物食物键;键留空则不喂 |
| 坐椅开关 / 坐椅延迟(秒) | True / 3 | 检测模式闲置超过延迟自动坐椅子回血蓝;键留空则不坐 |
| 画面静止上限(秒) | 60 | 帧签名不变超时 → 停(卡死/掉线) |
| 经验停滞上限(分钟) | 10 | 经验不涨超时 → 停(无效挂机) |

### 3.4 「自动打怪」调试可视化(勾选「启用标记框」时显示)

调试可视化已内化进 `MapleFarmTask`(原独立「战士调试」任务已移除)。Start 页勾选「启用标记框」即画框,任务配置里的显示开关控制各元素:

| 配置 | 默认 | 说明 |
|---|---|---|
| 显示玩家框 | True | 玩家 bbox(绿) |
| 显示攻击区 | True | 接敌区(细,蓝=无怪/红=有怪)+ 攻击区(粗,同色) |
| 显示名字搜索范围 | True | 锚点搜索区(蓝虚线) |
| 显示寻怪同层带 | True | 寻怪同层高度带(青虚线) |
| 显示怪物框 | True | 怪物 bbox(黄)+ 脚底点(青) |

**Overlay 颜色**:

| 框 | 颜色 | 含义 |
|---|---|---|
| 玩家 bbox | 绿 | 身体中心为锚 |
| 接敌区/攻击区 bbox | 蓝 | 无怪进入 |
| 接敌区/攻击区 bbox | **红** | **有怪物进入(此朝向可命中)** |
| 怪物 bbox | 黄 | YOLO 检测框 |
| 脚底点 | 青 | 怪物脚底位置(判定锚点) |

### 3.5 实弹验证清单(调试 overlay 判据 A-G)

进游戏逐个确认,全部通过才算 overlay 层 OK(勾选「启用标记框」看框):

- **A** 三框(玩家/攻击区/怪物)都能套住对应对象
- **B** 朝向切左/右,攻击框换到对应侧别
- **C** 怪物进入攻击区 → 攻击框变红;**怪物在背后(非朝向侧)→ 不变红**
- **D** 走位被打退时,三框跟随角色移动
- **E** 朝向=自动时,跟随方向键移动翻向
- **F** 挂机 10 分钟无按键操作,不崩溃、不闪烁
- **G** 用标定工具核对攻击距离与实际挥刀命中点一致

### 3.6 挂机注意事项

- 挂机期间**游戏窗口保持前台**,别碰键盘鼠标(F9 可急停)
- 分辨率/UI 布局不能变(变了只提醒、不自动停,但 ROI 会偏)
- 检测模式不攻击 → 检查「攻击区中心」是否标定到站桩点
- 按键无效 → 确认管理员运行 + 游戏前台 + 按键与游戏内一致

---

## 4. 常见问题速查

| 现象 | 原因 / 解法 |
|---|---|
| `record_frames.py` 报"未找到游戏窗口" | 游戏没开 / 不是怀旧服进程;窗口标题须含「冒险岛怀旧服」 |
| 标注工具打不开 | 文件夹路径不对 / 无 PNG;`--check` 可自检 |
| `yolo train` 报 path 错误 | `dataset/mobs.yaml` 的 `path: .` 须相对仓库根执行 |
| 模型漏检 | 补标漏掉的帧(1.2)重训;或 `--conf` 调低 |
| 模型误检(框背景) | 补标该背景帧为空样本;或 `--conf` 调高 |
| 训练后 best.pt 在哪 | `dataset/runs/<运行名>/weights/best.pt`(autolabel 默认读 `dataset/runs/mob_bootstrap/weights/best.pt`) |
| 实机不攻击 | 攻击键与游戏内不一致 / 检测模式攻击区未标定 / 未管理员运行 |
| 自动停了 | 看日志(`logs/ok-mxd.log`):死亡/低血/药尽/静止/经验停滞;分辨率不符不自动停,只提醒 |
| GUI 启动清空 screenshots | 框架行为;恢复:`git checkout -- screenshots/test_frames/` |

---

## 5. 脚本索引

| 脚本 | 作用 |
|---|---|
| `scripts/record_frames.py` | 隔 N 秒抓帧存 `dataset/raw/<地图>/` |
| `scripts/capture_frame.py` | 抓单帧 PNG |
| `scripts/label_boxes.py` | 鼠标拖拽标注怪物框(快捷键见 1.2) |
| `scripts/draw_yolo_boxes.py` | 把标注画回图抽查 |
| `scripts/bootstrap_split.py` | 前 N 帧切 train/val(试跑) |
| `scripts/final_split.py` | 全量切 train/val(正式) |
| `scripts/autolabel.py` | 弱模型自动标注剩余帧 |
| `scripts/detect_and_draw.py` | 模型推理画框看效果 |
| `scripts/calibrate_attack_zone.py` | 攻击区/偏移标定(画标注图看图调参) |

## 6. 目录结构

```
dataset/
  raw/<地图名>/frame_XXXX.png (+ .txt 标注)   # 采集+标注
  images/{train,val}/                          # 切分结果(训练输入)
  labels/{train,val}/
  runs/<运行名>/weights/best.pt                # 训练产出
  mobs.yaml  classes.txt                       # 数据配置(单类 mob)
screenshots/calibrate/zone_*.png               # 标定攻击框输出
configs/config.json                            # GUI 配置(含标定结果)
```
