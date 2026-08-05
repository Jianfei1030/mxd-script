import os

from qfluentwidgets import FluentIcon

from ok import ConfigOption

version = "v0.1.0"

key_config_option = ConfigOption('游戏按键', {
    '攻击键': 'ctrl',
    '血药键': 'home',
    '蓝药键': 'insert',
    '回城卷键(可留空)': '',
    '拾取键': 'z',
}, description='冒险岛游戏内按键,与游戏内键盘设置保持一致', config_description={
    '回城卷键(可留空)': '低血保命用。留空则低血时只停止任务不逃跑',
}, show_at_tab=True, icon=FluentIcon.GAME)

config = {
    'debug': False,
    'use_gui': True,
    'config_folder': 'configs',
    'gui_icon': 'icons/icon.png',
    'global_configs': [key_config_option],
    'ocr': {
        'lib': 'onnxocr',
        'auto_simplify': True,
        'params': {'use_openvino': True, 'use_npu': True},
    },
    'my_app': ['src.globals', 'Globals'],
    'start_timeout': 60,
    'wait_until_settle_time': 0,
    'template_matching': {
        'coco_feature_json': os.path.join('assets', 'coco_annotations.json'),
        'default_horizontal_variance': 0.002,
        'default_vertical_variance': 0.002,
        'default_threshold': 0.8,
    },
    'windows': {
        'title': '冒险岛怀旧服',
        'exe': 'Maplestory_Classic.exe',
        'hwnd_class': 'UnityWndClass',
        'interaction': 'PyDirect',
        'capture_method': ['WGC', 'BitBlt_RenderFull'],
        'check_hdr': False,
        'force_no_hdr': False,
        'check_night_light': False,
        'force_no_night_light': False,
    },
    'window_size': {'width': 1200, 'height': 800, 'min_width': 1200, 'min_height': 800},
    # ratio 设 None 显式关闭比例检查(冒险岛有 4:3/窗口化,不照搬鸣潮 16:9)
    'supported_resolution': {'ratio': None, 'resize_to': [], 'min_size': (1024, 768)},
    'links': {'default': {}},
    'about': """
    <p style="color:red;"><strong>本软件仅供个人学习 Python、计算机视觉、UI 自动化使用。</strong></p>
    <p style="color:red;"><strong>使用本软件可能导致账号被封禁,后果自负。</strong></p>
""",
    'screenshots_folder': 'screenshots',
    'gui_title': 'OK-MXD',
    'log_file': 'logs/ok-mxd.log',
    'error_log_file': 'logs/ok-mxd_error.log',
    'version': version,
    'onetime_tasks': [],
    'trigger_tasks': [["src.task.MapleFarmTask", "MapleFarmTask"]],
    'scene': ["src.scene.MapleScene", "MapleScene"],
}
