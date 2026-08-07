"""截取指定窗口(按 PID)的截图,存到指定路径。E2E 截图取证用,不依赖游戏。

用法: python scripts/_e2e_capture.py <pid> <out_path>
"""
import sys
import os
import time

import cv2
import numpy as np
from PIL import ImageGrab
import win32gui
import win32con
import win32process


def capture_window(pid, out_path):
    # 该进程下找可见主窗口
    hwnds = []

    def enum_cb(h, _):
        if win32gui.IsWindowVisible(h):
            _, wpid = win32process.GetWindowThreadProcessId(h)
            if wpid == pid:
                hwnds.append(h)
        return True

    win32gui.EnumWindows(enum_cb, None)
    if not hwnds:
        print(f'NO_WINDOW pid={pid}')
        return False
    hwnd = hwnds[0]
    rect = win32gui.GetWindowRect(hwnd)
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    print(f'WINDOW rect=({x0},{y0},{w}x{h}) hwnd={hwnd}')
    # 前台化再截,保证内容完整
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(1.0)
    except Exception as e:
        print(f'foreground warn: {e}')
    img = ImageGrab.grab(bbox=rect)
    img.save(out_path)
    print(f'SAVED {out_path} {img.size}')


if __name__ == '__main__':
    os.makedirs(os.path.dirname(sys.argv[2]), exist_ok=True)
    capture_window(int(sys.argv[1]), sys.argv[2])
