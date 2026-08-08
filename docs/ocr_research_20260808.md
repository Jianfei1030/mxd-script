# OCR 方案深度调研报告

> 调研日期：2026-08-08
> 调研目标：解决角色名字牌 OCR 检测率极低、不配合模板匹配几乎找不到名字的问题

---

## 一、当前系统分析

### 1.1 现有管线

```
游戏帧 (2560×1440)
  → 切块 640×240 (overlap 200px, ~12 块)
  → PaddleOCR v5 ONNX (OpenVINO 后端)
    → DB 检测器 (Differentiable Binarization) 提取文字框
    → PP-OCRv5 识别器 (rec_image_shape: 3, 48, 320) 识别文字
  → 匹配角色名
  → 模板分片快通道兜底 (白字二值化 + 竖切 2 片 matchTemplate)
```

**关键代码**：`src/detect/anchor.py` + `src/detect/ocr_engine.py`
**OCR 引擎**：`onnxocr-ppocrv5==0.0.18`（site-packages/onnxocr/）
**模型**：DB 检测 + PP-OCRv5 识别，OpenVINO 编译加速

### 1.2 问题诊断

| 症状 | 根因分析 |
|------|----------|
| 31px 小字检测不到 | DB 检测器 `det_limit_side_len=960`，2560 宽图被缩到 ~960，31px 字被压到 ~12px，低于 DB 的检测下限 |
| 白字+黑描边检测不稳定 | DB 对高对比描边文字的边缘响应不均匀，描边和文字本体可能被割裂成不同区域 |
| 半透明底框干扰 | 底框的 alpha 混合让背景亮度变化大，DB 的全局阈值难以适应 |
| 负样本误检 | `max_candidates=1000` 产出大量低质量框，噪声文字被误识别 |
| 冷启动无模板 | OCR 先命中一次才能裁模板，首次运行时完全依赖 OCR |

### 1.3 现有缓解措施

- **模板分片匹配**：白字二值化(阈值 150-255) → 竖切 2 片 → TM_SQDIFF_NORMED，怪盖住半边也能命中
- **快/慢通道**：快通道只搜上次锚点附近小窗，慢通道搜中央全区
- **部分匹配**：被遮挡只剩子串(≥ 过半长)也收
- **外推**：寻怪中按移动方向外推锚点 x

**问题**：模板匹配需要 OCR 先成功一次才能裁模板，且背景变化/分辨率变化会失效。

---

## 二、调研发现的方案

### 方案 A：集成 meikiocr 检测器（推荐优先尝试）

