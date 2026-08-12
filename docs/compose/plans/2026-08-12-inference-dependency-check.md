# 推理加速依赖检查与一键安装 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在「推理加速」tab 内显示 openvino / onnxruntime 依赖状态,缺失时可一键安装(国内镜像优先,自动切换)。

**Architecture:** 纯逻辑放 `src/dependency.py`(find_spec 检测 + sys.executable pip 安装 + 镜像自动切换);UI 用自定义控件 `LabelAndDependencyCheck`(ok/gui/tasks/,沿用 LabelAndBuffList 先例)经 config_type 机制挂进 GlobalConfigTab;安装跑 daemon 线程 + Qt Signal 回主线程,不阻塞 GUI。

**Tech Stack:** Python 3.12 / PySide6 / qfluentwidgets / unittest(mock) / offscreen Qt 渲染测试

**Spec:** `docs/compose/specs/2026-08-12-inference-dependency-check-design.md`([S1]-[S8])

**Environment:** Python 解释器 `C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe`(AGENTS.md §1.1)。所有命令在该机器 PowerShell 下执行。禁止硬编码项目绝对路径(§11.1)。

---

### Task 1: src/dependency.py 纯逻辑 + 单测

**Covers:** [S3, S4, S6]

**Files:**
- Create: `src/dependency.py`
- Test: `tests/test_dependency.py`

- [ ] **Step 1: 写失败测试** `tests/test_dependency.py`

```python
import sys
import unittest
from unittest import mock

import src.dependency as dep_mod
from src.dependency import (
    DEPENDENCIES, MIRRORS, build_install_cmd, check_dependencies,
    install_missing, missing_dependencies,
)


class TestCheckDependencies(unittest.TestCase):

    def test_all_installed(self):
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            result = check_dependencies()
        self.assertEqual(len(result), 2)
        self.assertTrue(all(d['installed'] for d in result))

    def test_partial_missing(self):
        with mock.patch.object(dep_mod, '_installed', side_effect=lambda m: m == 'openvino'):
            result = check_dependencies()
        self.assertTrue(result[0]['installed'])
        self.assertFalse(result[1]['installed'])

    def test_all_missing(self):
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            self.assertEqual(len(missing_dependencies()), 2)

    def test_missing_only_uninstalled(self):
        with mock.patch.object(dep_mod, '_installed', side_effect=lambda m: m == 'onnxruntime'):
            missing = missing_dependencies()
        self.assertEqual([d['name'] for d in missing], ['openvino'])

    def test_entries_pin_versions_from_requirements(self):
        by_name = {d['name']: d for d in DEPENDENCIES}
        self.assertEqual(by_name['openvino']['version'], '2026.2.1')
        self.assertEqual(by_name['onnxruntime']['pip'], 'onnxruntime-directml')
        self.assertEqual(by_name['onnxruntime']['version'], '1.24.4')
        self.assertTrue(by_name['openvino']['required'])
        self.assertFalse(by_name['onnxruntime']['required'])


class TestBuildInstallCmd(unittest.TestCase):

    def test_with_mirror(self):
        cmd = build_install_cmd([DEPENDENCIES[0]], 'https://mirror.example/simple')
        self.assertEqual(cmd[:2], [sys.executable, '-m'])
        self.assertEqual(cmd[2:4], ['pip', 'install'])
        self.assertIn('openvino==2026.2.1', cmd)
        self.assertEqual(cmd[-2:], ['-i', 'https://mirror.example/simple'])

    def test_without_mirror_uses_official(self):
        cmd = build_install_cmd(DEPENDENCIES, None)
        self.assertNotIn('-i', cmd)
        self.assertIn('onnxruntime-directml==1.24.4', cmd)


class TestInstallMissing(unittest.TestCase):

    def test_no_missing_is_noop(self):
        with mock.patch.object(dep_mod, 'missing_dependencies', return_value=[]):
            ok, detail = install_missing()
        self.assertTrue(ok)

    def test_tries_mirrors_in_order_until_success(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            mirror = cmd[cmd.index('-i') + 1] if '-i' in cmd else None
            if mirror == MIRRORS[1]:
                return mock.Mock(returncode=0, stderr='')
            return mock.Mock(returncode=1, stderr='boom')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertTrue(ok)
        self.assertEqual(detail, MIRRORS[1])
        self.assertEqual(len(calls), 2, '第二个镜像成功后应立即停止,不应继续尝试')

    def test_all_fail_returns_last_error(self):
        def fake_run(cmd, **kwargs):
            tag = cmd[cmd.index('-i') + 1] if '-i' in cmd else 'official'
            return mock.Mock(returncode=1, stderr=f'fail-{tag}')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertFalse(ok)
        self.assertIn('fail-official', detail, '应返回最后一个(官方源)错误')

    def test_exception_keeps_trying_next_mirror(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if len(calls) == 1:
                raise TimeoutError('too slow')
            return mock.Mock(returncode=0, stderr='')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)

    def test_exception_all_mirrors_returns_error(self):
        def fake_run(cmd, **kwargs):
            raise TimeoutError('too slow')

        with mock.patch('subprocess.run', side_effect=fake_run):
            ok, detail = install_missing([DEPENDENCIES[0]])
        self.assertFalse(ok)
        self.assertIn('too slow', detail)

    def test_mirror_order_tuna_first(self):
        self.assertEqual(MIRRORS[0], 'https://pypi.tuna.tsinghua.edu.cn/simple')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_dependency -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.dependency'`

