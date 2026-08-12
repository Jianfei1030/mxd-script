import os

from PySide6.QtCore import QObject

from ok import Logger, get_path_relative_to_exe

logger = Logger.get_logger(__name__)


def resolve_backend(accel_config):
    """推理后端选择:accel_config 勾选「启用GPU推理」→ 'auto'(DirectML 优先,失败回退 CPU);
    默认 'cpu'(OpenVINO,兼容性最好);任何读取异常一律 'cpu' 兜底。"""
    try:
        if accel_config and accel_config.get('启用GPU推理'):
            return 'auto'
    except Exception:
        pass
    return 'cpu'


def should_restart_for_gpu(gpu_enabled, model_backend):
    """判断是否需要重启 GUI 让 GPU 加速生效:
    gpu_enabled=True 且模型已创建(model_backend 非 None)且当前为 CPU 后端 → True;
    模型未创建(None)时懒加载会按新配置选后端,无需重启。"""
    if not gpu_enabled:
        return False
    if model_backend is None:
        return False
    return model_backend == 'cpu'


class Globals(QObject):
    """应用级单例(对应 config['my_app'])。"""

    def __init__(self, exit_event):
        super().__init__()
        self.exit_event = exit_event
        self._yolo_model = None

    @property
    def yolo_model(self):
        if self._yolo_model is None:
            weights = get_path_relative_to_exe(os.path.join('assets', 'mob_model', 'mob.onnx'))
            from src.OpenVinoYolo8Detect import OpenVinoYolo8Detect
            self._yolo_model = OpenVinoYolo8Detect(weights=weights, backend=self._resolve_backend())
        return self._yolo_model

    @property
    def model_backend(self):
        """模型实际后端:None=模型尚未创建(懒加载);'cpu'=OpenVINO CPU;'dml'=DirectML GPU。"""
        if self._yolo_model is None:
            return None
        return getattr(self._yolo_model, 'backend', 'cpu')

    def _resolve_backend(self):
        """从全局配置「推理加速」取后端:勾选→auto,否则 cpu。读取失败一律 cpu。"""
        backend = 'cpu'
        try:
            from ok import og
            global_config = getattr(getattr(og, 'app', None), 'global_config', None)
            if global_config is not None:
                backend = resolve_backend(global_config.get_config('推理加速'))
        except Exception:
            pass
        return backend

    def yolo_detect(self, image, threshold=0.5, label=-1):
        return self.yolo_model.detect(image, threshold=threshold, label=label)
