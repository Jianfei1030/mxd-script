"""路线录制器(spec §5):手动走一遍,按键着色,录出 route*.png。
用法: python scripts/route_recorder.py <地图名>
流程: 标定(首跑)→ 移动捕获 → 录制(F2 存段/F3 撤销/F4 放弃段/ESC 退出)。
前置: 停 GUI(WGC 冲突,AGENTS.md §1.4);游戏窗口前台 2560×1440;小地图展开+约定缩放。
评审修订(2026-08-11): A/B/C 组修复 —— F2 边沿触发(防按住连存)/回调线程只置事件/防键重复/
  goal 落笔+保存一体(绕过 blob 冷却)/last_pos_time 独立断线守卫/存档帧独立节流/捕获重试/
  启动等帧/只对 status=ok 当观测(防 suspect 陈旧坐标污染)/seg_idx 扫描续号/last_saved 撤销已存段/
  draw_line 连续线段合并/英文 HUD/jitter 排除跳跃。"""
import glob
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
ACQUIRE_RETRIES = 3                        # 移动捕获重试次数
WAIT_FRAME_TIMEOUT = 10.0                  # 启动取帧超时(秒)
F2_STALE = 3.0                             # F2 等有效黄点超时(秒)

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
        self.events = []            # 按键边沿事件队列(回调线程只 append,主循环消费,评审 #10)
        self.f2_pending = False     # F2 边沿:已按下,等有效黄点落 goal+保存(评审 #2)
        self.f2_pending_since = 0.0
        self.tracker = minimap.DotTracker()
        self.ops = rl.RouteOps(self.base.shape[:2])
        self.seg_idx = self._existing_route_max()
        self.last_pos = None
        self.last_pos_time = 0.0    # 上次有效观测时刻(画线断线守卫,评审 #4)
        self.last_blob = 0.0
        self.last_archive_t = 0.0   # 存档帧独立节流(评审 #7)
        self.last_saved = None      # (path, ops 深拷贝) 上一已存段(F3 撤销用,评审 #14)
        self.jitter = []            # 静止期(无方向键/跳跃)质心样本,抖动统计
        self.archive = []           # 存档帧
        self.quit = False
        if self.seg_idx > 0:
            print(f'[提示] 已有 route1..route{self.seg_idx}.png,新段从 route{self.seg_idx + 1} '
                  f'开始(重录请先删除旧段,评审 #11)')

    def _existing_route_max(self):
        """已落盘 routeN.png 的最大 N(评审 #11:重跑不覆盖旧段)。"""
        mx = 0
        for p in glob.glob(os.path.join(self.map_dir, 'route*.png')):
            stem = os.path.basename(p)[5:-4]  # 去 'route' 前缀与 '.png'
            if stem.isdigit():
                mx = max(mx, int(stem))
        return mx

    def on_key(self, key, down):
        """pynput 回调(独立线程):只更新 pressed 与事件队列,不动 ops(评审 #10)。"""
        name = KEY_MAP.get(key) if isinstance(key, keyboard.Key) else None
        if name is None:
            return
        if down:
            if name in self.pressed:
                return  # Windows 键自动重复,忽略(评审 #12)
            self.pressed.add(name)
            if name in ('f2', 'f3', 'f4', 'esc'):
                self.events.append(name)
        else:
            self.pressed.discard(name)

    def drain_events(self):
        """主循环消费按键事件;f2 只置位,由 step 落笔。f3/f4/esc 直接处理。"""
        while self.events:
            e = self.events.pop(0)
            if e == 'f3':
                self.do_undo()
            elif e == 'f4':
                self.ops.clear()
            elif e == 'esc':
                self.quit = True
            elif e == 'f2':
                self.f2_pending = True
                self.f2_pending_since = time.time()

    def do_undo(self):
        """F3:当前栈弹栈;栈空且有上一段 → 恢复 last_saved 段(评审 #14:goal 可撤销)。"""
        if self.ops.ops:
            self.ops.undo()
            return
        if self.last_saved is not None:
            path, ops_copy = self.last_saved
            self.ops.ops = [dict(op) for op in ops_copy]
            self.ops._repaint()
            n = int(os.path.basename(path)[5:-4])
            self.seg_idx = n - 1          # 回退段号,改完 F2 重存覆盖
            self.last_saved = None
            print(f'[恢复] 上一段回栈: {path} (可编辑后 F2 重存)')

    def calibrate_once(self, frame):
        """首跑标定 → map_meta.json;已有 meta 直接复用但打印匹配分。"""
        panel = frame[self.panel_roi[1]:self.panel_roi[1] + self.panel_roi[3],
                      self.panel_roi[0]:self.panel_roi[0] + self.panel_roi[2]]
        assert panel.shape[:2] == (self.panel_roi[3], self.panel_roi[2]), \
            f'面板尺寸异常: {panel.shape[:2]},期望 ({self.panel_roi[3]}, {self.panel_roi[2]}),检查分辨率/ROI'
        if self.meta is None:
            meta = minimap.calibrate(panel, self.base)
            assert meta is not None, '标定失败:面板折叠/缩放不对/底图不匹配,检查小地图'
            meta['panel_roi'] = self.panel_roi
            minimap.save_map_meta(self.map_dir, meta)
            self.meta = meta
        self.meta['panel_roi'] = self.panel_roi
        print(f'[标定] scale={self.meta["scale"]:.2f} offset=({self.meta["offset_x"]:.0f},'
              f'{self.meta["offset_y"]:.0f}) score={self.meta.get("match_score", 0):.2f}')

    def acquire_once(self, cap):
        """移动捕获:提示用户左右走两步,取位移最大的黄点(spec §2.3)。
        播种用最新帧点(after[-1])并传 now,避免首拍 dt=0 楔死 suspect(评审 #1)。"""
        print('[捕获] 请在游戏里左右走动两步(3 秒)...')
        before, after = [], []
        t0 = time.time()
        while time.time() - t0 < 3.0:
            frame = cap.get_frame()
            if frame is None:
                continue
            panel = minimap.crop_panel(frame, self.meta)
            dots = minimap.find_yellow_dots(panel)
            t = time.time()
            if t - t0 < 1.0:
                before.append(dots)
            elif t - t0 > 2.0:
                after.append(dots)
        if before and after:
            pos = self.tracker.acquire(before[-1], after[-1], self.meta, now=time.time())
            print(f'[捕获] 自己={pos}')
            return pos is not None
        return False

    def step(self, frame, now):
        panel = minimap.crop_panel(frame, self.meta)
        if len(self.archive) < ARCHIVE_FRAMES and now - self.last_archive_t >= 0.5:
            self.archive.append(panel.copy())
            self.last_archive_t = now
        dots = minimap.find_yellow_dots(panel)
        pos, status = self.tracker.update(dots, self.meta, now)
        if status == 'ok':  # 只对可信观测计数/落笔/连线(suspect 是拒采,评审 #5)
            if not (self.pressed & {'left', 'right', 'up', 'down', 'space'}):
                self.jitter.append(pos)
            if self.f2_pending:
                # F2 存段:goal 落笔+保存一体,绕过 blob 冷却(评审 #3);等黄点超时丢弃
                if now - self.f2_pending_since > F2_STALE:
                    print('[提示] F2 按下但黄点一直不可信,未存段')
                    self.f2_pending = False
                else:
                    self.ops.draw_blob(pos, rl.GOAL_COMMAND)
                    self._save_segment()
                    self.f2_pending = False
            else:
                action = rl.action_for_keys(self.pressed - {'f2'})  # f2 由边沿消费(评审 #2)
                if action is not None:
                    if action in rl.WALK_COMMANDS:
                        # 走色画线;距上次有效观测超 0.5s 断线不连(评审 #4:last_pos_time 独立)
                        if self.last_pos is not None and now - self.last_pos_time < 0.5:
                            self.ops.draw_line(self.last_pos, pos, action)
                    elif rl.blob_ready(now, self.last_blob, BLOB_COOLDOWN):
                        self.ops.draw_blob(pos, action)
                        self.last_blob = now
            self.last_pos = pos
            self.last_pos_time = now
        else:
            self.last_pos = None  # suspect/lost 断线,不可信位置不连线
        self.show(panel, pos, status)

    def _save_segment(self):
        """F2 存段:goal 已落笔 → 保存 → 记录 last_saved → 清栈进下一段。"""
        path = os.path.join(self.map_dir, f'route{self.seg_idx + 1}.png')
        self.ops.save(path)
        self.last_saved = (path, [dict(op) for op in self.ops.ops])
        print(f'[保存] {path}')
        self.seg_idx += 1
        self.ops.clear()

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
        cv2.putText(big, f'seg{self.seg_idx + 1} {status} F2=save F3=undo F4=drop ESC=quit',
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


def wait_frame(cap, timeout=WAIT_FRAME_TIMEOUT):
    """WGC 未就绪可能返回 None;等到首帧有效(评审 #9)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        frame = cap.get_frame()
        if frame is not None:
            return frame
        time.sleep(0.1)
    return None


if __name__ == '__main__':
    map_name = sys.argv[1] if len(sys.argv) > 1 else '东部岩山5'
    map_dir = os.path.join('minimap', map_name)
    ev, win, cap = build_capture()
    rec = Recorder(map_dir, DEFAULT_PANEL_ROI)
    listener = keyboard.Listener(on_press=lambda k: rec.on_key(k, True),
                                 on_release=lambda k: rec.on_key(k, False))
    listener.start()
    try:
        frame = wait_frame(cap)
        if frame is None:
            print(f'[启动] {WAIT_FRAME_TIMEOUT:.0f} 秒内未取到帧(游戏未开/窗口未就绪?),退出')
            sys.exit(1)
        rec.calibrate_once(frame)
        for attempt in range(1, ACQUIRE_RETRIES + 1):
            if rec.acquire_once(cap):
                break
            print(f'[捕获] 第 {attempt} 次未捕获,重试...')
        else:
            print(f'[捕获] 连续 {ACQUIRE_RETRIES} 次失败,退出(确认角色在走动、小地图黄点可见)')
            sys.exit(1)
        print('[录制] 开始走动吧')
        while not rec.quit:
            frame = cap.get_frame()
            if frame is None:
                time.sleep(0.1)
                continue
            rec.drain_events()
            rec.step(frame, time.time())
            time.sleep(0.1)
    finally:
        rec.finish()
        listener.stop()
        ev.set()
        cv2.destroyAllWindows()
