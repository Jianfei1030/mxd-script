from qfluentwidgets import FluentIcon

from ok import TriggerTask
from src.task.BaseMapleTask import BaseMapleTask


class MapleFarmTask(TriggerTask, BaseMapleTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动打怪"
        self.description = "站桩定频攻击+自动喝药+低血保命"
        self.icon = FluentIcon.GAME
        self.trigger_interval = 0.1
        self.default_config.update({'_enabled': False})

    def run(self):
        pass
