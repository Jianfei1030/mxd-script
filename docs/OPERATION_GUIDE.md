# ok-mxd 全流程操作手册:从训练到自动打怪

> 适用版本:v0.1.0。本手册覆盖完整链路:**采集 → 标注 → 训练 → 看 bbox 效果 → 标定 → 实机挂机**。
> 所有命令在**项目根目录** `G:\projects\MyDocs\projects\mxd_script` 下执行。
> 训练/推理脚本需要 `ultralytics`;采集/标注/标定脚本只依赖 `cv2` + 项目自带依赖。

---

## 0. 环境准备(一次性的)

### 0.1 Python 环境

项目依赖 `Python 3.12`(系统自带的 3.10 缺 PySide6/qfluentwidgets,跑不了任务代码)。

```powershell
# 本机已验证的 Python 3.12
$PY = "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe"
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
- 分辨率必须是 **2560x1440**(代码硬校验,不符自动停)
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

---

## 1. 训练流程(新地图从零开始)

> 目标:给新地图训练(或微调)怪物检测模型,产出 `best.pt`,供实机识别怪物。

### 1.1 采集帧 —— `record_frames.py`

在游戏里**站到目标地图的刷怪点**,开着游戏跑:

```powershell
& $PY scripts\record_frames.py <地图名> [间隔秒] [数量]
```

示例(地图叫 `training_ground`,2 秒一帧,采 50 帧):

```powershell
& $PY scripts\record_frames.py training_ground 2 50
```

- 输出到 `dataset/raw/<地图名>/frame_0000.png ... frame_0049.png`
- **采集要点**(决定模型质量):
  - 怪分布不同时段各采一批(怪多 / 怪少 / **没有怪的帧**都要有)
  - **空怪帧是负样本,是模型区分"有怪/没怪"的关键,不要删**
  - 站桩采集时角色位置固定,怪会从屏幕两侧走进走出,天然覆盖各种位置
- 单帧截图(不连续采集):`& $PY scripts\capture_frame.py <输出.png>`

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

**实机看框**(最直观):开 GUI + 开「战士调试」任务 → overlay 直接显示实时怪物黄框 + 玩家绿框 + 攻击范围框(见第 3 节)。

---

## 2. 攻击距离标定 —— `calibrate_warrior_zone.py`

> 战士武器不同,攻击距离不同。**攻击距离必须你自己确认**,不能直接用默认 120。
> 流程:输入距离 → 画攻击框 PNG → 肉眼对照实际挥刀命中点 → 调整直到贴合。

### 2.1 准备一张帧

```powershell
& $PY scripts\capture_frame.py screenshots\calib_frame.png
# 或直接截屏/用已有截图,要求 2560x1440、角色名字牌在画面内
```

### 2.2 跑标定工具

```powershell
& $PY scripts\calibrate_warrior_zone.py screenshots\calib_frame.png --name <你的角色名>
```

参数:`--name 角色名`(必填,用于 OCR 定位名字牌)/ `--json configs/config.json`(写配置的路径)/ `--facing LEFT|RIGHT`(标定朝向,默认 RIGHT)

交互流程:

1. 脚本 OCR 定位名字牌 → 推算身体中心
2. 依次输入:**攻击距离(px,默认 120)** → 攻击区高(默认 200) → 名字牌到身体偏移(默认 90) → 玩家宽(60) → 玩家高(120)
3. 画攻击框 PNG 到 `screenshots/calibrate/zone_RIGHT_120px.png`,打开肉眼对照:
   - **攻击框右边缘 = 实际挥刀能打到的水平最远点** → 贴合
   - 打不到那么远 → 输入 `n-20` 减小;打超了 → 输入 `n+20` 增大(回车重画当前值)
4. 贴合后输入 `y` → 自动写入 `configs/config.json` 的「战士调试」任务配置

| 输入 | 功能 |
|---|---|
| `y` | 写入配置,标定完成 |
| `n+20` / `n-20` | 攻击距离 ±20px 重画 |
| `n`(不带数字) | 攻击距离 +20px 重画 |
| 回车 | 保持当前值重画 |

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
   - 启用「**自动打怪**」(MapleFarmTask)—— 真正打怪挂机的任务
   - 启用「**战士调试**」(WarriorDebugTask)—— 只读可视化,不按键,与自动打怪可同时开

### 3.3 「自动打怪」任务配置项

| 配置 | 默认 | 说明 |
|---|---|---|
| 攻击模式 | 定频 | `定频`=间隔按键;`检测`=YOLO 框在攻击区内才打 |
| 攻击间隔(秒) | 1.5 | 定频攻击节奏 |
| 攻击区宽 / 高 | 0.6 / 0.6 | 检测模式:画面中心 ±30% 的矩形 |
| 攻击区中心X / Y | 0.5 / 0.5 | 检测模式:以站桩点为锚(帧比例),换点后重标 |
| 喝血阈值 / 喝蓝阈值 | 0.7 / 0.35 | HP/MP 低于此比例喝药 |
| 保命血线 | 0.25 | 低血:喝血 → 回城(若有卷)→ 停任务 |
| 死亡判定线 / 死亡确认帧数 | 0.02 / 20 | 连续 20 帧空血判定死亡 |
| 喝药无效上限 | 5 | 连喝 5 次 HP 不涨 → 停(药可能没了) |
| 药水检查间隔(秒) / 药水耗尽保护 | 30 / True | 低频 OCR 查快捷栏药数 |
| 拾取开关 / 拾取间隔(秒) | False / 30 | 默认关(掉平台风险,靠宠物) |
| 画面静止上限(秒) | 60 | 帧签名不变超时 → 停(卡死/掉线) |
| 经验停滞上限(分钟) | 10 | 经验不涨超时 → 停(无效挂机) |

### 3.4 「战士调试」任务配置项(Phase 1 debug 可视化)

| 配置 | 默认 | 说明 |
|---|---|---|
| 调试开关 | False | 打开才绘制 |
| 调试刷新间隔(秒) | 0.3 | 绘制节拍(不占 10Hz 保命循环) |
| 朝向 | 自动 | 左 / 右 / 自动(自动=名字牌 x 位移推断) |
| 角色名 | (空) | **必填**!用于 OCR 定位名字牌 |
| 名字牌到身体偏移 | 90 | 名字牌中心 → 身体中心的垂直偏移 |
| 玩家宽 / 玩家高 | 60 / 120 | 玩家 bbox 尺寸 |
| 攻击距离 | 120 | **用第 2 节标定工具确认后的值** |
| 攻击区高 | 200 | 攻击范围矩形高度 |

**Overlay 三框颜色**:

| 框 | 颜色 | 含义 |
|---|---|---|
| 玩家 bbox | 绿 | 身体中心为锚 |
| 攻击范围 bbox | 蓝 | 无怪进入(朝向侧半矩形) |
| 攻击范围 bbox | **红** | **有怪物脚底进入攻击范围(此朝向可命中)** |
| 怪物 bbox | 黄 | YOLO 检测框 |
| 脚底点 | 青 | 怪物脚底位置(判定锚点) |

### 3.5 实弹验证清单(Phase 1 判据 A-G)

进游戏逐个确认,全部通过才算 debug 层 OK:

- **A** 三框(玩家/攻击区/怪物)都能套住对应对象
- **B** 朝向切左/右,攻击框换到对应侧别
- **C** 怪物进入攻击区 → 攻击框变红;**怪物在背后(非朝向侧)→ 不变红**
- **D** 走位被打退时,三框跟随角色移动
- **E** 朝向=自动时,跟随方向键移动翻向
- **F** 挂机 10 分钟无按键操作,不崩溃、不闪烁
- **G** 用标定工具核对攻击距离与实际挥刀命中点一致

### 3.6 挂机注意事项

- 挂机期间**游戏窗口保持前台**,别碰键盘鼠标(F9 可急停)
- 分辨率/UI 布局不能变(变了任务自动停)
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
| 自动停了 | 看日志(`logs/ok-mxd.log`):死亡/低血/药尽/静止/经验停滞/分辨率不符 |
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
| `scripts/calibrate_warrior_zone.py` | 攻击距离/玩家尺寸标定 |

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
