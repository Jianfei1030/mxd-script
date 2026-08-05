from ok import BaseScene


class MapleScene(BaseScene):
    """框架要求 scene 类存在(config['scene'])。状态缓存按需后续添加,MVP 为空壳。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
