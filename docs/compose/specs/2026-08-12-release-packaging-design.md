# [S1] Release 打包功能设计(Windows exe 安装程序)

> 日期:2026-08-12 · 状态:设计(待实现)
> 目标用户:拿到安装包双击安装、双击桌面图标即用的最终用户(Windows 平台,不需要 Python 环境)。

## [S2] 需求与约束

**需求**:一键构建 → 产出可分发的 `setup.exe` 安装程序,用户安装后双击图标直接启动 GUI,无需安装 Python、无需手动装依赖。

**硬约束(来自实机经验,不可妥协)**:

| # | 约束 | 来源 |
|---|---|---|
| C1 | **必须管理员运行**:PyDirect 发按键走 SendInput 驱动级,非管理员 error 5 一个键发不出去 | AGENTS.md §1.3 / GETTING_STARTED |
| C2 | **依赖极重**:PySide6 523MB + openvino 223MB + numpy 31MB + onnxocr 21MB(含 22MB 模型) + DirectML/OpenCV 等;解压后总量 ~1GB 级 | 本机实测 |
| C3 | **运行期要写可写目录**:`configs/`(用户配置)、`logs/`、`screenshots/`;且 GUI 启动会清空 screenshots | config.py / ok 框架 |
| C4 | **只读资源必须随包**:`assets/mob_model/mob.onnx`(12.7MB,gitignore)、`icons/`、onnxocr 的 models/ | src/globals.py:32 |
| C5 | 游戏窗口必须前台 + 2560x1440(非打包职责,仅启动前提醒) | GETTING_STARTED |
| C6 | `ok/`、`pyappify/` 是内联源码目录(非 pip 包),打包时必须以源码方式收集,不能指望 import 钩子 | requirements.txt 注释 |

**范围外(明确不做)**:自动更新链路(pyappify upgrade)、代码签名、多语言、绿色 zip 版、体积瘦身优化。

## [S3] 方案选型

**方案 A(选定):PyInstaller onedir + Inno Setup 安装程序**

- `pyinstaller --onedir`:目录形态,启动快,天然支持外置只读资源与可写目录;产物 `dist/OK-MXD/`
- Inno Setup 将 `dist/OK-MXD/` 打成 `setup.exe`,装到 Program Files,建桌面/开始菜单图标,预创建可写目录
- 理由:依赖含大量 .pyd/.dll/.onnx(动态收集难),onedir 把收集问题降到"目录拷贝"级别;安装器解决可写目录、快捷方式、提权提示

**方案 B(否决):PyInstaller onefile**:启动时解压到临时目录(每启动 5-10s 延迟),且可写目录落在临时目录生命周期外,配置丢失风险高。

**方案 C(否决):嵌入式 Python + pyappify 更新器**:pyappify 的升级链路需 app.json/签名/更新服务器,超出 v1 范围;静态安装用 Inno 更直接。

## [S4] 架构与组成

```
dist/OK-MXD/                      ← PyInstaller 产物
├── OK-MXD.exe                    ← 主程序(manifest 提权)
├── _internal/                    ← PyInstaller 收集的依赖(python312.dll、全部 .pyd/.dll、site-packages)
│   ├── ok/  src/  config.py      ← 业务代码(源码收集)
│   ├── onnxocr/models/...        ← OCR 模型(22MB,datas 收集)
│   └── ...
├── assets/mob_model/mob.onnx     ← 检测模型(12.7MB,datas 收集,保持相对结构)
├── icons/icon.ico                ← 图标
├── configs/                      ← 安装器预建(用户配置,可写)
├── logs/                         ← 安装器预建(可写)
├── screenshots/                  ← 安装器预建(可写)
└── 卸载数据由 Inno 管理
```

**可写目录策略**:`configs/`/`logs/`/`screenshots/` 由 Inno 安装器创建在 exe 同级,并授予当前用户写权限(安装器本身提权运行,Program Files 默认仅管理员可写,必须显式改 ACL——见 [S6] 风险 R3)。

**路径解析**:ok 框架 `get_path_relative_to_exe`(ok/util/file.py:38)在 `sys.frozen=True` 时以 `sys.executable` 目录为基准解析资源,已满足 onedir 布局;**业务代码禁止引入新绝对路径**(AGENTS.md §11.1),一律经该函数。

## [S5] 提权方案

- `OK-MXD.exe` 通过 PyInstaller `--uac-admin` 声明 `requireAdministrator` manifest:双击直接弹 UAC,无需外层启动器
- Inno Setup 的 `PrivilegesRequired=admin` 保证安装器提权运行
- 用户从桌面快捷方式启动即提权,行为与现有 `elevated_launch.cmd` 一致(该 cmd 仅开发机用,不随包分发)