- [ ] **Step 3: 写最小实现** `src/dependency.py`

```python
import importlib.util
import subprocess
import sys

from ok import Logger

logger = Logger.get_logger(__name__)

# 与 requirements.txt 版本 pin 保持一致(AGENTS.md §11 铁律:改了版本必须同步改这里)
DEPENDENCIES = [
    {'name': 'openvino', 'pip': 'openvino', 'version': '2026.2.1',
     'required': True, 'desc': 'CPU 推理(OpenVINO)'},
    {'name': 'onnxruntime', 'pip': 'onnxruntime-directml', 'version': '1.24.4',
     'required': False, 'desc': 'GPU 推理(DirectML)'},
]

# 国内镜像优先(用户可能无科学上网环境);官方 PyPI 兜底(None 表示不加 -i)
MIRRORS = [
    'https://pypi.tuna.tsinghua.edu.cn/simple',
    'https://mirrors.aliyun.com/pypi/simple/',
    'https://mirrors.cloud.tencent.com/pypi/simple',
]


def _installed(module_name):
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def check_dependencies():
    result = []
    for dep in DEPENDENCIES:
        item = dict(dep)
        item['installed'] = _installed(dep['name'])
        result.append(item)
    return result


def missing_dependencies():
    return [dep for dep in check_dependencies() if not dep['installed']]


def build_install_cmd(pkgs, mirror):
    cmd = [sys.executable, '-m', 'pip', 'install'] + [f'{p["pip"]}=={p["version"]}' for p in pkgs]
    if mirror:
        cmd += ['-i', mirror]
    return cmd


def install_missing(missing=None, timeout=600):
    """依次尝试各镜像安装缺失依赖,首个成功即止。返回 (成功?, 镜像名或最后错误)。"""
    if missing is None:
        missing = missing_dependencies()
    if not missing:
        return True, '无缺失依赖'
    last_error = ''
    for mirror in MIRRORS + [None]:
        cmd = build_install_cmd(missing, mirror)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=timeout)
            if proc.returncode == 0:
                logger.info(f'pip install 成功 (mirror={mirror or "官方源"}): {" ".join(cmd)}')
                return True, mirror or '官方源'
            last_error = proc.stderr.strip()[-500:]
        except Exception as e:
            last_error = str(e)
    logger.error(f'pip install 全部镜像失败: {last_error}')
    return False, last_error
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_dependency -v`
Expected: 13 tests PASS

- [ ] **Step 5: 提交**

```bash
git add src/dependency.py tests/test_dependency.py
git commit -m "feat: 推理加速依赖检查纯逻辑(openvino/onnxruntime + 国内镜像安装)"
```

