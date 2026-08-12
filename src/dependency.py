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
