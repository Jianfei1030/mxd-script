"""每隔 N 秒抓一帧存入 dataset/raw/<地图名>/,站到刷怪图挂机采集。
用法: python scripts/record_frames.py <地图名> [间隔秒=2] [数量=50]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time

from scripts.capture_frame import build_capture

if __name__ == '__main__':
    import cv2

    map_name = sys.argv[1] if len(sys.argv) > 1 else 'map'
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    out_dir = f'dataset/raw/{map_name}'
    os.makedirs(out_dir, exist_ok=True)
    ev, win, cap = build_capture()
    existing = len(os.listdir(out_dir))
    for i in range(count):
        frame = cap.get_frame()
        if frame is not None:
            path = f'{out_dir}/frame_{existing + i:04d}.png'
            cv2.imwrite(path, frame)
            print(f'{i + 1}/{count} {path}')
        time.sleep(interval)
    ev.set()