---

### Task 2: LabelAndDependencyCheck 控件 + 挂载 + offscreen UI 测试

**Covers:** [S5, S7]

**Files:**
- Create: `ok/gui/tasks/LabelAndDependencyCheck.py`
- Create: `tests/test_dependency_ui.py`
- Modify: `ok/gui/tasks/ConfigItemFactory.py`(加 import + `config_widget` 分支,见 Step 3)
- Modify: `ok/gui/tasks/ConfigCard.py`(`__is_button_config` 放行,见 Step 3)
- Modify: `config.py`(`inference_config_option` 加 config_type,见 Step 3)

- [ ] **Step 1: 写失败测试** `tests/test_dependency_ui.py`(offscreen, 仿 `tests/test_config_card_ui.py` 头部)

```python
# tests/test_dependency_ui.py
"""LabelAndDependencyCheck offscreen 渲染测试(不依赖真实 GUI/窗口站,§11.3 自动化兜底)。"""
import os
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication

from ok import og


class _FakeApp:
    """代替 og.app,只提供 tr()(LabelAndWidget 渲染链只用到它)。"""

    def tr(self, message):
        return message


class DependencyCheckUiTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        og.app = _FakeApp()
        og.config = {}

    def _make(self):
        from ok.gui.tasks.LabelAndDependencyCheck import LabelAndDependencyCheck
        return LabelAndDependencyCheck({}, {}, '依赖状态')

    def test_shows_installed_and_missing_text(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', side_effect=lambda m: m == 'openvino'):
            widget = self._make()
        text = widget.status_label.text()
        self.assertIn('✓ 已安装', text)
        self.assertIn('✗ 未安装', text)
        self.assertIn('OpenVINO', text)

    def test_install_button_enabled_only_when_missing(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            widget = self._make()
        self.assertFalse(widget.install_button.isEnabled(), '全齐时安装按钮应禁用')
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget.refresh()
        self.assertTrue(widget.install_button.isEnabled(), '有缺失时安装按钮应可用')

    def test_refresh_updates_status(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            widget = self._make()
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget.refresh()
        self.assertNotIn('✓ 已安装', widget.status_label.text())
        self.assertIn('✗ 未安装', widget.status_label.text())

    def test_install_done_success_resets_and_alerts(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        with mock.patch.object(dep_mod, '_installed', return_value=True), \
                mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_info') as info, \
                mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_error') as err:
            widget._on_install_done(True, '清华')
        self.assertFalse(widget._installing)
        self.assertFalse(widget.install_button.isEnabled(), '装完后状态刷新为全齐 → 按钮禁用')
        self.assertEqual(widget.install_button.text(), '安装缺失依赖')
        info.assert_called_once()
        err.assert_not_called()
        self.assertIn('重启后生效', info.call_args[0][0])

    def test_install_done_failure_reports_error(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        with mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_info') as info, \
                mock.patch('ok.gui.tasks.LabelAndDependencyCheck.alert_error') as err:
            widget._on_install_done(False, 'connection refused')
        self.assertFalse(widget._installing)
        err.assert_called_once()
        self.assertIn('connection refused', err.call_args[0][0])
        info.assert_not_called()

    def test_start_install_noop_when_nothing_missing(self):
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=True):
            widget = self._make()
        with mock.patch.object(dep_mod, 'install_missing') as install:
            widget._start_install()
        install.assert_not_called()
        self.assertFalse(widget._installing)

    def test_start_install_runs_worker_thread(self):
        import src.dependency as dep_mod
        import ok.gui.tasks.LabelAndDependencyCheck as widget_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        with mock.patch.object(dep_mod, 'install_missing', return_value=(True, 'mirror')) as install, \
                mock.patch.object(widget_mod.threading, 'Thread') as thread:
            widget._start_install()
        install.assert_called_once()
        thread.assert_called_once()
        self.assertTrue(widget._installing)
        self.assertFalse(widget.install_button.isEnabled())

    def test_grab_render_screenshot(self):
        # §11.3 E2E 截图留证:渲染图存 screenshots/e2e/inference_dependency/
        import src.dependency as dep_mod
        with mock.patch.object(dep_mod, '_installed', return_value=False):
            widget = self._make()
        widget.resize(640, 160)
        out_dir = os.path.join('screenshots', 'e2e', 'inference_dependency')
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, 'dependency_check.png')
        widget.grab().save(path)
        self.assertTrue(os.path.exists(path), f'渲染图应已保存: {path}')


if __name__ == '__main__':
    unittest.main()
```

