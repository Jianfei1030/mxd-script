"""抓取一帧游戏画面。用法: python scripts/capture_frame.py <输出路径.png>
(直接运行该脚本时 sys.path[0] 是 scripts/,先把项目根插进去才能 import ok)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time


class _Opt(dict):
    validator = None


class _FakeGlobalConfig:
    def get_config(self, option):
        return _Opt()


class _FakeDeviceManager:
    config = {'selected_hwnd': 0}
    capture_method = None


def build_capture():
    """返回 (exit_event, hwnd_window, capture_method)。用毕需 exit_event.set()。"""
    from ok.device.capture_methods.hwnd_window import HwndWindow
    from ok.device.capture_methods.windows_graphics import WindowsGraphicsCaptureMethod

    exit_event = threading.Event()
    win = HwndWindow(exit_event, title='冒险岛怀旧服', exe_name='Maplestory_Classic.exe',
                     hwnd_class='UnityWndClass',
                     global_config=_FakeGlobalConfig(), device_manager=_FakeDeviceManager())
    deadline = time.time() + 10
    while not win.exists and time.time() < deadline:
        time.sleep(0.5)
    if not win.exists:
        raise RuntimeError('未找到游戏窗口(冒险岛怀旧服/UnityWndClass)')
    cap = WindowsGraphicsCaptureMethod(win)
    time.sleep(2)
    return exit_event, win, cap


if __name__ == '__main__':
    import cv2

    out = sys.argv[1] if len(sys.argv) > 1 else 'screenshots/frame.png'
    ev, win, cap = build_capture()
    frame = cap.get_frame()
    assert frame is not None, 'WGC 取帧失败'
    cv2.imwrite(out, frame)
    print(f'saved {out} {frame.shape}')
    ev.set()
