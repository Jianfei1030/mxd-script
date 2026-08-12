import unittest

from src.globals import resolve_backend, should_restart_for_gpu


class TestResolveBackend(unittest.TestCase):
    """推理后端选择:勾选「启用GPU推理」→ 'auto'(DirectML 优先,失败回退 CPU);
    默认 'cpu'(OpenVINO,兼容性最好);任何异常一律 'cpu' 兜底。
    """

    def test_accel_on_returns_auto(self):
        self.assertEqual(resolve_backend({'启用GPU推理': True}), 'auto')

    def test_accel_off_returns_cpu(self):
        self.assertEqual(resolve_backend({'启用GPU推理': False}), 'cpu')

    def test_missing_accel_returns_cpu(self):
        self.assertEqual(resolve_backend(None), 'cpu')
        self.assertEqual(resolve_backend({}), 'cpu')
        self.assertEqual(resolve_backend({'启用GPU推理': 0}), 'cpu')

    def test_broken_config_returns_cpu(self):
        # 无 get 方法 / get 抛异常 → 一律按 CPU 兜底
        self.assertEqual(resolve_backend(42), 'cpu')


class TestShouldRestartForGpu(unittest.TestCase):
    """勾选GPU后是否自动重启:勾选 + 模型已CPU创建 → True;
    模型未创建/已GPU/未勾选 → False。"""

    def test_enabled_and_cpu_model_restarts(self):
        self.assertTrue(should_restart_for_gpu(True, 'cpu'))

    def test_enabled_but_model_not_created(self):
        # 懒加载未触发:首次检测会按新配置选后端,无需重启
        self.assertFalse(should_restart_for_gpu(True, None))

    def test_enabled_and_gpu_model(self):
        self.assertFalse(should_restart_for_gpu(True, 'dml'))

    def test_disabled_never_restarts(self):
        self.assertFalse(should_restart_for_gpu(False, 'cpu'))
        self.assertFalse(should_restart_for_gpu(False, 'dml'))
        self.assertFalse(should_restart_for_gpu(False, None))


if __name__ == '__main__':
    unittest.main()