注意:`_start_install` 里 `threading.Thread(...).start()` 被 mock 后不真起线程,所以测试安全;`_installing=True` 后按钮禁用。`test_start_install_runs_worker_thread` 断言线程被创建。

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_dependency_ui -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ok.gui.tasks.LabelAndDependencyCheck'`

- [ ] **Step 3: 写实现**

**3a. 新建 `ok/gui/tasks/LabelAndDependencyCheck.py`:**

```python
import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import PushButton

from ok import Logger, og
from ok.gui.tasks.LabelAndWidget import LabelAndWidget
from ok.gui.util.Alert import alert_error, alert_info
from src.dependency import check_dependencies, install_missing, missing_dependencies

logger = Logger.get_logger(__name__)


class LabelAndDependencyCheck(LabelAndWidget):
    """「推理加速」依赖状态 + 一键安装(国内镜像优先,失败自动切换)。"""

    install_done = Signal(bool, str)

    def __init__(self, config_desc, config, key):
        super().__init__(og.app.tr(key), og.app.tr('推理加速所需依赖检查'))
        self._installing = False

        self.status_label = QLabel()
        self.status_label.setObjectName('contentLabel')
        self.status_label.setWordWrap(True)

        self.check_button = PushButton(og.app.tr('重新检测'))
        self.install_button = PushButton(og.app.tr('安装缺失依赖'))
        self.check_button.clicked.connect(self.refresh)
        self.install_button.clicked.connect(self._start_install)
        self.install_done.connect(self._on_install_done)

        right = QVBoxLayout()
        right.addWidget(self.status_label)
        buttons = QHBoxLayout()
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.install_button)
        right.addLayout(buttons)
        self.add_layout(right)

        self.refresh()

    def refresh(self):
        deps = check_dependencies()
        lines = [f"{d['desc']} {'✓ 已安装' if d['installed'] else '✗ 未安装'}" for d in deps]
        self.status_label.setText('\n'.join(lines))
        self.install_button.setEnabled(bool(missing_dependencies()) and not self._installing)

    def _start_install(self):
        if self._installing:
            return
        missing = missing_dependencies()
        if not missing:
            return
        self._installing = True
        self.install_button.setEnabled(False)
        self.install_button.setText(og.app.tr('正在安装…'))
        threading.Thread(target=self._install_worker, args=(missing,), daemon=True).start()

    def _install_worker(self, missing):
        ok, detail = install_missing(missing)
        self.install_done.emit(ok, detail)

    def _on_install_done(self, ok, detail):
        self._installing = False
        self.install_button.setText(og.app.tr('安装缺失依赖'))
        self.refresh()
        if ok:
            alert_info(og.app.tr(f'依赖安装完成({detail}),重启后生效'))
        else:
            alert_error(og.app.tr(f'依赖安装失败: {detail}'))
```

**3b. `ok/gui/tasks/ConfigItemFactory.py` 挂载**(import 区第 11 行后加一行,`config_widget` 中 `elif resolved_type == 'buff_list':` 之后加分支):

```python
from ok.gui.tasks.LabelAndDependencyCheck import LabelAndDependencyCheck
# ...
        elif resolved_type == 'dependency_check':
            return LabelAndDependencyCheck(config_desc, config, key)
```

**3c. `ok/gui/tasks/ConfigCard.py` `__is_button_config` 放行新类型**(第 267-274 行):

