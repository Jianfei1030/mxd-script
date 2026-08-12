# -*- coding: utf-8 -*-
"""build_release 纯函数:版本解析、PyInstaller 命令构建、默认配置清洗、前置校验。"""
import unittest

from scripts.build_release import (
    DEFAULT_ISCC_PATH,
    PROJECT_ROOT,
    build_pyinstaller_command,
    parse_version,
    sanitize_default_config,
    verify_prerequisites,
)


class TestParseVersion(unittest.TestCase):

    def test_reads_version_from_config_py(self):
        # config.py 顶部: version = "v0.1.0"
        self.assertEqual(parse_version(PROJECT_ROOT), "v0.1.0")

    def test_missing_version_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            parse_version("G:/no_such_dir_xyz")


class TestBuildPyinstallerCommand(unittest.TestCase):

    def test_command_shape(self):
        cmd = build_pyinstaller_command(PROJECT_ROOT, "v0.1.0")
        self.assertIn("--onedir", cmd)
        self.assertIn("--name", cmd)
        self.assertIn("OK-MXD", cmd)
        self.assertIn("--uac-admin", cmd)
        self.assertIn("--icon", cmd)
        self.assertIn("--collect-all", cmd)
        self.assertIn("onnxocr", cmd)
        self.assertIn("--hidden-import", cmd)
        # onnxocr 模型用分号分隔的 add-data(Windows PyInstaller 语法)
        self.assertTrue(any("onnxocr" in a and "models" in a and ";" in a for a in cmd))
        # 入口必须是 main.py(生产入口,无 --e2e)
        self.assertTrue(cmd[-1].endswith("main.py"))

    def test_dataincludes_onnxocr_models(self):
        cmd = build_pyinstaller_command(PROJECT_ROOT, "v0.1.0")
        self.assertTrue(any("onnxocr" in a and "models" in a for a in cmd))


class TestSanitizeDefaultConfig(unittest.TestCase):

    def test_strips_personal_fields(self):
        src = {
            "_enabled": True,
            "角色名": "端侧大模型",
            "决策日志开关": True,
            "攻击间隔(秒)": 1.0,
        }
        out = sanitize_default_config(src)
        self.assertIs(out["_enabled"], False)          # 默认不启用
        self.assertEqual(out["角色名"], "")             # 剥离角色名
        self.assertIs(out["决策日志开关"], False)        # 关决策日志
        self.assertEqual(out["攻击间隔(秒)"], 1.0)       # 非个人字段保留

    def test_returns_new_dict(self):
        src = {"角色名": "x"}
        out = sanitize_default_config(src)
        self.assertIsNot(src, out)
        self.assertNotEqual(src["角色名"], out["角色名"])


class TestVerifyPrerequisites(unittest.TestCase):

    def test_missing_mob_onnx_reports_error(self):
        # 故意指向不存在的模型路径
        ok, errors = verify_prerequisites(
            mob_onnx_path="G:/no_such_mob.onnx",
            iscc_path=DEFAULT_ISCC_PATH,
        )
        self.assertFalse(ok)
        self.assertTrue(any("mob.onnx" in e for e in errors))

    def test_iscc_missing_reports_error(self):
        ok, errors = verify_prerequisites(
            mob_onnx_path=None,  # 跳过模型检查
            iscc_path="G:/no_such_iscc.exe",
        )
        self.assertFalse(ok)
        self.assertTrue(any("ISCC" in e for e in errors))


if __name__ == '__main__':
    unittest.main()
