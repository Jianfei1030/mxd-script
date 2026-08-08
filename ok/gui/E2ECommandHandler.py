"""E2E 控件查找与 OS 级操作。

职责：
1. 查找 Qt widget 树，返回控件屏幕坐标、类型、状态
2. 通过 win32api 发送 OS 级输入事件（模拟真实用户）
3. 截图（WGC 游戏窗口 / 全屏含 overlay）
"""
import base64
import io
import logging
import time

from PySide6.QtCore import QPoint

logger = logging.getLogger(__name__)

# 从 LabelAndXxx 包装中提取底层 Qt 控件的属性名
_INNER_ATTR = {
    'LabelAndSwitchButton': 'switch_button',
    'LabelAndSpinBox': 'spin_box',
    'LabelAndDoubleSpinBox': 'spin_box',
    'LabelAndLineEdit': 'line_edit',
    'LabelAndTextEdit': 'text_edit',
    'LabelAndDropDown': 'combo_box',
}


class E2ECommandHandler:
    """控件查找 + OS 级操作 + 截图。"""

    def __init__(self, main_window, app):
        self.mw = main_window
        self.app = app
        self._widget_map = {}
        self._build_static_map()
        self._discover_task_widgets()

    # ── 注册表构建 ──────────────────────────────────────

    def _build_static_map(self):
        """静态映射：StartTab 上的固定控件。"""
        st = self.mw.start_tab
        self._widget_map.update({
            'start_button': st.start_card.start_button,
            'refresh_button': st.start_card.refresh_button,
            'capture_button': st.start_card.capture_button,
            'status_bar': st.start_card.status_bar,
            'overlay_switch': st.overlay_switch,
            'overlay_log_switch': st.overlay_log_switch,
            'device_list': st.device_list,
            'capture_list': st.capture_list,
            'interaction_list': st.interaction_list,
        })

    def _discover_task_widgets(self):
        """动态发现：扫描所有 TaskCard，注册 enable 开关 + 配置控件。"""
        for tab_attr in ('trigger_tab', 'onetime_tab'):
            tab = getattr(self.mw, tab_attr, None)
            if tab is None:
                continue
            cards = getattr(tab, 'card_widgets', [])
            for card in cards:
                task_name = card.task.name
                if card.enable_button:
                    self._widget_map[f'task_{task_name}_enable'] = card.enable_button
                for key, widget in card.config_widget_by_key.items():
                    inner = self._extract_inner(widget)
                    if inner is not None:
                        self._widget_map[f'task_{task_name}_{key}'] = inner

    @staticmethod
    def _extract_inner(widget):
        """从 LabelAndXxx 包装中取出底层 Qt 控件。"""
        cls_name = type(widget).__name__
        attr = _INNER_ATTR.get(cls_name)
        if attr:
            return getattr(widget, attr, None)
        return widget

    # ── 控件查找 ────────────────────────────────────────

    def find_widget(self, name):
        """查找控件，返回 (widget, info_dict) 或 (None, error_dict)。"""
        widget = self._widget_map.get(name)
        if widget is None:
            return None, {'exists': False, 'error': f'widget not found: {name}'}
        info = self._widget_info(widget)
        info['exists'] = True
        return widget, info

    @staticmethod
    def _widget_info(widget):
        """提取控件元信息。"""
        info = {
            'type': type(widget).__name__,
            'visible': widget.isVisible() if hasattr(widget, 'isVisible') else True,
        }
        # 文本
        for attr in ('text', 'title', 'currentText', 'toPlainText', 'placeholderText'):
            val = getattr(widget, attr, None)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = None
            if val is not None:
                info['text'] = str(val)
                break
        # 选中状态
        for attr in ('isChecked', 'checked'):
            val = getattr(widget, attr, None)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = None
            if isinstance(val, bool):
                info['checked'] = val
                break
        # 数值
        for attr in ('value',):
            val = getattr(widget, attr, None)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    val = None
            if val is not None:
                info['value'] = val
                break
        # 屏幕坐标
        try:
            center = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() // 2))
            info['rect'] = {
                'x': center.x(),
                'y': center.y(),
                'w': widget.width(),
                'h': widget.height(),
            }
        except Exception:
            info['rect'] = None
        return info

    # ── OS 级操作 ───────────────────────────────────────

    def os_click(self, name):
        """模拟真实用户点击：移动鼠标 → 按下 → 抬起。"""
        widget, info = self.find_widget(name)
        if widget is None:
            return info
        if not info.get('visible', True):
            logger.warning(f'os_click: widget {name} is not visible, clicking anyway')
        self._os_click_widget(widget)
        return {'ok': True}

    def _os_click_widget(self, widget):
        """对指定控件执行 OS 级点击（移动鼠标 → 按下 → 抬起）。"""
        import win32api
        import win32con
        center = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() // 2))
        x, y = center.x(), center.y()
        # 移动鼠标
        win32api.SetCursorPos((x, y))
        time.sleep(0.05)
        # 按下 + 抬起
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
        time.sleep(0.1)  # 等待 Qt 处理事件

    def os_type_text(self, name, text):
        """点击控件获取焦点 → 清空 → 剪贴板粘贴（支持中文）。"""
        import win32api
        import win32con
        import pyperclip

        widget, info = self.find_widget(name)
        if widget is None:
            return info

        # 点击获取焦点
        center = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() // 2))
        x, y = center.x(), center.y()
        win32api.SetCursorPos((x, y))
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
        time.sleep(0.02)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
        time.sleep(0.15)

        # Ctrl+A 全选
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(0x41, 0, 0, 0)  # 'A'
        win32api.keybd_event(0x41, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)

        # Delete 清空
        win32api.keybd_event(win32con.VK_DELETE, 0, 0, 0)
        win32api.keybd_event(win32con.VK_DELETE, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)

        # 剪贴板粘贴（支持中文）
        pyperclip.copy(text)
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(0x56, 0, 0, 0)  # 'V'
        win32api.keybd_event(0x56, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)

        return {'ok': True}

    def os_press_key(self, key_name):
        """按单个键（enter/escape/tab/f9 等）。"""
        import win32api
        import win32con

        vk_map = {
            'enter': win32con.VK_RETURN,
            'return': win32con.VK_RETURN,
            'escape': win32con.VK_ESCAPE,
            'esc': win32con.VK_ESCAPE,
            'tab': win32con.VK_TAB,
            'space': win32con.VK_SPACE,
            'delete': win32con.VK_DELETE,
            'backspace': win32con.VK_BACK,
            'f9': 0x78,
            'f10': 0x79,
            'f11': 0x7A,
            'f12': 0x7B,
        }
        vk = vk_map.get(key_name.lower())
        if vk is None:
            return {'ok': False, 'error': f'unknown key: {key_name}'}
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        return {'ok': True}

    def os_hotkey(self, keys):
        """组合键（如 ["ctrl", "a"]）。"""
        import win32api
        import win32con

        vk_map = {
            'ctrl': win32con.VK_CONTROL,
            'alt': win32con.VK_MENU,
            'shift': win32con.VK_SHIFT,
            'win': win32con.VK_LWIN,
        }
        # 按下所有修饰键
        for k in keys[:-1]:
            vk = vk_map.get(k.lower())
            if vk is None:
                return {'ok': False, 'error': f'unknown modifier: {k}'}
            win32api.keybd_event(vk, 0, 0, 0)
        # 按下主键
        main_key = keys[-1]
        vk = vk_map.get(main_key.lower())
        if vk is None and len(main_key) == 1:
            # 尝试字母键
            vk = ord(main_key.upper())
        if vk is None:
            return {'ok': False, 'error': f'unknown key: {main_key}'}
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        # 释放修饰键（逆序）
        for k in reversed(keys[:-1]):
            vk = vk_map.get(k.lower())
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
        return {'ok': True}

    # ── 导航 ────────────────────────────────────────────

    def navigate(self, tab_name):
        """切换导航 tab。tab_name: start/triggers/settings/about..."""
        tab_map = {
            'start': self.mw.start_tab,
            'triggers': self.mw.trigger_tab,
            'onetime': self.mw.onetime_tab,
            'settings': self.mw.setting_tab,
            'about': self.mw.about_tab,
            'schedule': getattr(self.mw, 'schedule_tab', None),
            'debug': getattr(self.mw, 'debug_tab', None),
        }
        tab = tab_map.get(tab_name)
        if tab is None:
            return {'ok': False, 'error': f'tab not found: {tab_name}'}
        self.mw.switchTo(tab)
        time.sleep(0.3)  # 等待 tab 切换动画
        return {'ok': True}

    def expand_card(self, task_name):
        """展开指定任务的 TaskCard（OS 级点击展开按钮）。"""
        for tab_attr in ('trigger_tab', 'onetime_tab'):
            tab = getattr(self.mw, tab_attr, None)
            if tab is None:
                continue
            for card in getattr(tab, 'card_widgets', []):
                if card.task.name == task_name:
                    # 若已展开则跳过
                    if getattr(card, 'isExpand', lambda: False)():
                        return {'ok': True}
                    expand_btn = getattr(getattr(card, 'card', None), 'expandButton', None)
                    if expand_btn is None:
                        expand_btn = getattr(card, 'expandButton', None)
                    if expand_btn is not None and expand_btn.isVisible():
                        self._os_click_widget(expand_btn)
                    else:
                        card.setExpand(True)
                    time.sleep(0.3)
                    # 展开后重新发现配置控件
                    for key, widget in card.config_widget_by_key.items():
                        inner = self._extract_inner(widget)
                        if inner is not None:
                            self._widget_map[f'task_{task_name}_{key}'] = inner
                    return {'ok': True}
        return {'ok': False, 'error': f'task card not found: {task_name}'}

    # ── 任务控制 ────────────────────────────────────────

    def start_executor(self):
        return self.os_click('start_button')

    def pause_executor(self):
        return self.os_click('start_button')

    # ── 配置读写（直接操作 Config dict） ────────────────

    def get_config(self, task_name, key=None):
        """读取任务配置。"""
        from ok import og
        for task in og.executor.get_all_tasks():
            if task.name == task_name:
                if key:
                    return {'ok': True, 'result': {key: task.config.get(key)}}
                return {'ok': True, 'result': dict(task.config)}
        return {'ok': False, 'error': f'task not found: {task_name}'}

    def set_config(self, task_name, key, value):
        """写入任务配置（自动持久化 JSON）。"""
        from ok import og
        for task in og.executor.get_all_tasks():
            if task.name == task_name:
                task.config[key] = value
                return {'ok': True}
        return {'ok': False, 'error': f'task not found: {task_name}'}

    # ── 状态查询 ────────────────────────────────────────

    def get_status_bar_text(self):
        """读取 StartCard 状态栏文字。"""
        try:
            text = self.mw.start_tab.start_card.status_bar.title
            return {'ok': True, 'result': {'text': text}}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ── 截图 ────────────────────────────────────────────

    def screenshot_game(self, save_path=None):
        """WGC 抓取游戏窗口（不含 overlay）。"""
        from ok import og
        from PIL import Image

        if og.device_manager is None:
            return {'ok': False, 'error': 'device_manager not initialized'}
        frame = og.device_manager.capture_method.get_frame()
        if frame is None:
            return {'ok': False, 'error': 'WGC capture returned None (game window not found?)'}
        img = Image.fromarray(frame[:, :, ::-1])  # BGR -> RGB
        if save_path:
            import os
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            img.save(save_path)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {'ok': True, 'result': {'base64_png': b64, 'w': img.width, 'h': img.height}}

    def screenshot_screen(self, save_path=None, rect=None):
        """全屏截图（含 overlay 绘制）。rect={x,y,w,h} 可选裁剪。"""
        import win32gui
        from PIL import ImageGrab
        from ok import og

        if og.device_manager is None:
            return {'ok': False, 'error': 'device_manager not initialized'}
        hwnd = og.device_manager.hwnd_window.hwnd
        if rect:
            img = ImageGrab.grab(bbox=(rect['x'], rect['y'],
                                       rect['x'] + rect['w'], rect['y'] + rect['h']))
        else:
            try:
                r = win32gui.GetWindowRect(hwnd)
                img = ImageGrab.grab(bbox=r)
            except Exception:
                # 窗口不存在时截全屏
                img = ImageGrab.grab()
        if save_path:
            import os
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            img.save(save_path)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {'ok': True, 'result': {'base64_png': b64, 'w': img.width, 'h': img.height}}
