---
name: mxd-model-training
description: 新地图怪物检测模型的完整训练流水线：采集帧 → 人工标注（含 2 类 player）→ 切分 train/val → yolo 训练 → 导出 ONNX → 部署 + 备份。当用户要求「采集」「标注」「切分」「训练模型」「重新训练」「部署模型」或换新地图训练时使用。覆盖 2 类标注规则、后台化训练与 resume、部署前备份、预标注视觉验收等全部已验证踩坑。
---

# mxd 新地图模型训练流水线

> 适用：给冒险岛新地图训练（或微调）怪物检测模型。完整链路：
> **采集 → 标注 → 切分 → 训练 → 导出 ONNX → 部署 + 备份**。
> 详细背景见 `OPERATION_GUIDE.md`（注意其中 H:\ok-mxd 路径为旧机器示例）与 `AGENTS.md` §2/§3/§7。

## 0. 数据与路径铁律

- 数据集在项目根 `dataset/`；`mobs.yaml` 的 `path: .` **要求从 dataset 目录执行** yolo train/export。
- 标注文件与图片同名不同后缀（`frame_0001.png` → `frame_0001.txt`），YOLO txt 格式 `class cx cy w h`（归一化）。
- 采集分辨率必须与历史训练数据一致（**2560×1440**，勿用 4K）——4K 帧与 2K 历史数据混训导致怪/名字牌相对大小分布不一致。
- **禁止 hard code 本地路径**（项目铁律 §11.1）：命令用 `.venv-warrior\Scripts\python.exe` / `yolo.exe` 相对路径或运行目录推导。
- 当前部署模型：`assets/mob_model/mob.onnx`（现为 v8s 双类；master 仓库版为 mob_player_v1 12.7MB）。部署前必须备份旧模型。

## 1. 采集帧 —— record_frames.py

前置：**先停 GUI**（GUI 持有 WGC 会话，采集会无限挂起）。进游戏目标地图，模拟巡逻视角走动（不站桩、不攻击），帧间隔 1~2s：

```powershell
$env:PYTHONUTF8=1; .\.venv-warrior\Scripts\python.exe scripts\record_frames.py <地图名> [间隔秒] [数量]
```

- 产出 `dataset/raw/<地图名>/frame_{n:04d}.png`（帧号接续已有文件）。
- **必须有纯背景负样本帧**（区别"有怪/没怪"，越多越好）。
- 新地图先小批量迭代（用户 2026-08-10 拍板）：先 10-30 帧标注 + 增量训练 + 视觉验收未训练帧，有效再扩量。

## 2. 标注 —— label_boxes.py（2 类规则）

```powershell
.\.venv-warrior\Scripts\python.exe scripts\label_boxes.py dataset\raw\<地图名>
```

**快捷键**：鼠标左键拖拽=添加框 / `c` 切换类别（0=mob 红 / 1=player 绿，切换成功=终端打印「当前类别: 1 (player)」；需窗口焦点，长按或先单击图片窗口）/ `r` `d` 删最后 / 右键点击删除 / `n` 空格=保存并下一张（0 框存空 txt=负样本）/ `p`=上一张 / `q`=退出。

**2 类标注铁律（2026-08-10 T14 确立）**：
- player 类**只框自己**（名字牌正下方角色），画面里其他玩家/宠物一律不框（当背景）——框了路人模型学会"任意玩家"。
- 每帧必标自己（分两轮：先标 mob，再切 `c` 标 player）。
- 遮挡处理：部分重合 → 照常补完整闭合框（含被挡部分）；完全看不到本体 → 该帧不进训练集（切分时剔除）。
- player 框高 ≈0.15-0.17 归一化（比 mob 高），可据此抽查校验。

**预标注（可选）**：`scripts/prelabel_from_onnx.py` 用现有 mob.onnx 自动预标（必须走 OpenVINO，ultralytics 加载 onnx 卡死 120s+）。**预标注必须先视觉验收再用**——新地图模型没见过的新怪种必然 100% 误检。空 txt 会被重标，跑完需检查负样本帧。

## 3. 切分 —— final_split.py

