"""路线录制器(spec §5):手动走一遍,按键着色,录出 route*.png。
用法: python scripts/route_recorder.py <地图名>
流程: 标定(首跑)→ 移动捕获 → 录制(F2 存段/F3 撤销/F4 放弃段/ESC 退出)。
前置: 停 GUI(WGC 冲突,AGENTS.md §1.4);游戏窗口前台 2560×1440;小地图展开+约定缩放。"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from pynput import keyboard

from scripts.capture_frame import build_capture
from src.detect import minimap
from src.task import route_logic as rl

DEFAULT_PANEL_ROI = (10, 100, 270, 190)   # 面板地图区粗裁(2560×1440 实测训练场截图),CLI 可改
ARCHIVE_FRAMES = 20                        # 存档帧数(离线测试用)
BLOB_COOLDOWN = 0.7

# 真实键位 → 规范名(与 config.py 游戏按键默认一致;用户改过键位需同步)
KEY_MAP = {
    keyboard.Key.left: 'left', keyboard.Key.right: 'right',
    keyboard.Key.up: 'up', keyboard.Key.down: 'down',
    keyboard.Key.alt_l: 'space', keyboard.Key.alt_r: 'space',
    keyboard.Key.f2: 'f2', keyboard.Key.f3: 'f3', keyboard.Key.f4: 'f4',
    keyboard.Key.esc: 'esc',
}


class Recorder:
    def __init__(self, map_dir, panel_roi):
        self.map_dir = map_dir
        self.base = minimap.load_base_map(map_dir)
        assert self.base is not None, f'底图缺失: {map_dir}/底图.png'
        self.panel_roi = panel_roi
        self.meta = minimap.load_map_meta(map_dir)
        self.pressed = set()
        self.tracker = minimap.DotTracker()
        self.ops = rl.RouteOps(self.base.shape[:2])
        self.seg_idx = 0
        self.last_pos = None
        self.last_dot_time = 0.0
        self.last_blob = 0.0
        self.jitter = []            # 静止期(无方向键)质心样本,抖动统计
        self.archive = []           # 存档帧
        self.quit = False

    def on_key(self, key, down):
        name = KEY_MAP.get(key) if isinstance(key, keyboard.Key) else None
        if name is None:
            return
        if down:
            self.pressed.add(name)
            if name == 'f3':
                self.ops.undo()
            elif name == 'f4':
                self.ops.clear()
            elif name == 'esc':
                self.quit = True
        else:
            self.pressed.discard(name)

    def calibrate_once(self, frame):
        """首跑标定 → map_meta.json;已有 meta 直接复用但打印匹配分。"""
        panel = frame[self.panel_roi[1]:self.panel_roi[1] + self.panel_roi[3],
                      self.panel_roi[0]:self.panel_roi[0] + self.panel_roi[2]]
        if self.meta is None:
            meta = minimap.calibrate(panel, self.base)
            assert meta is not None, '标定失败:面板折叠/缩放不对/底图不匹配,检查小地图'
            meta['panel_roi'] = self.panel_roi
            minimap.save_map_meta(self.map_dir, meta)
            self.meta = meta
        self.meta['panel_roi'] = self.panel_roi
        print(f"[标定] scale={self.meta['scale']:.2f} offset=({self.meta['offset_x']:.0f},"
              f"{self.meta['offset_y']:.0f}) score={self.meta.get('match_score', 0):.2f}")

    def acquire_once(self, cap):
        """移动捕获:提示用户左右走两步,取位移最大的黄点(spec §2.3)。"""
        print('[捕获] 请在游戏里左右走动两步(3 秒)...')
        before, after = [], []
        t0 = time.time()
        while time.time() - t0 < 3.0:
            frame = cap.get_frame()
            if frame is None:
                continue
            panel = minimap.crop_panel(frame, self.meta)
            dots = minimap.find_yellow_dots(panel)
            if time.time() - t0 < 1.0:
                before.append(dots)
            elif time.time() - t0 > 2.0:
                after.append(dots)
        if before and after:
            pos = self.tracker.acquire(before[-1], after[0], self.meta)
            print(f'[捕获] 自己={pos}')
            return pos is not None
        return False

    def step(self, frame, now):
        panel = minimap.crop_panel(frame, self.meta)
        if len(self.archive) < ARCHIVE_FRAMES and now - self.last_dot_time > 0.5:
            self.archive.append(panel.copy())
        dots = minimap.find_yellow_dots(panel)
        pos, status = self.tracker.update(dots, self.meta, now)
        if pos is not None:
            self.last_dot_time = now
            if not (self.pressed & {'left', 'right', 'up', 'down'}):
                self.jitter.append(pos)
            action = rl.action_for_keys(self.pressed)
            if action is not None:
                if action in rl.WALK_COMMANDS:
                    # 走色画线;黄点丢失超 0.5s 断线不连(spec §5 防垃圾长线)
                    if self.last_pos is not None and now - self.last_dot_time < 0.5:
                        self.ops.draw_line(self.last_pos, pos, action)
                elif rl.blob_ready(now, self.last_blob, BLOB_COOLDOWN):
                    self.ops.draw_blob(pos, action)
                    self.last_blob = now
                if action == rl.GOAL_COMMAND:
                    path = os.path.join(self.map_dir, f'route{self.seg_idx + 1}.png')
                    self.ops.save(path)
                    print(f'[保存] {path}')
                    self.seg_idx += 1
                    self.ops.clear()
            self.last_pos = pos
        else:
            self.last_pos = None  # 丢失断线
        self.show(panel, pos, status)

    def show(self, panel, pos, status):
        base_bgr = self.base[:, :, :3].copy()       # 底图 BGRA → BGR
        layer = self.ops.layer
        over = cv2.addWeighted(base_bgr, 0.5, layer[:, :, :3], 0.5, 0)
        over[layer[:, :, 3] > 0] = layer[layer[:, :, 3] > 0][:, :3]
        if pos is not None:
            cv2.drawMarker(over, (int(pos[0]), int(pos[1])), (0, 255, 255),
                           cv2.MARKER_CROSS, 6, 1)
        big = cv2.resize(over, (over.shape[1] * 6, over.shape[0] * 6),
                         interpolation=cv2.INTER_NEAREST)
        cv2.putText(big, f'seg{self.seg_idx + 1} {status} F2=存段 F3=撤销 F4=放弃 ESC=退',
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.imshow('route_recorder', big)
        cv2.waitKey(1)

    def finish(self):
        """存档帧 + 抖动统计 + 路线校验报告(涂错色)。"""
        arch_dir = os.path.join(self.map_dir, 'archive')
        os.makedirs(arch_dir, exist_ok=True)
        for i, p in enumerate(self.archive):
            minimap.imwrite_unicode(os.path.join(arch_dir, f'panel_{i:03d}.png'), p)
        if len(self.jitter) >= 10:
            arr = np.array(self.jitter)
            dev = np.abs(arr - arr.mean(axis=0)).sum(axis=1)
            stats = {'std': float(dev.std()), 'p95': float(np.percentile(dev, 95)),
                     'n': int(len(dev))}
            with open(os.path.join(self.map_dir, 'jitter_stats.json'), 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            print(f'[抖动] {stats}')
        _segs, unknown = rl.load_routes(self.map_dir)
        if unknown:
            print(f'[校验] {len(unknown)} 个像素不在色表(涂错/抗锯齿),前 5 个: {unknown[:5]}')


if __name__ == '__main__':
    map_name = sys.argv[1] if len(sys.argv) > 1 else '东部岩山5'
    map_dir = os.path.join('minimap', map_name)
    ev, win, cap = build_capture()
    rec = Recorder(map_dir, DEFAULT_PANEL_ROI)
    listener = keyboard.Listener(on_press=lambda k: rec.on_key(k, True),
                                 on_release=lambda k: rec.on_key(k, False))
    listener.start()
    try:
        frame = cap.get_frame()
        rec.calibrate_once(frame)
        rec.acquire_once(cap)
        print('[录制] 开始走动吧')
        while not rec.quit:
            frame = cap.get_frame()
            if frame is not None:
                rec.step(frame, time.time())
            time.sleep(0.1)
    finally:
        rec.finish()
        listener.stop()
        ev.set()
        cv2.destroyAllWindows()
