import time

from qfluentwidgets import FluentIcon
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

from ok import Logger, TriggerTask
from src.detect import anchor
from src.task import farm_logic
from src.task.BaseMapleTask import BaseMapleTask

logger = Logger.get_logger(__name__)

# Phase 1 只读不按键:WarriorDebugTask 独立于 MapleFarmTask,不 share 状态。
# 配置值均为初始默认,玩家宽/高/攻击距离/名字牌偏移待标定(见 spec §3.6)。
DEFAULT_CONFIG = {
    '调试开关': False,
    '调试刷新间隔(秒)': 0.3,
    '朝向': '自动',          # 左/右/自动
    '角色名': '',
    '名字牌到身体偏移': 90,
    '玩家宽': 60,
    '玩家高': 120,
    '攻击距离': 120,
    '攻击区高': 200,
    '寻怪同层容差(像素)': 150,
    # 画框开关(默认全开,按需关闭)
    '显示怪物框': True,
    '显示玩家框': True,
    '显示攻击区': True,
    '显示名字搜索范围': True,
    '显示寻怪同层带': True,
}

# 玩家朝向推断:名字牌 x 位移超过该阈值才计入朝向位移(OCR 噪声约 ±5px,留 3 倍余量)
MOVE_X_THRESHOLD = 15
# 连续同向位移 ≥ 此帧数才翻转朝向(两拍确认:单拍位移/噪声不翻,压住 OCR 抖动)
FACING_CONFIRM_FRAMES = 2
# 快通道小窗半宽/半高(±240x±80,与 attack-zone spec §4.2 一致)
WINDOW_HALF_W = 240
WINDOW_HALF_H = 80
# 怪物 bbox 颜色(黄)/脚底点颜色
MOB_COLOR = QColor(255, 255, 0)
MOB_FOOT_COLOR = QColor(0, 255, 255)
# 玩家 bbox 绿 / 攻击区蓝(无怪)红(怪进区)
PLAYER_COLOR = QColor(0, 255, 0)
ZONE_IDLE_COLOR = QColor(0, 128, 255)
ZONE_HOT_COLOR = QColor(255, 0, 0)
# 名字检测范围(蓝虚线)/寻怪同层高度带(青虚线):均虚线,调试画框用
ANCHOR_SEARCH_COLOR = QColor(0, 0, 255)
SEEK_BAND_COLOR = QColor(0, 255, 255)


