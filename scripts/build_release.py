# -*- coding: utf-8 -*-
"""release 打包编排。用法:
    python scripts/build_release.py            # pyinstaller + inno,产出 setup.exe
    python scripts/build_release.py --no-inno  # 只出 dist/OK-MXD/ 目录
纯函数集中在文件上部,主流程在 main()(Task 4 补全)。
"""
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_ISCC_CANDIDATES = [
    r"C:\Users\jianfei\AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]
DEFAULT_ISCC_PATH = next((p for p in DEFAULT_ISCC_CANDIDATES if os.path.exists(p)), "")

MOB_ONNX_REL = os.path.join("assets", "mob_model", "mob.onnx")
CONFIG_SRC_REL = os.path.join("docs", "configs", "端侧大模型_战士_MapleFarmTask.json")
DIST_NAME = "OK-MXD"
PYTHON = sys.executable


def parse_version(project_root):
    """从 config.py 提取 version = "vX.Y.Z"。"""
    config_py = os.path.join(project_root, "config.py")
    with open(config_py, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'version\s*=\s*"([^"]+)"', text)
    if not m:
        raise ValueError(f"config.py 找不到 version = \"...\": {config_py}")
    return m.group(1)


def _data_pair(src_rel, dst_rel):
    """PyInstaller --add-data 条目(Windows 分号分隔)。"""
    src = os.path.join(PROJECT_ROOT, src_rel)
    return f"{src};{dst_rel}"


def build_pyinstaller_command(project_root, version, dist_dir=None, work_dir=None):
    """拼 PyInstaller onedir 命令(列表形式,可直接 subprocess)。"""
    dist_dir = dist_dir or os.path.join(project_root, "dist")
    work_dir = work_dir or os.path.join(project_root, "build")
    entry = os.path.join(project_root, "main.py")
    icon = os.path.join(project_root, "icons", "icon.ico")
    return [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name", DIST_NAME,
        "--uac-admin",
        "--icon", icon,
        "--distpath", dist_dir,
        "--workpath", work_dir,
        "--add-data", _data_pair("assets", "assets"),
        "--add-data", _data_pair("icons", "icons"),
        "--add-data", _data_pair(os.path.join("onnxocr", "models"),
                                 os.path.join("onnxocr", "models")),   # 22MB OCR 模型保持目录结构
        "--collect-all", "onnxocr",
        "--hidden-import", "openvino",
        "--hidden-import", "onnxruntime",
        "--hidden-import", "onnxruntime.capi._pybind_state",
        "--collect-all", "qfluentwidgets",
        entry,
    ]


def sanitize_default_config(src):
    """清洗参考配置为随包默认:不启用、剥离角色名、关决策日志;其余字段保留。"""
    out = dict(src)
    out["_enabled"] = False
    out["角色名"] = ""
    out["决策日志开关"] = False
    return out


def verify_prerequisites(mob_onnx_path=None, iscc_path=None):
    """前置校验,返回 (ok, errors)。传 None 跳过对应项。"""
    errors = []
    if mob_onnx_path is not None and not os.path.exists(mob_onnx_path):
        errors.append(f"缺少检测模型 {mob_onnx_path}(.gitignore 不入库,需从有模型的机器拷贝)")
    if iscc_path is not None and not iscc_path:
        errors.append("未找到 ISCC.exe(Inno Setup 6),安装或在 DEFAULT_ISCC_CANDIDATES 补路径")
    if iscc_path is not None and iscc_path and not os.path.exists(iscc_path):
        errors.append(f"ISCC.exe 不存在: {iscc_path}")
    return (len(errors) == 0, errors)


def _run(cmd, cwd=None):
    print(">>", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def main():
    args = sys.argv[1:]
    no_inno = "--no-inno" in args
    version = parse_version(PROJECT_ROOT)
    mob_onnx = os.path.join(PROJECT_ROOT, MOB_ONNX_REL)
    iscc = "" if no_inno else DEFAULT_ISCC_PATH
    ok, errors = verify_prerequisites(mob_onnx, iscc)
    if not ok:
        for e in errors:
            print("[前置校验失败]", e)
        sys.exit(1)
    print(f"打包版本: {version}  (no_inno={no_inno})")
    # Task 4 补全: pyinstaller 执行、默认配置注入、冒烟探针、ISCC 编译


if __name__ == "__main__":
    main()