```powershell
.\.venv-warrior\Scripts\python.exe scripts\final_split.py --train <地图名> --val <地图名> --frames N
```

- `--train` 地图取**全部帧**（copy_map_all），`--frames` **仅作用于 val 地图**（后 N 帧复制重命名 frame_0000 起）。
- **必须显式 `--val <地图> --frames N`**（默认 `DEFAULT_VAL_MAPS=['map3']` 本机不存在会 FileNotFoundError）。
- 混合训练建议：多地图各取前 90% 入 train / 后 10% 入 val（地图内时序不重叠），文件名加 `{地图名}_` 前缀。
- 切分后建议检查：train/val 图片数与标注 txt 数一致、负样本帧（空 txt）保留。

## 4. 训练 —— yolo train（必须从 dataset 目录 + 用 yolo.exe）

```powershell
# 从 dataset 目录执行（mobs.yaml path: . 相对 cwd 解析）
..\.venv-warrior\Scripts\yolo.exe train data=mobs.yaml model=..\yolov8s.pt imgsz=1280 epochs=100 batch=8 device=0 project=runs name=<名>
```

- **用 `yolo.exe`**（`python -m ultralytics` 报 No module named ultralytics.__main__）。
- 模型档位：v8n（3.2M，快）/ **v8s（11.1M，推荐：少误检，挂机场景更优）** / v8m（25.9M，batch≤4）。4090 24GB 边界：v8s batch8≈10-12G。
- 预训练权重首次联网下载（`yolov8s.pt` 21.5MB），代理：`$env:https_proxy="http://127.0.0.1:10800"`；离线用 `model=..\yolov8s.pt` 绝对路径 + `YOLO_OFFLINE=true` 跳过下载。
- **长训练必须 OS 级后台化**（bash 600s 超时会连坐杀掉 yolo 子进程）：

```powershell
$cmd = '$env:YOLO_OFFLINE="true"; C:\projects\mxd-script\.venv-warrior\Scripts\yolo.exe train data=mobs.yaml model=C:\projects\mxd-script\yolov8s.pt imgsz=1280 epochs=100 batch=8 device=0 project=runs name=<名> *> logs\train_<名>.log'
Start-Process powershell -ArgumentList "-EncodedCommand", $([Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))) -WindowStyle Hidden
```

- 中断后用 `yolo.exe train resume model=<last.pt> ...`（args 与首次一致）续训不丢已训 epoch。
- 增量训练：从上一 best.pt 起步（`model=runs\detect\runs\<上一名>\weights\best.pt`），保留旧地图特征。

## 5. 导出 ONNX

```powershell
# 从 dataset 目录执行；产物路径带 detect/runs/ 层
..\.venv-warrior\Scripts\yolo.exe export model=runs\detect\runs\<名>\weights\best.pt format=onnx imgsz=1280
```

## 6. 部署 + 备份（铁律）

1. **备份旧模型**：`Copy-Item assets\mob_model\mob.onnx assets\mob_model\mob.onnx.bak_<日期>_<iterN>`（现有多层 .bak 链）。
2. 复制新模型：`Copy-Item dataset\runs\detect\runs\<名>\weights\best.onnx assets\mob_model\mob.onnx`。
3. 部署前确认 2 类语义：master 的 YOLO 关联锚点逻辑把 class1=player 当**任意玩家** bbox 接管锚点；若模型是「只标自己」训练的双类，语义差异需先向用户确认（2026-08-10 遗留）。
4. 部署后重启 GUI 才生效（模型懒加载 + 热重载不覆盖模型文件）。

## 7. 验收

- 离线看框：`scripts/detect_and_draw.py <best.pt> <帧目录> --conf 0.25`（输出 _detected.png 红框）。
- 实机看框：GUI「启用标记框」+ 任务配置显示开关（黄=怪、绿=player、蓝/红=攻击区）。
- **训练验收用 threshold 0.25**（find_mobs 默认 0.5）；误检多→补标该背景帧为空样本重训；漏检→补标漏掉的帧。
- 新特性必须带单测 + E2E（见 AGENTS.md §11）。
