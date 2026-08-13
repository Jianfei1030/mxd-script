from ok.gui.tasks.LabelAndButtons import LabelAndButtons
from ok.gui.tasks.LabelAndDoubleSpinBox import LabelAndDoubleSpinBox
from ok.gui.tasks.LabelAndDropDown import LabelAndDropDown
from ok.gui.tasks.LabelAndFileSelector import LabelAndFileSelector
from ok.gui.tasks.LabelAndGlobal import LabelAndGlobal
from ok.gui.tasks.LabelAndLineEdit import LabelAndLineEdit
from ok.gui.tasks.LabelAndMultiSelection import LabelAndMultiSelection
from ok.gui.tasks.LabelAndSpinBox import LabelAndSpinBox
from ok.gui.tasks.LabelAndSwitchButton import LabelAndSwitchButton
from ok.gui.tasks.LabelAndTextEdit import LabelAndTextEdit
from ok.gui.tasks.LabelAndBuffList import LabelAndBuffList
from ok.gui.tasks.LabelAndDependencyCheck import LabelAndDependencyCheck
from ok.gui.tasks.LabelAndKeyInput import LabelAndKeyInput
from ok.gui.tasks.ModifyListItem import ModifyListItem


def _resolve_type(the_type, default_value):
    if not isinstance(the_type, dict):
        return None

    resolved_type = the_type.get('type')
    if resolved_type:
        return resolved_type
    if 'buttons' in the_type or 'callback' in the_type:
        return 'button'
    if 'options' in the_type:
        if isinstance(default_value, list):
            return 'multi_selection'
        return 'drop_down'
    return None


def _restart_for_gpu_if_needed():
    """勾选「启用GPU推理」后,若模型已用 CPU 创建则自动重启 GUI 让 GPU 生效。
    模型未创建(懒加载未触发)时无需重启——首次检测会按新配置选后端。"""
    import threading

    from ok import Logger, og
    from src.globals import should_restart_for_gpu

    logger = Logger.get_logger(__name__)

    def restart():
        try:
            my_app = getattr(og, 'my_app', None)
            backend = getattr(my_app, 'model_backend', None) if my_app else None
            if not should_restart_for_gpu(True, backend):
                logger.info(f'启用GPU推理:模型后端={backend},无需重启')
                return
            logger.info('启用GPU推理但模型已用 CPU 创建,自动重启 GUI 使 DirectML 生效')
            import ctypes
            import sys
            import os
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), os.getcwd(), 1)
            my_app.exit_event.set()
        except Exception as e:
            logger.error(f'启用GPU推理自动重启失败: {e}')

    threading.Thread(target=restart, daemon=True).start()


def config_widget(config_type, config_desc, config, key, value, task):
    the_type = config_type.get(key) if config_type is not None else None
    value = config.get_default(key)
    resolved_type = _resolve_type(the_type, value)
    if resolved_type:
        if resolved_type == 'drop_down':
            if isinstance(value, list) and 'options_available' in the_type:
                return ModifyListItem(
                    config_desc, config, key, options_available=the_type['options_available'],
                    allow_duplication=the_type.get('allow_duplication', False)
                )
            return LabelAndDropDown(config_desc, the_type['options'], config, key)
        elif resolved_type == 'multi_selection':
            return LabelAndMultiSelection(config_desc, the_type['options'], config, key)
        elif resolved_type == 'global':
            config = task.get_global_config(key)
            desc = task.get_global_config_desc(key)
            return LabelAndGlobal(desc, config, key)
        elif resolved_type == 'text_edit':
            return LabelAndTextEdit(config_desc, config, key)
        elif resolved_type == 'file_selector':
            if not isinstance(value, str):
                raise ValueError("file_selector config type requires a string default value")
            return LabelAndFileSelector(config_desc, config, key, the_type)
        elif resolved_type == 'button':
            buttons = the_type.get('buttons')
            if not buttons:
                buttons = [the_type]
            return LabelAndButtons(config_desc, key, buttons)
        elif resolved_type == 'buff_list':
            return LabelAndBuffList(config_desc, config, key)
        elif resolved_type == 'key_input':
            return LabelAndKeyInput(config_desc, config, key)
        elif resolved_type == 'dependency_check':
            return LabelAndDependencyCheck(config_desc, config, key)
        else:
            raise Exception('Unknown config type')
    if isinstance(value, bool):
        on_check = None
        if key == '启用GPU推理' and '推理加速' in getattr(config, 'config_file', ''):
            on_check = _restart_for_gpu_if_needed
        return LabelAndSwitchButton(config_desc, config, key, on_check=on_check)
    elif isinstance(value, list):
        options_available = the_type.get('options_available') if isinstance(the_type, dict) else None
        allow_duplication = the_type.get('allow_duplication', False) if isinstance(the_type, dict) else False
        return ModifyListItem(
            config_desc, config, key, options_available=options_available,
            allow_duplication=allow_duplication
        )
    elif isinstance(value, int):
        return LabelAndSpinBox(config_desc, config, key, the_type)
    elif isinstance(value, float):
        return LabelAndDoubleSpinBox(config_desc, config, key)
    elif isinstance(value, str):
        if value and len(value) > 16 or '\n' in value:
            return LabelAndTextEdit(config_desc, config, key)
        else:
            return LabelAndLineEdit(config_desc, config, key)
    else:
        raise ValueError(f"invalid type {type(value)}, value {value}")
