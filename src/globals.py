from PySide6.QtCore import QObject


class Globals(QObject):
    """应用级单例(对应 config['my_app'])。YOLO 等重型资源后续按需加到这里。"""

    def __init__(self, exit_event):
        super().__init__()
        self.exit_event = exit_event
