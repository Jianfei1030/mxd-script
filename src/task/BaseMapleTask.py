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

    def find_mobs(self, frame=None, threshold=0.5):
        from ok import og
        return og.my_app.yolo_detect(frame if frame is not None else self.frame,
                                     threshold=threshold, label=0)

    def stop_farming(self, reason):
        self.log_warning(f'停止打怪:{reason}', notify=True)
        self.disable()
