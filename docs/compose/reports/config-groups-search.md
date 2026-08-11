---
feature: config-groups-search
status: delivered
specs: []
plans:
  - plans/2026-08-10-config-groups-search.md
branch: master
commits: 6f7ce40..1e52a53
---

# 自动打怪卡片配置项分组+搜索 — Final Report

## What Was Built

「实时触发」tab 的「自动打怪」任务卡片展开区新增三项纯 UI 能力：(1) 全部 65 个配置项按功能分 9 组（攻击/拾取/保命与药水/走位与朝向/寻怪/角色定位/战斗细节/挂机辅助/调试），组标题青绿粗体 + 组间虚线，组内容连续排列；(2) 展开区顶部搜索框，输入关键字做**宽松匹配**（键名+描述子串、忽略大小写、空输入全显示），匹配项保留、组标题随组内匹配显隐，清空恢复全部分组；(3) 组标题可点击**折叠/展开**（会话级状态，▶/▼ 箭头指示），搜索时匹配组自动展开、清空后恢复折叠状态。

不触碰任何任务执行/配置读写逻辑——分组与搜索纯粹是展示层。无 `config_groups` 元数据的任务卡片（一次性任务、其他触发任务）渲染行为与修改前完全一致。

## Architecture

- **`src/task/MapleFarmTask.py`**：模块级 `CONFIG_GROUPS`（与 `DEFAULT_CONFIG` 相邻）——有序 `[(组名, [键, ...])]`，组显示顺序 = 定义顺序。`__init__` 暴露 `self.config_groups`。新增配置键必须同步归组（完整性测试强制）。
- **`src/task/config_groups.py`**：纯函数模块（离线可单测）——`group_of`（键→组）、`should_insert_header`（组切换判定）、`matches`（宽松匹配）、`visible_keys`/`visible_groups`（过滤结果计算）。
- **`ok/gui/tasks/ConfigCard.py`**（`TaskCard` 的父类，仅任务卡片使用）：消费 `task.config_groups`。`__ordered_config_keys` 按组序重排渲染键（组连续、每组只插一个标题）；`__maybe_add_group_header` 在组首插入 **QToolButton 标题**（点击 `__toggle_group` 折叠/展开，`group_widgets` 记录组→控件映射，`group_collapsed` 存会话级折叠状态）；`__maybe_add_search_box` 建搜索框（仅在有分组的卡片）；`__apply_search_filter` 收到 textChanged 后按纯函数结果 setVisible（有 query 时匹配优先并自动展开匹配组，无 query 时按折叠状态恢复）。全部走空检查——无分组的任务跳过所有新逻辑。

### Design Decisions

- **宽松匹配含描述**：键名或 config_description 都参与匹配，搜「阈值」能命中「喝药判定间隔(秒)」（描述里写「HP 低于阈值」）。这是有意行为——配置键名未必覆盖用户记得的说法。
- **渲染顺序按组重排**：DEFAULT_CONFIG 按历史开发顺序定义，组是交错的；若只插标题不重排，同一组会出现在多个位置。`__ordered_config_keys` 按 CONFIG_GROUPS 顺序渲染（组内按组定义顺序，未分组键兜底追加），无分组任务保持原 dict 顺序。
- **折叠与搜索互不打架**：折叠状态是会话级内存（不持久化）；有搜索词时匹配优先（组自动展开、箭头转 ▼），清空后按 `group_collapsed` 恢复折叠并同步箭头。widget 可见性永远是「搜索匹配 ∧ 组展开」由单一入口 `__apply_search_filter` 统一计算，避免两套 setVisible 互相覆盖。
- **过滤逻辑全下沉纯函数**：UI 只做装配（setVisible），匹配/过滤决策都在 `config_groups.py`，可离线断言（AGENTS.md §11.2）。

## Usage

打开「实时触发」→ 展开「自动打怪」卡片：
- 顶部搜索框输入关键字（如「锚点」「阈值」「喝药」）→ 匹配项保留、组标题随匹配显隐
- 清空搜索框（或点清空按钮）→ 恢复 9 组全量显示
- 无分组的任务卡片无搜索框、无组标题，行为不变

## Verification

- `tests/test_config_groups.py`（9 用例）：CONFIG_GROUPS 覆盖 DEFAULT_CONFIG 全部键且不重复、组名唯一、组顺序断言；`group_of`/`should_insert_header`/`matches`/`visible_keys`/`visible_groups` 边界（空 query、大小写、描述命中）。
- `tests/test_config_card_ui.py`（10 用例，offscreen QApplication）：真实 MapleFarmTask + ConfigCard 渲染——搜索框存在、9 组标题、过滤后键与组标题显隐、清空恢复、无分组任务无搜索框；**折叠**：初始全展开、点击折叠/再点展开、组间独立、折叠后标题仍可见、搜索覆盖折叠且清空恢复；grab() 渲染图存 `screenshots/e2e/config_groups/`。
- 全量回归：587 测试全绿（12 skip），全源码 py_compile 通过。
- E2E：offscreen 截图经视觉模型验收通过（9 组标题 + 顶部搜索框 + 过滤后跨组匹配 + 折叠后组标题保留/内容隐藏/▶▼ 箭头区分）；真实 GUI（提权启动）无崩溃。
- merge upstream a06acf9 后 CONFIG_GROUPS 纳入上游新增键（群攻怪数阈值/攻击前垫步开关→攻击组，丢锚唯一框接管开关→角色定位组），完整性测试保持绿色。

## Journey Log

- [lesson] DEFAULT_CONFIG 键序按历史开发累积、组交错——「渲染时插标题」会重复插同组标题，必须按分组重排渲染键序而非只插分隔。
- [lesson] 宽松匹配会命中描述里的任何词（如群攻描述含「坐椅」）——测试断言必须选无歧义关键词（「椅子」），这是匹配按设计的正确行为，不是 bug。
- [lesson] agent 受限窗口站无法截图提权 GUI（PyAutoGUI 全屏与 PrintWindow 均抓到空白）——交互类 E2E 用 offscreen QApplication 渲染 + grab 截图 + 视觉模型验收替代。
- [lesson] 上游 commit 删除 assets/（gitignore 模型文件）后 merge 会连带删掉本地运行时依赖 mob.onnx——merge 后必须检查并从 reference_repo 恢复。
- [lesson] 折叠与搜索都改 setVisible 时，必须让「组标题点击」与「搜索 textChanged」都走同一个过滤入口（`__apply_search_filter`），否则两套可见性状态会互相覆盖产生幽灵显隐。

## Source Materials

| File | Role | Notes |
|------|------|-------|
| `docs/compose/plans/2026-08-10-config-groups-search.md` | 实施计划 | 5 任务 TDD，全部完成 |