**项目**：[rtr46/meikiocr](https://github.com/rtr46/meikiocr)
**安装**：`pip install meikiocr`（PyPI 月下载 4100+，最后更新 2026-04-11）

**核心架构**：
- **检测器**：`meiki.text.detect.v0.1` — CRAFT (Character Region Awareness for Text) 架构
  - 专门为游戏文字训练，在游戏文本 benchmark 上**超越 PaddleOCR DB、EasyOCR 等通用检测器**
  - 字符级热度图检测，天然适合小字体、描边文字
  - 输出：文字行边界框 + 置信度
- **识别器**：`meiki.text.recognition.v0` — PARSeq 架构
  - Pareto 最优的准确率/延迟 tradeoff
  - 支持日文（与中文有大量字符重叠）

**用法**：
```python
from meikiocr import MeikiOCR
ocr = MeikiOCR()
results = ocr.run_ocr(image)
# 返回 [{'text': '...', 'box': [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], 'confidence': 0.95}]
```

**优势**：
- ONNX 原生推理，可直接用 OpenVINO 加速
- 游戏文字专门训练，比通用 OCR 准确率高得多
- 活跃维护，社区反馈好
- 可单独用检测器（`run_detection`），识别器可替换为 PaddleOCR rec（中文更好）

**局限**：
- 训练数据是日文游戏，中文识别需验证（但检测是通用的，不依赖语言）
- 识别器限制 48 字符/行（名字牌场景不影响）
- 检测器限制 64 个框/图（名字牌场景不影响）

**集成思路**：
1. 用 `meikiocr.run_detection()` 替换 PaddleOCR 的 DB 检测器做文字框检测
2. 检测到的框送 PaddleOCR rec 做中文识别（PP-OCRv5 rec 的中文识别已经很好）
3. 保留模板匹配作为第三层兜底

**预估工作量**：2-3 天

---

### 方案 B：PaddleOCR 预处理增强（低成本，可立即尝试）

在现有 PaddleOCR 管线的检测前加入预处理，提升白字+描边文字的检测率。

#### B1. 白字增强 + 反转

```python
def enhance_white_text(img):
    """白字黑描边 → 反转为黑字白底，增强 OCR 检测率。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # CLAHE 增强局部对比度
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    # 反转：白字黑底 → 黑字白底（OCR 模型对黑字白底更友好）
    inverted = cv2.bitwise_not(enhanced)
    return cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)
```

#### B2. HSV 色彩隔离（参考 ok-gf2 项目）

```python
def isolate_white_hsv(img):
    """只保留白色像素，过滤背景噪声。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 白色：低饱和度 + 高亮度
    mask = cv2.inRange(hsv, (0, 0, 150), (180, 60, 255))
    result = cv2.bitwise_and(img, img, mask=mask)
    return result
```

#### B3. 形态学处理（连接描边和文字）

```python
def morphological_clean(img):
    """小核膨胀连接描边和文字本体。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    dilated = cv2.dilate(binary, kernel, iterations=1)
    return cv2.cvtColor(dilated, cv2.COLOR_GRAY2BGR)
```

**优势**：改动最小，可立即 A/B 测试
**局限**：DB 检测器的根本限制（小字特征图分辨率不足）可能无法完全解决
**预估工作量**：半天

---

### 方案 C：调整 PaddleOCR 检测参数

```python
# 降低检测输入分辨率限制，让小字不被过度压缩
params.det_limit_side_len = 480  # 默认 960，降低让小字保留更多细节
params.det_limit_type = 'min'    # 默认 'max'，改为按短边限制

# 提高检测阈值，减少噪声误检
params.det_db_thresh = 0.3       # 默认 0.3
params.det_db_box_thresh = 0.6   # 默认 0.5，提高减少低质量框
params.det_db_unclip_ratio = 1.5 # 默认 1.5

# 降低检测输入的最小边
params.det_limit_side_min = 48   # 默认 0
```

**优势**：零代码改动，只调参数
**局限**：效果有限，DB 架构对小字的检测能力有上限
**预估工作量**：1 小时

---

### 方案 D：自训练 CRAFT 检测器（长期最优解）

用冒险岛截图数据训练专门的文字检测模型：

1. **数据准备**（1-2 天）：
   - 收集 200+ 张含名字牌的游戏截图（当前已有 70+ 张）
   - 标注名字牌区域（现有 `label_boxes.py` 可复用，改标文字框即可）
   - 数据增强：旋转、缩放、模糊、亮度变化

2. **模型训练**（半天）：
   - 基础模型：CRAFT 预训练权重
   - 微调：用冒险岛名字牌标注数据 fine-tune
   - 训练框架：PyTorch → 导出 ONNX

3. **部署**：
   - ONNX + OpenVINO 推理
   - 替换 DB 检测器，保留 PP-OCRv5 rec

**优势**：针对性最强，准确率最高
**局限**：需要持续维护训练数据
**预估工作量**：3-5 天

---

### 方案 E：YOLO 文字区域检测 + OCR（混合方案）

用 YOLO 检测名字牌区域（已有 YOLO 检测怪物的经验），然后在检测到的区域内做 OCR：

1. **YOLO 检测名字牌**：
   - 在现有 mob 检测模型基础上，增加 `nametag` 类别
   - 或训练单独的名字牌检测模型

2. **OCR 识别**：
   - YOLO 检测到的名字牌区域 → 裁切 → PaddleOCR rec 识别

**优势**：YOLO 对小目标检测鲁棒，不受文字描边/底框干扰
**局限**：需要额外训练数据，增加推理开销（YOLO + OCR 双模型）
**预估工作量**：3-4 天

---

### 方案 F：升级到 PaddleOCR 3.0 / PP-OCRv5 最新版

PaddleOCR 3.0 (2026) 有显著改进：
- Medium tier: 检测 +4.6%、识别 +5.1%
- 50 种语言统一识别
- 参数量仅 34.5M

**但**：当前用的是 `onnxocr-ppocrv5==0.0.18`（ONNX 导出版），升级需要：
1. 安装最新 `paddleocr` 包
2. 重新导出 ONNX 模型
3. 验证 OpenVINO 兼容性

**优势**：官方升级，兼容性好
**局限**：ONNX 导出流程可能有坑，PaddlePaddle 框架依赖重
**预估工作量**：1-2 天

---

## 三、方案对比

| 方案 | 准确率提升 | 实施成本 | 风险 | 推荐优先级 |
|------|-----------|---------|------|-----------|
| **A. meikiocr 检测器** | ⭐⭐⭐⭐⭐ | 中 (2-3天) | 低 (ONNX 原生) | **🥇 首选** |
| **B. 预处理增强** | ⭐⭐⭐ | 低 (半天) | 无 | **🥈 先做** |
| **C. 调参** | ⭐⭐ | 极低 (1h) | 无 | **🥉 同时做** |
| **D. 自训练 CRAFT** | ⭐⭐⭐⭐⭐ | 高 (3-5天) | 中 | 长期 |
| **E. YOLO+OCR** | ⭐⭐⭐⭐ | 高 (3-4天) | 中 | 备选 |
| **F. 升级 PaddleOCR** | ⭐⭐⭐ | 中 (1-2天) | 中 | 备选 |

---

## 四、推荐实施路径

### 阶段 1：快速验证（1 天）

1. **调参** (方案 C)：降低 `det_limit_side_len`，提高 `det_db_box_thresh`
2. **预处理** (方案 B)：在 `anchor.py` 的 `_scan` 中加入白字增强预处理
3. **A/B 测试**：用存档帧对比改进前后的检测率

### 阶段 2：集成 meikiocr（2-3 天）

1. 安装 meikiocr，验证中文名字牌检测效果
2. 如果检测好但识别差 → 用 meikiocr 检测 + PaddleOCR rec 识别
3. 如果都好 → 直接替换整个管线
4. 保留模板匹配作为第三层兜底

### 阶段 3：长期优化（可选）

1. 如果 meikiocr 对中文不够好 → 自训练 CRAFT (方案 D)
2. 如果需要更高的鲁棒性 → YOLO+OCR 混合 (方案 E)

---

## 五、关键参考项目

| 项目 | 链接 | 参考价值 |
|------|------|----------|
| meikiocr | github.com/rtr46/meikiocr | 游戏文字 OCR 专用，CRAFT+PARSeq |
| ok-gf2 | github.com/AliceJump/ok-gf2 | 同框架游戏自动化，HSV 隔离+PaddleOCR |
| RSTGameTranslation | github.com/thanhkeke97/RSTGameTranslation | 游戏实时翻译，OCR 对比评测 |
| NVIDIA STDR | developer.nvidia.com/blog/robust-scene-text-detection-and-recognition-implementation/ | CRAFT+PARSeq 工业级实现 |
| PaddleOCR 3.0 | github.com/PaddlePaddle/PaddleOCR | PP-OCRv5 最新改进 |
| auto-maple | github.com/tanjeffreyz/auto-maple | MapleStory 自动化，模板匹配方案 |

---

## 六、技术细节补充

### 6.1 CRAFT vs DB 检测原理对比

**DB (Differentiable Binarization)**：
- 对整个文字区域输出一个二值化概率图
- 对大文字效果好，小文字的特征图分辨率不足
- 全局阈值，对亮度变化敏感

**CRAFT (Character Region Awareness for Text)**：
- 对每个字符输出一个高斯热度图（region score）
- 字符级检测，天然适合小字体
- 通过 affinity score 连接相邻字符成行
- 对描边、阴影等干扰更鲁棒

### 6.2 PARSeq 识别器优势

- **Attention-based**：不像 CTC 只能从左到右，PARSeq 可以双向注意力
- **更强的鲁棒性**：对变形、模糊、低分辨率文字识别更好
- **游戏文字训练**：meikiocr 的 PARSeq 专门在游戏字体上训练

### 6.3 白字二值化预处理原理

名字牌是白字(255) + 黑描边(0) + 半透明底框(100-200 混合)：
- 直接送 OCR：描边和底框都会被检测为"文字"
- 白字二值化(阈值 150-255)：只保留白字形，描边和底框归零
- 反转后：白字→黑字，白底→黑底，OCR 模型对黑字白底更友好

---

## 七、决策记录

- 2026-08-08：完成初步调研，确定 meikiocr + 预处理增强为首选方案
- 待验证：meikiocr 对中文名字牌的检测效果
- 待验证：预处理增强对现有 PaddleOCR 的提升幅度
