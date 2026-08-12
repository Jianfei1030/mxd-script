# 推理加速依赖检查与一键安装 — 设计文档

- 日期: 2026-08-12
- 状态: 已批准(用户评审通过)
- 关联: config.py `inference_config_option` / src/OpenVinoYolo8Detect.py 后端选择

## [S1] Problem

「推理加速」(全局配置, `config.py:29`) 勾选「启用GPU推理」后走 DirectML,否则走 OpenVINO CPU。
当前行为:

- **无依赖检查 UI**: 用户无法在界面上得知 openvino / onnxruntime 是否已安装。
- **无自动安装**: 缺 `onnxruntime` 时仅在日志打 warning 并回退 CPU(`OpenVinoYolo8Detect._try_init_dml`),
  缺 `openvino` 时模块顶层 `from openvino import Core` 直接 ModuleNotFoundError 崩溃。
- 依赖安装只能靠用户手动 `pip install -r requirements.txt`,换机器/装机后体验差。

目标: 在「推理加速」tab 内显示依赖状态;缺失时可一键安装,安装源优先国内镜像
(用户可能无科学上网环境)。

## [S2] Solution overview

- **依赖检查纯逻辑** 放 `src/dependency.py`(可离线单测, 遵循 AGENTS.md §11 纯逻辑可测铁律)。
- **UI 控件** `ok/gui/tasks/LabelAndDependencyCheck.py`, 通过 `config_type` 机制挂进
  「推理加速」`GlobalConfigTab`(沿用 `LabelAndBuffList` 自定义控件先例)。
- **安装** 用当前解释器 `sys.executable -m pip install`, 镜像列表 清华→阿里云→腾讯云→官方 PyPI
  依次尝试,首个成功即止; 安装跑在 QThread 避免阻塞 GUI。
- 安装完成后 InfoBar 提示「重启后生效」(GPU 推理会话在首次 detect 时创建,装后需重启才启用 GPU)。

## [S3] Dependencies to check

仅两项(推理加速相关):

| import 模块 | pip 包 | 版本 pin | required | 说明 |
|---|---|---|---|---|
| `openvino` | `openvino` | 2026.2.1 | 是 | CPU 推理(OpenVINO),缺了推理直接崩 |
| `onnxruntime` | `onnxruntime-directml` | 1.24.4 | 否 | GPU 推理(DirectML),缺了自动回退 CPU 仅失去加速 |

- 检测方式: `importlib.util.find_spec(模块名)` 存在性检查。
- 版本不做运行时校验(安装按钮用 pin 保证版本; 手动装错版本属用户行为,不属本功能职责)。

## [S4] Pure logic — src/dependency.py

```python
DEPENDENCIES = [
    {'name': 'openvino', 'pip': 'openvino', 'version': '2026.2.1',
     'required': True, 'desc': 'CPU 推理(OpenVINO)'},
    {'name': 'onnxruntime', 'pip': 'onnxruntime-directml', 'version': '1.24.4',
     'required': False, 'desc': 'GPU 推理(DirectML)'},
]
MIRRORS = [
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple/',
    'https://mirrors.cloud.tencent.com/pypi/simple',
]

def check_dependencies() -> list[dict]:
    # 每项附 installed: bool(find_spec)
def missing_dependencies() -> list[dict]:
    # 过滤 installed=False
def build_install_cmd(pkgs: list[dict], mirror: str | None) -> list[str]:
    # [sys.executable, '-m', 'pip', 'install'] + [f'{p["pip"]}=={p["version"]}' for p in pkgs]
    # + (['-i', mirror] if mirror)
def install_missing(missing) -> (ok: bool, detail: str):
    # 对 MIRRORS + [None](官方源) 依次 subprocess.run(capture_output, timeout=600)
    # 首个 rc==0 返回 (True, mirror); 全失败返回 (False, 最后一条 stderr)
```

- 禁止硬编码绝对路径(AGENTS.md §11.1), 项目根由脚本推导, `sys.executable` 来自运行时。

## [S5] UI widget — ok/gui/tasks/LabelAndDependencyCheck.py

「推理加速」tab 内开关下方新增「依赖状态」区(LabelAndWidget 行,与现有控件风格一致):

- 每依赖一行状态文本: `{desc} ✓ 已安装` / `{desc} ✗ 未安装`
- 按钮:
  - 「重新检测」— 常驻,点击重跑 `check_dependencies()` 刷新状态
  - 「安装缺失依赖」— 仅 `missing_dependencies()` 非空时可用;点击后禁用按钮、
    文本变「正在安装…」,QThread 跑 `install_missing`;完成回主线程刷新状态 +
    InfoBar(success: 「安装完成,重启后生效」/ error: 最后一条错误)
- 构造时主动执行一次检测(首次进 tab 即看到状态)

### 挂载方式

- `config.py` `inference_config_option` 加:
  ```python
  config_type={
      '依赖状态': {'type': 'dependency_check'},
  }
  ```
  (键不在 default_config 中 → 不落盘,ConfigCard 靠 `__is_button_config` 放行渲染)
- `ok/gui/tasks/ConfigItemFactory.py` `config_widget` 加分支:
  `elif resolved_type == 'dependency_check': return LabelAndDependencyCheck(config_desc, config, key)`
  (`_resolve_type` 已能透传 `type='dependency_check'`)
- `ok/gui/tasks/ConfigCard.py` `__is_button_config` 放行新类型:
  `the_type.get('type') in ('button', 'dependency_check')`

## [S6] Install flow

- 命令: `sys.executable -m pip install openvino==2026.2.1 onnxruntime-directml==1.24.4 -i <mirror>`
  (仅安装缺失项,一次装全部缺失项)
- 镜像顺序: 清华 TUNA → 阿里云 → 腾讯云 → 官方 PyPI(最后一个为 None 表示官方源)
- 超时 600s; 输出捕获不刷屏; 全失败时 InfoBar 展示最后一条错误(stderr 截断)
- QThread 封装在控件模块内(Worker + signal), 不阻塞 GUI 线程

## [S7] Tests(AGENTS.md §11 铁律)

- `tests/test_dependency.py`(离线):
  - check_dependencies: mock find_spec 全有/全无/部分 → installed 字段正确
  - missing_dependencies: 只返回未安装项
  - build_install_cmd: 带/不带镜像的参数构造,版本 pin 正确
  - install_missing: mock subprocess.run 依次失败→成功,断言镜像切换顺序与首个成功即止;
    全失败返回 (False, 错误详情); 超时/异常兜底
  - MIRRORS 顺序断言(清华在前)
- `tests/test_dependency_ui.py`(offscreen, 仿 test_config_card_ui):
  - 控件渲染: 状态文本含 ✓/✗、两按钮存在
  - 缺依赖时「安装缺失依赖」可用; 全齐时禁用
  - 点击安装触发 install 流程并刷新状态(QThread 用同步桩替代)
  - grab 渲染图存 `screenshots/e2e/inference_dependency/`
- 全量单测 + 全源码编译检查必须绿(命令见 AGENTS.md §11.6)
- E2E: agent 受限窗口站无法截提权 GUI,按 §12 先例走 offscreen grab + 断言验收

## [S8] Out of scope

- 不检查 GPU 驱动/DirectX12 可用性(运行时已有自动回退 CPU 兜底)
- 不检查其他项目依赖(onnxocr 等)——本功能只服务「推理加速」
- 不自动安装(不点按钮不装), 不做版本升级/降级
- 不改 OpenVinoYolo8Detect 后端选择逻辑
