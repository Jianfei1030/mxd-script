import os
import sys
import unittest
from unittest import mock

import numpy as np

import src.OpenVinoYolo8Detect as yolo_mod
from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect

MODEL = 'assets/mob_model/mob.onnx'

try:
    import importlib.util
    HAS_ORT = importlib.util.find_spec('onnxruntime') is not None
except Exception:
    HAS_ORT = False

FRAME = np.random.randint(0, 255, (360, 640, 3), dtype=np.uint8)  # 小帧提速(纯延迟测试与内容无关)


@unittest.skipUnless(os.path.exists(MODEL), 'YOLO 模型缺失,跳过')
class TestDetectBackend(unittest.TestCase):
    """推理后端选择:DirectML 优先,OpenVINO CPU 兜底。

    detect() 内部会吞掉一切异常并返回 [],所以"返回 []"不能证明后端跑通了——
    必须同时断言没有 error 日志被吞。
    """

    def _detect_no_error(self, det, frame):
        errors = []
        with mock.patch.object(yolo_mod.logger, 'error', side_effect=errors.append):
            boxes = det.detect(frame, threshold=0.5)
        self.assertEqual(errors, [], f'detect 内部异常被吞: {errors}')
        return boxes

    def test_cpu_backend_forces_openvino(self):
        det = OpenVinoYolo8Detect(weights=MODEL, backend='cpu')
        self.assertIsNone(det._ort_session)
        self.assertIsNotNone(det.compiled_model)
        boxes = self._detect_no_error(det, FRAME)
        self.assertIsInstance(boxes, list)

    def test_default_backend_is_cpu(self):
        # 不显式传 backend 时默认走 OpenVINO CPU(兼容性优先,GPU 需显式/勾选启用)
        det = OpenVinoYolo8Detect(weights=MODEL)
        self.assertIsNone(det._ort_session)
        self.assertIsNotNone(det.compiled_model)

    def test_auto_falls_back_to_cpu_without_onnxruntime(self):
        # 模拟 onnxruntime 不可用(如无 DML 依赖的机器)→ 自动回退 OpenVINO CPU,
        # 且必须打显式 warning(用户勾选了 GPU 却不可用,不能静默)
        warnings = []
        with mock.patch.dict(sys.modules, {'onnxruntime': None}), \
                mock.patch.object(yolo_mod.logger, 'warning', side_effect=warnings.append):
            det = OpenVinoYolo8Detect(weights=MODEL, backend='auto')
        self.assertIsNone(det._ort_session)
        self.assertIsNotNone(det.compiled_model)
        self.assertTrue(any('DirectML 不可用' in str(w) for w in warnings),
                        f'应显式警告 DirectML 不可用,实际 warning 调用: {warnings}')
        self._detect_no_error(det, FRAME)

    @unittest.skipUnless(HAS_ORT, 'onnxruntime-directml 未安装,跳过')
    def test_auto_uses_dml_when_available(self):
        det = OpenVinoYolo8Detect(weights=MODEL, backend='auto')
        self.assertIsNotNone(det._ort_session, 'DirectML session 应被创建')
        self.assertFalse(hasattr(det, 'compiled_model'), 'DML 可用时不应再走 OpenVINO')
        self._detect_no_error(det, FRAME)

    @unittest.skipUnless(HAS_ORT, 'onnxruntime-directml 未安装,跳过')
    def test_dml_and_cpu_agree_on_empty_frame(self):
        det_dml = OpenVinoYolo8Detect(weights=MODEL, backend='auto')
        det_cpu = OpenVinoYolo8Detect(weights=MODEL, backend='cpu')
        black = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertEqual(det_dml.detect(black, threshold=0.5),
                         det_cpu.detect(black, threshold=0.5))


if __name__ == '__main__':
    unittest.main()
