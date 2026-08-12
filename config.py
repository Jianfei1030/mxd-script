import os

from qfluentwidgets import FluentIcon

from ok import ConfigOption

version = "v0.1.0"

key_config_option = ConfigOption('游戏按键', {
    '攻击键': 'ctrl',
    '副攻击键(可留空)': '',
    '血药键': 'home',
    '蓝药键': 'insert',
    '回城卷键(可留空)': '',
    '拾取键': 'z',
    '宠物食物键(可留空)': '',
    '椅子键(可留空)': '',
    '群攻键(可留空)': '',
    '左移键': 'left',
    '右移键': 'right',
}, description='冒险岛游戏内按键,与游戏内键盘设置保持一致', config_description={
    '回城卷键(可留空)': '低血保命用。留空则低血时只停止任务不逃跑',
    '宠物食物键(可留空)': '喂宠物用。先在游戏内把宠物食物拖到快捷键,再填对应按键;留空则不喂',
    '椅子键(可留空)': '坐椅用(检测模式没怪时自动坐椅子回血蓝)。先在游戏内把椅子拖到快捷键,再填对应按键;留空则不坐',
    '群攻键(可留空)': '群攻(前后双向命中)技能键。接敌区内怪数达到「群攻怪数阈值」时改按它,那一拍不转向也不按单体攻击键。留空 = 功能关闭',
    '副攻击键(可留空)': '二连击的第二段攻击键(先按攻击键、立即接它)。需「二连击开关」开启且此处已绑定才生效:留空或开关未开,二连击均不启用',
}, show_at_tab=True, icon=FluentIcon.GAME)

inference_config_option = ConfigOption('推理加速', {
    '启用GPU推理': False,
}, description='YOLO 推理后端:默认 CPU(OpenVINO,兼容性最好);勾选后优先使用本机最强推理硬件(DirectML GPU,失败自动回退 CPU)', config_description={
    '启用GPU推理': '勾选后 YOLO 检测走 DirectML GPU(本机 RTX 4060 等),失败自动回退 CPU;不勾选始终用 CPU。默认不勾选以保兼容性',
}, config_type={
    '依赖状态': {'type': 'dependency_check'},
}, show_at_tab=True, icon=FluentIcon.SPEED_HIGH)

config = {
    'debug': False,
    'use_gui': True,
    'config_folder': 'configs',
    'gui_icon': 'icons/icon.png',
    'global_configs': [key_config_option, inference_config_option],
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
    'trigger_tasks': [
        ["src.task.MapleFarmTask", "MapleFarmTask"],
    ],
    'scene': ["src.scene.MapleScene", "MapleScene"],
}