class WarriorDebugTask(TriggerTask, BaseMapleTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "战士调试"
        self.description = "只读可视化:玩家/攻击范围/怪物 bbox,怪进范围攻击框变色"
        self.icon = FluentIcon.VIEW
        self.trigger_interval = 0.1  # 10Hz 轮询,节流在 run 内做
        self.default_config.update(DEFAULT_CONFIG)
        from ok.gui.Communicate import communicate
        communicate.executor_paused.connect(self._on_executor_paused)
        self._reset_state()

    def _reset_state(self):
        self._anchor = None        # 上一可信锚点(名字牌中心)
        self._facing = 'RIGHT'     # 无历史默认 RIGHT(spec §3.4)
        self._facing_dx_sign = 0   # 上拍位移符号(1 右/-1 左/0 静止),朝向滞回用
        self._facing_dx_frames = 0  # 连续同向位移帧数
        self._last_draw = 0.0

    def enable(self):
        self._reset_state()
        super().enable()

    def _on_executor_paused(self, paused):
        """F9 全局暂停时清掉 overlay,避免暂停后调试框残留在游戏画面上。"""
        if paused:
            try:
                self.get_overlay_view().clear_draw('warrior_debug')
            except Exception as e:
                logger.warning(f'clear_draw failed: {e}')

    def on_disable(self):
        """停止时清掉 overlay,避免残影。"""
        try:
            self.get_overlay_view().clear_draw('warrior_debug')
        except Exception as e:
            logger.warning(f'clear_draw failed: {e}')
        super().on_disable()

    def run(self):
        frame = self.frame
        if frame is None:
            return
        cfg = self.config
        if not cfg.get('调试开关'):
            return

        now = time.time()
        if now - self._last_draw < cfg['调试刷新间隔(秒)']:
            return

        character_name = (cfg.get('角色名') or '').strip()
        if not character_name:
            self._debug_text('请先在配置里填写角色名')
            return
        h, w = frame.shape[:2]
        if self._anchor is None:
            # 首次:中央区慢扫定位(名字牌在角色脚下,搜索区 0.70x0.70:
            # 0.50 时角色站高处/海拔变化名字牌易出区,2026-08-08 实测调大)
            hit = anchor.find_in_region(
                frame, character_name, anchor.search_region(w, h, 0.70, 0.70))
            if hit is None:
                self._debug_text('未找到名字牌:请确认角色名与画面')
                return
            # 位置合理性校验:名字牌应在画面中心 ±30% 范围内,防止匹配到右侧组队列表/UI文字
            cx, cy = w / 2.0, h * 0.55
            dx_ratio = abs(hit.x - cx) / (w * 0.30)
            dy_ratio = abs(hit.y - cy) / (h * 0.30)
            if dx_ratio > 1.0 or dy_ratio > 1.0:
                self._debug_text(f'名字牌位置异常(x={hit.x:.0f},y={hit.y:.0f}),已过滤;请确认角色名')
                return
            self._anchor = hit
            self._last_draw = now
            self._draw_debug(frame, cfg, facing=self._facing, in_zone=False, mobs=[])
            return

        # 快通道小窗刷新;失败沿用上一可信锚点(spec §4.2 步骤 4)
        hit = anchor.find_in_window(
            frame, character_name, (self._anchor.x, self._anchor.y),
            WINDOW_HALF_W, WINDOW_HALF_H)
        if hit is not None:
            self._facing = self._resolve_facing(cfg, hit)
            self._anchor = hit

        mobs = self.find_mobs(frame)
        body_center = anchor.body_center(self._anchor, cfg['名字牌到身体偏移'])
        zone = farm_logic.warrior_attack_zone(
            body_center, self._facing, cfg['攻击距离'], cfg['攻击区高'])
        in_zone = any(farm_logic.mob_feet_in_zone(mob, zone) for mob in mobs)
        self._last_draw = now
        self._draw_debug(frame, cfg, facing=self._facing, in_zone=in_zone, mobs=mobs)

    def _resolve_facing(self, cfg, hit):
        """朝向解析(spec §3.3 优先级):①手动 左/右 优先;②自动 = 移动推断;③无历史默认 RIGHT。"""
        manual = (cfg.get('朝向') or '').strip()
        if manual == '左':
            return 'LEFT'
        if manual == '右':
            return 'RIGHT'
        return self._auto_facing(hit)

    def _auto_facing(self, hit):
        """朝向自动推断:连续两拍同向位移(>阈值)才翻转,单拍位移/噪声不翻(两拍确认)。
        被击退后的朝向翻转由生产链路(MapleFarmTask 受击检测)处理,这里只负责
        走位朝向的稳健跟踪,不追求对击退事件的即时响应。"""
        if self._anchor is None:
            return self._facing
        dx = hit.x - self._anchor.x
        sign = 1 if dx > MOVE_X_THRESHOLD else (-1 if dx < -MOVE_X_THRESHOLD else 0)
        if sign != 0 and sign == self._facing_dx_sign:
            self._facing_dx_frames += 1
        else:
            self._facing_dx_sign = sign
            self._facing_dx_frames = 1 if sign != 0 else 0
        if self._facing_dx_frames >= FACING_CONFIRM_FRAMES:
            return 'RIGHT' if self._facing_dx_sign > 0 else 'LEFT'
        return self._facing

    def _debug_text(self, text):
        logger.info(text)
        overlay = self.get_overlay_view()
        if overlay is not None:
            overlay.draw('warrior_debug', lambda painter, w: self._paint_text(painter, text))

    @staticmethod
    def _paint_text(painter, text):
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawText(QRectF(10, 10, 800, 40), text)

    def _draw_debug(self, frame, cfg, facing, in_zone, mobs):
        from ok import og
        if getattr(og, 'executor', None) is not None and getattr(og.executor, 'paused', False):
            # F9 暂停瞬间 executor 线程可能仍跑最后一拍,禁止再画(否则 draw 信号排队,
            # 在清理 clear_draw 之后到达主线程 → 残留最后一帧的框)
            return
        ok_config = getattr(og.app, 'ok_config', None)
        if ok_config is not None and not ok_config.get('use_overlay', False):
            # 关闭「启用标记框」时不绘制,并清掉上次残留,避免关闭后仍显示旧框
            overlay = self.get_overlay_view()
            if overlay is not None:
                overlay.clear_draw('warrior_debug')
            return
        overlay = self.get_overlay_view()
        if overlay is None:
            return
        body_center = anchor.body_center(self._anchor, cfg['名字牌到身体偏移'])
        zone = farm_logic.warrior_attack_zone(
            body_center, facing, cfg['攻击距离'], cfg['攻击区高'])
        pw, ph = cfg['玩家宽'], cfg['玩家高']
        zone_color = ZONE_HOT_COLOR if in_zone else ZONE_IDLE_COLOR
        # 名字检测范围(蓝虚线):与 run() 首次慢扫同值 0.70;寻怪同层带(青虚线):
        # 以名字牌 y 为中线 ±容差,怪脚底落带内 = 会自动走过去(与 MapleFarmTask 同语义)
        w, h = frame.shape[1], frame.shape[0]
        search = anchor.search_region(w, h, 0.70, 0.70)
        tol = cfg['寻怪同层容差(像素)']
        feet_y = self._anchor.y

        def paint(painter, widget):
            if getattr(og, 'executor', None) is not None and getattr(og.executor, 'paused', False):
                return
            painter.setBrush(Qt.NoBrush)
            ratio = widget.frame_ratio()
            # 每帧读最新配置(GUI 改开关后可能重建 dict 对象,闭包捕获的 cfg 会过期)
            c = self.config

            def rect(x, y, w, h):
                return QRectF(x * ratio, y * ratio, w * ratio, h * ratio)

            if c.get('显示名字搜索范围', True):
                painter.setPen(QPen(ANCHOR_SEARCH_COLOR, 2, Qt.PenStyle.DashLine))
                painter.drawRect(rect(search[0], search[1], search[2] - search[0], search[3] - search[1]))
            if c.get('显示寻怪同层带', True):
                painter.setPen(QPen(SEEK_BAND_COLOR, 2, Qt.PenStyle.DashLine))
                painter.drawRect(rect(0, feet_y - tol, w, 2 * tol))
            if c.get('显示玩家框', True):
                painter.setPen(QPen(PLAYER_COLOR, 2))
                painter.drawRect(rect(body_center[0] - pw / 2, body_center[1] - ph / 2, pw, ph))
            if c.get('显示攻击区', True):
                painter.setPen(QPen(zone_color, 3))
                painter.drawRect(rect(zone[0], zone[1], zone[2], zone[3]))
            if c.get('显示怪物框', True):
                painter.setPen(QPen(MOB_COLOR, 2))
                for mob in mobs:
                    painter.drawRect(rect(mob.x, mob.y, mob.width, mob.height))
                    fx, fy = farm_logic.mob_feet(mob)
                    painter.setPen(QPen(MOB_FOOT_COLOR, 4))
                    painter.drawPoint(QPointF(fx * ratio, fy * ratio))
                    painter.setPen(QPen(MOB_COLOR, 2))

        overlay.draw('warrior_debug', paint)