## [S6] 关键技术点与风险

| # | 风险/关键点 | 对策 |
|---|---|---|
| R1 | onnxocr 模型路径:包内 `models/ppocrv5/{det,rec,cls}.onnx` 由 `ONNXPaddleOcr` 相对模块定位 | PyInstaller datas 收集 `onnxocr/models` 保持目录结构;打包后冒烟测 OCR 读名字牌 |
| R2 | OpenVINO `use_openvino=True` + onnxruntime-directml(新加「推理加速」开关)双后端 | 两库都显式 hidden-import;冒烟测 CPU 检测 + GPU 勾选 |
| R3 | Program Files 写权限:安装器建目录但运行期是管理员进程,写 exe 同级目录 | 安装器 `Permissions: users-modify` 显式 ACL,保证即使降权也能写 |
| R4 | PySide6 插件(direct 平台插件、qfluentwidgets 资源)漏收集 | `--collect-all PySide6` 级收集或 `collect_all("PySide6")`,冒烟测 GUI 能弹出 |
| R5 | `configs/` 首次启动空目录,任务默认配置缺失 | Inno 预置一份默认 `configs/*.json`(从仓库 `docs/configs/` 副本拷,不含角色名等个人数据) |
| R6 | 打包机缺 `screenshots/test_frames` 存档帧会致 tests 红 | 打包不跑 tests;冒烟单测仅跑纯逻辑模块 |
| R7 | `mob.onnx` 在 .gitignore,CI/换机打包拿不到 | 打包脚本显式校验 `assets/mob_model/mob.onnx` 存在,缺失即报错;从有模型的机器拷 |
| R8 | 杀软误报:PyInstaller 壳 + SendInput 驱动操作 | 无解,接受;README 注明仅供学习用途 |

## [S7] 打包产物与脚本

新增 `scripts/build_release.py`(唯一入口,幂等):

```
python scripts/build_release.py          # 默认:pyinstaller + inno,产出 setup.exe
python scripts/build_release.py --no-inno   # 只出 dist/OK-MXD/ 目录(自测用)
```

流程:
1. 前置校验:mob.onnx 存在、python 3.12、`pyinstaller`/`innosetup` 可用
2. PyInstaller onedir 打包(入口 `main.py`,datas:assets/、icons/、onnxocr/models;hidden:OpenVINO、directml;`--uac-admin`;版本号取 config.py)
3. 复制预置默认配置 `docs/configs/端侧大模型_战士_MapleFarmTask.json → dist/OK-MXD/configs/MapleFarmTask.json`(清理角色名等个人字段)
4. 冒烟验证(两步,均可离线):先跑最小 import 探针(子进程 `python -c "import src.globals"` 指向 dist 内 `_internal`);再直接启动 `dist/OK-MXD/OK-MXD.exe`,等 3 秒查进程存活、无 stderr 崩溃日志(GUI 拉起不崩即过,有屏时人工确认窗口弹出)
5. Inno Setup 编译 `scripts/installer.iss` → `dist/OK-MXD-setup-<version>.exe`

Inno 脚本要点:`PrivilegesRequired=admin`、`DefaultDirName={autopf}\OK-MXD`、桌面+开始菜单图标、`[Dirs]` 建 configs/logs/screenshots 并 `Permissions: users-modify`、卸载删整个目录。

## [S8] 验收标准

1. **构建**:`build_release.py` 在干净目录重复执行两次,产出 setup.exe 且幂等
2. **安装**:在**无 Python 的机器/虚拟机**安装 setup.exe,桌面图标出现
3. **启动**:双击图标弹 UAC,提权后 GUI 正常弹出(标题 OK-MXD,无 ModuleNotFoundError)
4. **核心链路**:GUI 内「推理加速」两种后端都能加载模型(YOLO 检测不报错);OCR 名字牌能识别(读 `screenshots/test_frames` 存档帧验证,若打包机无此帧则此条降级为 OCR 模型加载探针)
5. **可写**:挂机配置能保存(写 configs/MapleFarmTask.json),日志写入 logs/
6. **卸载**:卸载后 exe 目录、桌面图标、开始菜单全部清除

## [S9] 测试策略

- **单元测试**(随代码):`tests/test_build_release.py` 覆盖打包脚本的纯逻辑——版本号解析、默认配置清洗(角色名剥离)、路径校验(mob.onnx 缺失报错)不真正执行 pyinstaller
- **构建级验证**(脚本内):打包后 `--e2e` 探针 + 最小 import 冒烟(离线可跑)
- **E2E 验收**(实机):按 [S8] 在干净虚拟机走安装→启动→保存配置→卸载全流程,截图留证(`screenshots/e2e/release/`)
