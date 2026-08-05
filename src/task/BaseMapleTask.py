from ok import BaseTask, Logger

logger = Logger.get_logger(__name__)


class BaseMapleTask(BaseTask):

    def stop_farming(self, reason):
        self.log_warning(f'停止打怪:{reason}', notify=True)
        self.disable()