```python
    def __is_button_config(self, the_type):
        return (
            isinstance(the_type, dict)
            and (
                the_type.get('type') in ('button', 'dependency_check')
                or ('type' not in the_type and ('buttons' in the_type or 'callback' in the_type))
            )
        )
```

**3d. `config.py` `inference_config_option` 加 config_type**(第 29-33 行):

```python
inference_config_option = ConfigOption('推理加速', {
    '启用GPU推理': False,
}, description='YOLO 推理后端:默认 CPU(OpenVINO,兼容性最好);勾选后优先使用本机最强推理硬件(DirectML GPU,失败自动回退 CPU)', config_description={
    '启用GPU推理': '勾选后 YOLO 检测走 DirectML GPU(本机 RTX 4060 等),失败自动回退 CPU;不勾选始终用 CPU。默认不勾选以保兼容性',
}, config_type={
    '依赖状态': {'type': 'dependency_check'},
}, show_at_tab=True, icon=FluentIcon.SPEED_HIGH)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_dependency_ui tests.test_config_card_ui -v`
Expected: 全部 PASS(offscreen,无真实 GUI)

- [ ] **Step 5: 提交**

```bash
git add ok/gui/tasks/LabelAndDependencyCheck.py tests/test_dependency_ui.py ok/gui/tasks/ConfigItemFactory.py ok/gui/tasks/ConfigCard.py config.py
git commit -m "feat: 推理加速 tab 依赖状态控件 + 一键安装(国内镜像)"
```

---

### Task 3: 全量验证 + 截图证据

**Covers:** [S7]

**Files:**
- 截图产物: `screenshots/e2e/inference_dependency/dependency_check.png`(Task 2 测试已生成)

- [ ] **Step 1: 全量单测**(AGENTS.md §11.6 全命令)

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_bars tests.test_guards tests.test_anchor_offline tests.test_potions tests.test_anchor tests.test_ocr_engine tests.test_analyze_anchor tests.test_analyze_facing tests.test_analyze_seek tests.test_analyze_turn tests.test_facing tests.test_label_boxes tests.test_yolo tests.test_config_groups tests.test_config_card_ui tests.test_dependency tests.test_dependency_ui
```
Expected: 全部 PASS(既有红 `test_anchor_offline.TestAnchorOnRealFrames.test_b_anchor_y_in_expected_band` 除外,属 §11.7 已知基线)

- [ ] **Step 2: 全源码编译检查**

Run:
```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: 校验截图产物存在**

Run: `Get-ChildItem screenshots\e2e\inference_dependency`
Expected: `dependency_check.png` 存在(Task 2 Step 1 测试自动生成)

- [ ] **Step 4: 视觉验收截图**(可选,若本机有 vision 模型)

用 vision-capable 模型(`actor models --vision`)检查 `screenshots/e2e/inference_dependency/dependency_check.png`:
- 应含两行依赖状态(OpenVINO / onnxruntime),各有 ✓/✗
- 应有「重新检测」「安装缺失依赖」两个按钮,安装按钮可用(测试模拟全缺失)
验收结论写入 AGENTS.md 对应特性记录或本计划提交信息。

- [ ] **Step 5: 提交**

```bash
git add screenshots/e2e/inference_dependency
git commit -m "test: 推理加速依赖检查 offscreen 渲染截图证据"
```

---

## 自审记录

- **Spec 覆盖**: S3/S4 → Task 1;S5/S7 → Task 2;S6 → Task 1(install_missing);S7 → Task 2/3;S1/S2/S8 → 无行为要求(Problem/概述/范围外),无需任务。
- **类型一致性**: `install_missing(missing=None, timeout=600)` 返回 `(bool, str)`;`build_install_cmd(pkgs, mirror)` 接受 list;`LabelAndDependencyCheck(config_desc, config, key)` 与 ConfigItemFactory 调用 `LabelAndDependencyCheck(config_desc, config, key)` 一致;控件暴露 `status_label` / `install_button` / `check_button` / `_installing`,测试引用一致。
- **占位符扫描**: 无 TBD/TODO,所有代码步骤含完整代码。
