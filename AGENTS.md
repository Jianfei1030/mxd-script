# AGENTS.md —— mxd-script(ok-mxd)项目状态与工作指引

> 本文档是**项目当前状态的总沉淀**,供后续任何会话快速接续。改动本项目代码前,先读本文件。
> 最新状态以本文件为准;运行细节见 `OPERATION_GUIDE.md`(根目录),设计决策见 `docs/superpowers/specs/`。

---

## 1. 项目定位

**冒险岛怀旧服自动打怪脚本**,基于 ok-ww 框架(纯截屏 + 模拟输入,不读内存/不注入/不碰封包)。

- 原仓库:`https://github.com/Chappelliu/mxd-script`(public)
- 本 fork:`G:\projects\MyDocs\projects\mxd_script`,远端 `https://github.com/Jianfei1030/mxd-script`(**PRIVATE**)
- 核心区别:原作者是**法师站桩**;本 fork 按**战士(近战)巡逻打怪**需求扩展(Phase 2 开发中)

**运行硬约束(不可违背):**
- 仅 **2560x1440** 分辨率(代码硬校验,不符自动停)
- **必须管理员**运行 GUI(PyDirect 驱动级按键,非管理员被 BlackCipher 拦截)
- 游戏窗口**保持前台**,挂机期间不碰键盘鼠标
- 急停:`F9`
- 进程 `Maplestory_Classic.exe` / 窗口类 `UnityWndClass` / 标题 `冒险岛怀旧服`

---

## 2. 开发环境

- **测试/运行 Python 3.12**:`C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe`
  (系统 `python` 是 3.10,缺 PySide6,qfluentwidgets,跑不了任务代码)
- 已装:pyside6-fluent-widgets==1.8.3 / PySide6 / opencv-python==4.12.0.88 / numpy==2.2.6 / psutil / comtypes / pycaw / pydirectinput / pynput / pywin32 / openvino==2026.2.1
- **⚠️ ultralytics 未装**——训练/推理脚本(autolabel / detect_and_draw / yolo train)依赖它,但用户决策**训练不在本机跑**,用户侧自备 GPU 环境执行
- 测试命令(仓库根):
  ```
  & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest discover tests
  ```
  全量 73 tests = 1 既有失败(test_yolo 数据依赖: val 集无正样本)+ 7 跳过

---

## 3. 架构与机制

### 3.1 视觉方案
| 项 | 方案 | 说明 |
|---|---|---|
| HP/MP/EXP 条 | ROI 颜色占比 | cv2.inRange + 列填充率,帧比例坐标 2560x1440 校准 |
| 快捷栏药水数 | PaddleOCR | onnxocr-ppocrv5, OpenVINO, 3x 放大 |
| 怪物检测 | 自训练 yolov8n | ONNX 1280x1280, OpenVINO 运行;单类 'mob' |
| 玩家定位 | 名字牌 OCR 锚点 | `src/detect/anchor.py`(Phase 1 新增) |

### 3.2 输入层
PyDirect(SendInput 驱动级),管理员 + 前台。PostMessage 被 BlackCipher 拦截。

### 3.3 主循环
`MapleFarmTask`(TriggerTask 10Hz):分辨率守卫 → 死亡判定 → 保命 → 喝药 → 药水耗尽 → 攻击(检测/定频)→ 拾取 → 静止/停滞守卫。

### 3.4 游戏按键(config.py 默认,GUI 可改)
攻击 `ctrl` / 血药 `home` / 蓝药 `insert` / 回城卷 `''`(留空)/ 拾取 `z`。

---

## 4. 训练管线(采集→训练→看框)

全流程见 `OPERATION_GUIDE.md`。命令(仓库根):

```
record_frames.py <地图名> [间隔秒=2] [数量=50]   # 采集 → dataset/raw/<地图名>/
label_boxes.py dataset/raw/<地图名>              # 鼠标拖拽标注,快捷键见手册
draw_yolo_boxes.py <图>                          # 标注抽查 → _boxed.png
bootstrap_split.py --train A B --val C --frames 10   # 试跑切分
final_split.py --train A B --val C --frames 50       # 正式切分
yolo train data=dataset/mobs.yaml model=yolov8n.pt imgsz=1280   # 用户侧跑
autolabel.py --maps A B C --start 10 --end 49 --model <best.pt> # 弱模型自举
detect_and_draw.py <best.pt> <图或目录> [--conf 0.25]  # 看模型识别框
calibrate_warrior_zone.py <帧PNG> --name 角色名       # 攻击距离标定
```

