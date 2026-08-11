import unittest

from src.globals import resolve_backend


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


if __name__ == '__main__':
    unittest.main()
