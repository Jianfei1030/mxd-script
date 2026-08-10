from ok import BaseTask, Logger
from src.detect import bars

logger = Logger.get_logger(__name__)


class BaseMapleTask(BaseTask):

    def read_hp(self, frame=None):
        return bars.read_hp(frame if frame is not None else self.frame)

    def read_mp(self, frame=None):
        return bars.read_mp(frame if frame is not None else self.frame)

    def read_exp(self, frame=None):
        return bars.read_exp(frame if frame is not None else self.frame)

    def find_mobs(self, frame=None, threshold=0.5, boxes=None):
        """boxes= 传入同拍已推理的全类别结果时只做类别过滤,不再推理
        (一拍一次推理,spec §3.2;detect 的 label 参数是事后过滤,分两次调用
        会白付一倍推理)。不传 = 旧行为(自行推理)。"""
        if boxes is not None:
            return [b for b in boxes if b.name == 'mob']
        from ok import og
        return og.my_app.yolo_detect(frame if frame is not None else self.frame,
                                     threshold=threshold, label=0)

    def find_all(self, frame=None, threshold=0.5):
        """一次推理拿全类别(mob+player),供检测拍分流。"""
        from ok import og
        return og.my_app.yolo_detect(frame if frame is not None else self.frame,
                                     threshold=threshold, label=-1)

    def stop_farming(self, reason):
        self.log_warning(f'停止打怪:{reason}', notify=True)
        self.disable()