**关键点:**
- `dataset/mobs.yaml` 已修为 **相对路径 `path: .`**(原指向作者 H: 盘,克隆后必须先修这类硬编码)
- **空怪帧必须保留(存空 txt=负样本)**,是单类模型区分有/无怪的关键
- 训练数据按**巡逻视角采集**(角色移动中,非站桩)——用户实机是巡逻打怪
- `.gitignore` 忽略 screenshots/* + dataset/raw/, images/, labels/, runs/(数据全本地采集)

---

## 5. 战士巡逻扩展(两阶段)

设计 spec:`docs/superpowers/specs/2026-08-06-warrior-patrol-design.md`

### Phase 1:Debug 可视化层(✅ 已完成,已 push)
独立只读任务 `WarriorDebugTask`(不按键),overlay 绘制三框:
- 玩家 bbox(绿,名字牌 OCR→身体中心→标定宽高矩形)
- 攻击范围 bbox(蓝,朝向侧半矩形)→ 怪脚底入区变**红**
- 怪物 bbox(黄 + 脚底点青)

配置项:`调试开关` / `调试刷新间隔` / `朝向`(左/右/自动)/ `角色名` / `名字牌到身体偏移` / `玩家宽` / `玩家高` / `攻击距离` / `攻击区高`。

**相关提交:** e56fa11(farm_logic 纯函数)/ abaff50(anchor 双通道)/ b4df996(overlay)/ 7fc2d07(标定工具)。

**⚠️ 已修 Bug:** `朝向` 手动配置此前从未被读取(只走自动推断),commit 11eb2d9 修复——手动左/右优先于自动(新增 `_resolve_facing`)。

### Phase 2:巡逻闭环(🔜 未开始,方案已定案)
- **状态机**:PATROL(巡逻走位)⇄ HUNTING(停走面向攻击)
  - PATROL:按方向走,每节拍检测近战攻击区;区内有怪 → HUNTING
  - HUNTING:面向怪攻击;怪死/消失 → 回 PATROL;怪打退超范围 → 朝怪走 0.3s → 回 PATROL
- **单屏折返巡逻**:玩家 x 比例 <0.2 → 向右;<0.8 → 向左;否则保持
- **朝向 = 自主移动键方向(方案 A,已确认)**:
  - 关键前提:巡逻移动由我们发键,方向是已知事实;且**打退不翻转朝向**(用户实测)
  - 故**无需视觉检测**(否决 sprite 模板匹配 / YOLO 朝类别)
  - 复用 `farm_logic.facing_update`;Phase 1 `_auto_facing` 仅限 debug 只读层
- **打退处理**:每帧重定位覆盖(怪被打退/玩家被打退都靠 recalc)

---

## 6. 当前状态与未完成工作

### ✅ 已完成
- MVP 全功能(站桩打怪/喝药/保命/死亡/守卫/拾取)
- Phase 1 debug 可视化层全部(4 提交已 push)
- 训练管线适配(split 自定义地图名 + mobs.yaml 相对路径 + detect_and_draw 看框)
- autolabel 参数化(--maps/--start/--end/--model/--conf)
- 全流程操作手册 `OPERATION_GUIDE.md`(根目录)
- fork 改 PRIVATE

### ⏳ 待办(按优先级)
1. **Phase 1 实弹验证(判据 A-G)**——需用户在游戏内实测,未执行。**A-G 未过不得进 Phase 2**
2. **Phase 2 巡逻闭环实现**——状态机 + 单屏折返 + 朝向攻击 + 打退重定位(方案已定,见 §5)
3. **待用户确认项(spec §5):**
   - 移动键位:左/右移动键是方向键还是 A/D?
   - 攻击键位:单一 `攻击键` 还是左右分离?
   - 宠物跟随:名字牌是否被宠物名遮挡(可关宠物名字显示?)

### ⚠️ 已知问题/风险
- test_yolo 失败是数据依赖(val 集无正样本),非代码 bug
- Phase 1 `_auto_facing`(位移推断)在打退时不可靠,仅限 debug 层用
- GUI 标定按钮列 M4 待办(目前标定走命令行)

---

## 7. 代码地图(关键文件)

| 文件 | 职责 |
|---|---|
| `src/task/MapleFarmTask.py` | 站桩打怪主任务(Phase 2 将加巡逻分支) |
| `src/task/WarriorDebugTask.py` | Phase 1 debug 可视化(只读三框) |
| `src/task/farm_logic.py` | 战士近战纯函数(攻击区/朝向/巡逻方向/脚底) |
| `src/detect/anchor.py` | 名字牌 OCR 锚点(快/慢双通道) |
| `src/task/BaseMapleTask.py` | 基类(Phase 2 将加 move/attack_facing) |
| `scripts/calibrate_warrior_zone.py` | 攻击距离标定工具 |
| `scripts/record_frames.py` | 采集帧 |
| `scripts/label_boxes.py` | 标注(鼠标拖拽) |
| `scripts/bin_split*.py` | 切分 train/val |
| `scripts/autolabel.py` | 弱模型自举标注 |
| `scripts/detect_and_draw.py` | 模型推理看框 |
| `config.py` | 游戏按键 + trigger_tasks 注册 |
| `dataset/mobs.yaml` | 训练数据配置(相对路径) |

---

## 8. 开发约定

- 纯函数逻辑放 `farm_logic.py`,可离线单测;任务层只接线 + 画框
- OCR 以函数参数注入(`ocr_fn=None`),可离线单测
- 多文件/多步任务用 task 工具跟踪;复杂软件任务优先 sub-agent 执行
- 改动前对照 spec 与本文档 §5/§6,不默认"站桩"思维(本 fork 是战士巡逻)
- 提交前跑全量测试确认无回归