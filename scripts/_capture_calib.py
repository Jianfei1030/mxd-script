"""抓一帧游戏画面存 screenshots/calib_frame.png(标定用)。后台运行,输出到日志文件。

路径不写死:项目根由本文件位置推导(scripts/ 的上一级),可在任意机器/任意
目录运行(铁律:禁止 hard code 本地路径)。
"""
import sys
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
os.chdir(ROOT)

LOG = 'logs/capture_calib.log'

def log(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')

log('start capture')
try:
    from capture_frame import build_capture
    import cv2
    exit_event, hwnd, method = build_capture()
    time.sleep(3)
    for i in range(10):
        frame = method.get_frame()
        if frame is not None:
            os.makedirs('screenshots', exist_ok=True)
            cv2.imwrite('screenshots/calib_frame.png', frame)
            log(f'SAVED calib_frame.png shape={frame.shape}')
            break
        log(f'frame None retry {i}')
        time.sleep(1)
    else:
        log('FAILED no frame after 10 retries')
except Exception as e:
    log(f'ERROR {e}')
log('done')
