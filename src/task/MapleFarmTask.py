import time

from qfluentwidgets import FluentIcon
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPen

from ok import Logger, TriggerTask
from ok.gui.Communicate import communicate
from src.detect import anchor, bars, guards, ocr_engine, potions
from src.task import farm_logic
from src.task.BaseMapleTask import BaseMapleTask

logger = Logger.get_logger(__name__)

# 模块级默认配置:__init__ 与离线测试共用同一份,新增键只改这里
DEFAULT_CONFIG = {
    '攻击间隔(秒)': 1.5,
    '喝血阈值': 0.7,
    '喝蓝阈值': 0.35,
    '保命血线': 0.25,
    '死亡判定线': 0.02,
    '死亡确认帧数': 20,
    '喝药无效上限': 5,
    '喝药判定间隔(秒)': 1.0,
    '喝药开关': True,
    '药水检查间隔(秒)': 30,
    '药水耗尽保护': True,
    '拾取开关': False,
    '拾取间隔(秒)': 30,
    '喂宠物开关': True,
    '喂宠物间隔(秒)': 900,
    '坐椅开关': True,
    '坐椅延迟(秒)': 3.0,
    '画面静止上限(秒)': 60,
    '经验停滞上限(分钟)': 10,
    '攻击模式': '检测',
    '角色名': '',
    '攻击区宽(像素)': 600,
    '攻击区高(像素)': 200,
    '名字牌到身体偏移(像素)': 90,
    '锚点搜索区宽(比例)': 0.30,
    '锚点搜索区高(比例)': 0.30,
    '锚点搜索区中心Y(比例)': 0.55,
    '锚点刷新间隔(秒)': 2,
    '锚点保鲜(秒)': 10,
    '走位持续时间(秒)': 0.4,
    '走位开关': True,
    '走位间隔(秒)': 120,
    '朝向': '自动',
    '寻怪开关': True,
    '寻怪同层容差(像素)': 60,
    '寻怪刷新间隔(秒)': 0.4,
    '寻怪外推速度(像素/秒)': 250,
    '玩家宽(像素)': 60,
    '玩家高(像素)': 120,
}

CALIBRATED_SIZE = (2560, 1440)  # 只在此分辨率挂机(README 约束)

FAST_HALF_W = 240        # 快通道搜索窗半宽(像素)
FAST_HALF_H = 80         # 快通道搜索窗半高
ANCHOR_EXTRAPOLATE_MIN_AGE = 0.5  # 锚点年龄 ≥ 此值才开始外推:新鲜锚点不需要推
ANCHOR_VX_MAX_AGE = 2.0           # 实测速度在此窗口内可信,超时退化用配置速度
ANCHOR_VX_MAX_SPEED = 600         # 实测速度上限(像素/秒):跳变 = 回退/误检,不学
ANCHOR_VX_PLATFORM_DY = 30        # 名字牌 y 位移超此值视为换平台,不学速度
ANCHOR_DEFAULT_SPEED = 250        # 无实测速度时的水平外推速度(像素/秒)
FALLBACK_WARN_INTERVAL = 60   # 回退屏幕中心的告警最小间隔(秒),防刷屏
DETECT_ERROR_LOG_INTERVAL = 60   # 检测(OCR/YOLO)异常日志最小间隔(秒),10Hz 主循环下不限频会刷爆日志
TURN_TAP_SECONDS = 0.05  # 转向轻点:方向键按 50ms 即翻转朝向,位移可忽略(约几像素,方向随怪侧轮换不累积)

DEBUG_OVERLAY_KEY = 'maple_farm_debug'   # 调试 overlay 的画笔 key,与 WarriorDebugTask 的 'warrior_debug' 互不干扰
PLAYER_COLOR = QColor(0, 255, 0)
ZONE_IDLE_COLOR = QColor(0, 128, 255)
ZONE_HOT_COLOR = QColor(255, 0, 0)
MOB_COLOR = QColor(255, 255, 0)
MOB_FOOT_COLOR = QColor(0, 255, 255)


class MapleFarmTask(TriggerTask, BaseMapleTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # F9 全局暂停时 executor 不再调用 run(),长按的方向键必须在这里松,
        # 否则角色会在暂停期间一直走下去
        communicate.executor_paused.connect(self._on_executor_paused)
        self.name = "自动打怪"
        self.description = "站桩定频攻击+自动喝药+低血保命"
        self.icon = FluentIcon.GAME
        self.trigger_interval = 0.1  # ~10Hz 轮询,保命响应足够快
        self.default_config.update(DEFAULT_CONFIG)
        self.config_type['攻击模式'] = {'type': 'drop_down', 'options': ['定频', '检测']}
        self.config_type['朝向'] = {'type': 'drop_down', 'options': ['自动', '左', '右']}
        self.config_description.update({
            '攻击间隔(秒)': '定频模式:攻击按键节奏。检测模式:完整检测拍(锚点OCR+YOLO)的节流——攻击本身长按持续,不再受此限制',
            '角色名': '检测模式用它 OCR 定位角色(名字牌)。留空则攻击区锚在画面中心',
            '攻击区宽(像素)': '2560x1440 下标定。用 scripts/calibrate_attack_zone.py 看图调',
            '名字牌到身体偏移(像素)': '名字牌在角色脚下,该值是牌子中心到身体中心的距离',
            '喝药判定间隔(秒)': 'HP 低于阈值时,两次喝药/判效的最小间隔。药水起效需要时间,间隔太短会误判"喝药无效"',
            '喝药开关': '总开关:关闭后不自动喝血/喝蓝;保命时也不按血药键(回城卷与停任务照常)',
            '朝向': '走位(防挂机)结束后面朝哪边:左/右显式指定(推荐);自动 = 首次走位后采纳实际朝向',
            '喂宠物开关': '到点自动按宠物食物键喂宠物(需先在游戏内把宠物食物拖到快捷键,再在设置页「游戏按键」绑定)',
            '坐椅开关': '检测模式没怪时自动坐椅子回血蓝(需先在游戏内把椅子拖到快捷键,再在设置页「游戏按键」绑定椅子键)',
            '坐椅延迟(秒)': '闲置这么久才坐下,避免怪一刷新就起来坐下反复横跳',
            '喂宠物间隔(秒)': '喂宠物的最小间隔,默认 15 分钟一次',
            '寻怪开关': '同层有怪但都在攻击区外时,自动朝最近的怪走近并攻击(仅检测模式)',
            '寻怪同层容差(像素)': '判定"同一层"的高度容差:怪脚底与角色名字牌高度差在此范围内才走近,避免追到别的平台',
            '寻怪刷新间隔(秒)': '寻怪中刷新目标方向的最小间隔:越小追怪换目标/接战越快,但 YOLO 跑得越勤;空闲与原地攻击时不受影响',
            '寻怪外推速度(像素/秒)': '寻怪中名字牌被怪遮挡、OCR 连续失败时,攻击区按此速度跟随走动中的角色(水平外推),怪进区即可接战;名字牌一露头快通道立刻重新咬住。无实测速度时用此值,实测行走速度约 250',
            '玩家宽(像素)': '仅用于调试可视化画框(勾选 GUI「启用标记框」时显示),不影响攻击判定',
            '玩家高(像素)': '同「玩家宽(像素)」,仅调试画框用',
        })
        self._reset_state()

    def _reset_state(self):
        """全部可变运行时状态。__init__ 与测试共用,新增状态只改这里。"""
        self._last_attack = 0.0
        self._last_pickup = 0.0
        self._last_pet_feed = 0.0
        self._hp_streak = 0
        self._hp_at_press = 0.0           # 上次按下药键时的 HP,作窗口判定的基线
        self._last_hp_potion_press = 0.0  # 上次按下药键时刻;0.0 哨兵=尚无上一窗口,只记基线不判无效
        self._dead_frames = 0
        self._bad_size_frames = 0
        self._last_potion_check = 0.0
        self._last_sig = None
        self._last_change_time = 0.0
        self._last_exp = None
        self._last_exp_gain_time = 0.0
        self._anchor = None            # (x, y) 名字牌中心,全帧坐标
        self._anchor_time = None
        self._anchor_vx = 0.0          # 名字牌实测水平速度(像素/秒),低通学习;0.0=无实测
        self._last_anchor_hit = 0.0    # 上次快/慢通道命中锚点的时刻;0.0 哨兵=从未命中
        self._last_anchor_scan = 0.0
        self._last_detect = 0.0
        self._last_fallback_warn = 0.0
        self._last_detect_error_log = 0.0
        self._last_walk = 0.0
        self._last_mob_present = None
        self._facing = None           # 角色面朝方向;None=未知(首次走位前),配置 左/右 时走位前由配置定
        self._seek_dir = None         # 自动寻怪目标方向 'left'/'right';None=不寻怪(区内有怪/无同层怪/开关关)
        self._last_seek_refresh = 0.0  # 寻怪中快速刷新目标方向的节流时刻
        self._seek_key = None         # 寻怪长按中按下的方向键名('左移键'/'右移键');None=未按住
        self._attack_held = False     # 攻击键是否长按中(检测模式,区内有怪时按住连续挥砍)
        self._sitting = False         # 本轮闲置是否已按过椅子键(再按一次会起身,只能按一次)
        self._last_busy = 0.0         # 最近一次"忙"(攻击/寻怪/走位)时刻,坐椅延迟按它算
        self._debug_drawn = False      # 调试 overlay 当前是否已画(True 时开关关掉/模式切换才需要真的调 clear_draw)

    def enable(self):
        """每次被用户/框架重新启用时复位运行时状态,防止上次停止的计时器秒停。"""
        self._reset_state()
        super().enable()

    def on_create(self):
        super().on_create()
        if self.config.get('药水耗尽保护') and self.config.get('喝药开关'):
            potions.prewarm()
        if self.config.get('攻击模式') == '检测' and (self.config.get('角色名') or '').strip():
            ocr_engine.prewarm()

    def _log_detect_error(self, now, context, exc):
        """检测环节(OCR/YOLO)异常限频记录,防 10Hz 主循环下刷爆日志。

        不许静默吞异常:异常发生时按"这一级没检测到"降级处理(继续沿阶梯往下走/停手),
        但必须留痕,否则模型持续报错会在用户毫无察觉的情况下一直退化运行。
        """
        if now - self._last_detect_error_log >= DETECT_ERROR_LOG_INTERVAL:
            self._last_detect_error_log = now
            self.log_error(f'{context}异常,本次按未检测到处理(不影响任务继续运行): {exc!r}', exception=exc)

    def _update_anchor(self, hit, now):
        """任一通道命中 → 更新锚点,并低通学习实测水平速度(学习条件见
        farm_logic.anchor_vx_update:dt 窗口内、非换平台、速率不跳变)。
        实测速度是外推的优先依据:外推准不准全靠它(配置速度只是兜底)。"""
        if self._anchor is not None and self._anchor_time is not None:
            dt = now - self._anchor_time
            dx = hit.x - self._anchor[0]
            dy = abs(hit.y - self._anchor[1])
            self._anchor_vx = farm_logic.anchor_vx_update(self._anchor_vx, dx, dt, dy)
        self._anchor, self._anchor_time = (hit.x, hit.y), now
        self._last_anchor_hit = now

    def _extrapolated_anchor_x(self, now, cfg):
        """寻怪中锚点超龄 → 角色此刻应在的水平 x(实测速度优先,无实测用配置速度 × 寻怪方向)。

        只在"正在寻怪(角色在走动)"时推:站桩外推只会把攻击区推离原地;
        锚点新鲜(年龄 < 0.5s)不推——刚命中过,位置就是真值,推了反而引入误差;
        已过期(年龄 > 保鲜)不推——位置本身已不可信,交给回退分支。
        返回值钳在 [0, 2560] 内,极端外推不出帧。
        """
        if self._seek_dir is None or self._anchor is None or self._anchor_time is None:
            return self._anchor[0] if self._anchor is not None else None
        age = now - self._anchor_time
        if age < ANCHOR_EXTRAPOLATE_MIN_AGE or age > cfg['锚点保鲜(秒)']:
            return self._anchor[0]
        if now - self._last_anchor_hit <= ANCHOR_VX_MAX_AGE and self._anchor_vx != 0.0:
            vx = self._anchor_vx
        else:
            speed = cfg.get('寻怪外推速度(像素/秒)', ANCHOR_DEFAULT_SPEED)
            vx = speed if self._seek_dir == 'right' else -speed
        return max(0.0, min(CALIBRATED_SIZE[0], self._anchor[0] + vx * age))

    def _resolve_anchor(self, frame, now, cfg):
        """按四级阶梯拿角色锚点,返回 (Anchor, 来源标签)。任何一级都不停任务。

        快通道(上次锚点附近小窗,寻怪中超龄时小窗跟外推位置) → 慢通道(中央区分块,节流)
        → 沿用上次(寻怪中超龄则按外推位置回) → 回退(屏幕中心 x + 最后已知层高 y)。
        怪堆里名字牌被遮挡 OCR 连续失败时,攻击区不再冻在旧位置——角色边走路边外推,
        怪进区就能接战(2026-08-06 实测"身边很多怪时一直寻怪不攻击"根因,spec §4.2)。
        OCR 调用可能抛异常(模型/引擎故障等),任一通道抛出都当作"这一级没拿到锚点"处理,
        绝不允许异常冒泡出去——冒泡到 run() 外层会被框架 TaskExecutor 的通用 except 抓住并
        直接 disable() 整个任务,连保命/喝药都会停,违反"无怪只停手,任务继续跑"的契约。
        """
        h, w = frame.shape[:2]
        centre = anchor.Anchor(w / 2.0, h / 2.0, 0)
        name = (cfg['角色名'] or '').strip()
        if not name:
            return centre, 'fallback'

        if self._anchor is not None:
            search_x = self._extrapolated_anchor_x(now, cfg)
            try:
                hit = anchor.find_in_window(frame, name, (search_x, self._anchor[1]),
                                            FAST_HALF_W, FAST_HALF_H)
            except Exception as e:
                hit = None
                self._log_detect_error(now, '快通道锚点 OCR', e)
            if hit is not None:
                self._update_anchor(hit, now)
                return hit, 'window'

        if farm_logic.should_rescan_anchor(now, self._last_anchor_scan, cfg['锚点刷新间隔(秒)']):
            self._last_anchor_scan = now
            region = anchor.search_region(w, h, cfg['锚点搜索区宽(比例)'], cfg['锚点搜索区高(比例)'],
                                          cfg['锚点搜索区中心Y(比例)'])
            try:
                hit = anchor.find_in_region(frame, name, region)
            except Exception as e:
                hit = None
                self._log_detect_error(now, '慢通道锚点 OCR', e)
            if hit is not None:
                self._update_anchor(hit, now)
                return hit, 'region'

        if not farm_logic.anchor_expired(now, self._anchor_time, cfg['锚点保鲜(秒)']):
            x = self._extrapolated_anchor_x(now, cfg)
            return anchor.Anchor(x, self._anchor[1], 0), 'cached'

        if now - self._last_fallback_warn >= FALLBACK_WARN_INTERVAL:
            self._last_fallback_warn = now
            self.log_warning(f'{cfg["锚点保鲜(秒)"]}s 未定位到角色「{name}」,攻击区锚在画面中心,'
                             f'纵向保留最后已知层高')
        # 名字牌 y 同平台极稳定(实测 887-888,差 1-2px),回退保留 y 才能罩住脚下这层怪;
        # 纯屏幕中心 y=720 比实测层高 ~165px,怪全在攻击区外(2026-08-06 实测"怪堆里坐下")
        return anchor.Anchor(w / 2.0, self._anchor[1] if self._anchor is not None else h / 2.0, 0), 'fallback'

    @staticmethod
    def _slot_of(key_name):
        return key_name.lower()

    def _boxes_enabled(self):
        """GUI Start 页「启用标记框」(Enable Boxes)全局开关的读法,
        与 ok/feature/FeatureSet.py::_draw_boxes_enabled 同一套(og.app.ok_config['use_overlay'])。
        无 GUI/未初始化(离线测试、og.app 尚为 None)时安全降级为 False,不抛异常。"""
        from ok import og
        app = getattr(og, 'app', None)
        ok_config = getattr(app, 'ok_config', None)
        if ok_config is None:
            return False
        return bool(ok_config.get('use_overlay', False))

    def _clear_debug(self):
        """清掉已画的调试 overlay(没画过则什么都不做)。get_overlay_view 失败/返回 None
        都容错——清理动作不能把主循环搞崩。"""
        if not self._debug_drawn:
            return
        try:
            overlay = self.get_overlay_view()
            if overlay is not None:
                overlay.clear_draw(DEBUG_OVERLAY_KEY)
        except Exception as e:
            self.log_error(f'调试 overlay 清除失败: {e!r}')
        self._debug_drawn = False

    def _draw_debug(self, cfg, body, zone, mobs, mob_present):
        """画玩家框(绿)/攻击区框(蓝=无怪,红=有怪)/怪物框(黄)+脚底点(青)。
        画法照抄 WarriorDebugTask._draw_debug 的 get_overlay_view().draw + frame_ratio 换算,
        用独立 key(DEBUG_OVERLAY_KEY),与 WarriorDebugTask 的 overlay 互不影响。"""
        overlay = self.get_overlay_view()
        if overlay is None:
            return
        pw, ph = cfg['玩家宽(像素)'], cfg['玩家高(像素)']
        zx0, zy0, zx1, zy1 = zone
        zone_color = ZONE_HOT_COLOR if mob_present else ZONE_IDLE_COLOR

        def paint(painter, widget):
            ratio = widget.frame_ratio()

            def rect(x, y, w, h):
                return QRectF(x * ratio, y * ratio, w * ratio, h * ratio)

            painter.setPen(QPen(PLAYER_COLOR, 2))
            painter.drawRect(rect(body[0] - pw / 2, body[1] - ph / 2, pw, ph))
            painter.drawText(rect(body[0] - pw / 2, body[1] - ph / 2 - 20, 100, 20), '玩家')

            painter.setPen(QPen(zone_color, 3))
            painter.drawRect(rect(zx0, zy0, zx1 - zx0, zy1 - zy0))
            painter.drawText(rect(zx0, zy0 - 20, 100, 20), '攻击区')

            for mob in mobs:
                painter.setPen(QPen(MOB_COLOR, 2))
                painter.drawRect(rect(mob.x, mob.y, mob.width, mob.height))
                painter.drawText(rect(mob.x, mob.y - 20, 100, 20), '怪物')
                fx, fy = farm_logic.mob_feet(mob)
                painter.setPen(QPen(MOB_FOOT_COLOR, 4))
                painter.drawPoint(rect(fx, fy, 1, 1))

        overlay.draw(DEBUG_OVERLAY_KEY, paint)
        self._debug_drawn = True

    def _resolve_facing(self):
        """走位用朝向:配置 朝向=左/右 显式优先(中途改配置立即生效);自动 → 已跟踪的 _facing。"""
        manual = (self.config.get('朝向') or '').strip()
        if manual == '左':
            return 'LEFT'
        if manual == '右':
            return 'RIGHT'
        return self._facing

    def _detect_and_act(self, frame, now, cfg, keys):
        """一个检测拍:锚点 → 找怪 → 区内有怪则转向接战,否则确定寻怪方向。

        完整检测拍与寻怪快速刷新拍共用。攻击键本身不在这里按——由 _do_attack_hold
        按"_last_mob_present"长按接管(每拍都重按保持,游戏按动画速度连续挥砍)。"""
        anchor_hit, source = self._resolve_anchor(frame, now, cfg)
        body = anchor.body_center(anchor_hit, cfg['名字牌到身体偏移(像素)'])
        zone = farm_logic.attack_zone(body, cfg['攻击区宽(像素)'], cfg['攻击区高(像素)'])
        try:
            mobs = self.find_mobs(frame)
        except Exception as e:
            mobs = []
            self._log_detect_error(now, 'YOLO 找怪', e)
        centres = [(m.x + m.width / 2, m.y + m.height / 2) for m in mobs]
        mob_present = farm_logic.mob_in_zone(centres, zone)
        self._last_mob_present = mob_present
        if self._boxes_enabled():
            self._draw_debug(cfg, body=body, zone=zone, mobs=mobs, mob_present=mob_present)
        else:
            self._clear_debug()
        if mob_present:
            self._seek_dir = None  # 怪进攻击区了,停追,原地攻击
            # 面向怪再攻击:怪在面朝反侧(或朝向未知)时先轻点方向键转向。
            # 战士只能打面朝方向,朝向错攻击必然打空;转向后 _facing 随怪侧更新,
            # 之后的走位与攻击都按此朝向保持(方案 2,spec §4.4 HUNTING 前置)。
            # 攻击键本身由 _do_attack_hold 长按接管,不在这里轻点
            turn = farm_logic.turn_direction(self._facing, body[0],
                                             farm_logic.nearest_mob_x(centres, zone, body[0]))
            if turn is not None:
                key = '左移键' if turn == 'left' else '右移键'
                self.send_key(keys[key], down_time=TURN_TAP_SECONDS)
                self._facing = 'LEFT' if turn == 'left' else 'RIGHT'
                # 转向本身就是"活动":走位倒计时从头算,不紧跟着又走位
                # (刚转完向立刻两段走位会显得很怪;且正在打怪就不是挂机闲逛)
                self._last_walk = now
        else:
            # 自动寻怪:区内没怪 → 在同层(脚底高度容差内)找最近的怪,记下要朝它走的方向。
            # 只追同层:跨平台的怪走不过去,追了只会撞墙/掉台子。
            self._seek_dir = None
            if cfg['寻怪开关']:
                entries = [(m.x + m.width / 2, m.y + m.height) for m in mobs]
                self._seek_dir = farm_logic.seek_direction(entries, body[0], anchor_hit.y,
                                                           cfg['寻怪同层容差(像素)'])
                if self._seek_dir is not None:
                    # 寻怪本身就在移动=活动中,防挂机走位倒计时顺延;
                    # 刷新节流也从这一拍起算,避免启动后第一拍立即重复刷新
                    self._last_walk = now
                    self._last_seek_refresh = now

    def _do_walk(self, keys):
        """防挂机走位:两段方向由朝向决定(先反方向出、朝原方向回),结束时朝向不翻转
        ——旧版随机往返会把面朝方向翻反,战士只能打面朝方向,翻反后攻击一直打空;
        净位移 0,不会走出站桩点或掉下平台。首次走位前朝向未知(自动模式):
        随机一侧走,走完把实际朝向(第二段方向)采纳为基线。"""
        hold = self.config['走位持续时间(秒)']
        first, second, new_facing = farm_logic.walk_order(self._resolve_facing())
        key_first = '左移键' if first == 'left' else '右移键'
        key_second = '右移键' if second == 'right' else '左移键'
        self.send_key(keys[key_first], down_time=hold)
        self.send_key(keys[key_second], down_time=hold)
        self._facing = new_facing

    def _do_pet_feed(self, cfg, keys, now):
        """喂宠物:到间隔按宠物食物键(默认 15 分钟一次)。食物键留空(未绑定)
        时不按键也不推进计时——用户在设置页绑好键后立即补喂,不用再等一个完整间隔。"""
        if farm_logic.should_feed_pet(now, self._last_pet_feed, cfg['喂宠物间隔(秒)'],
                                      cfg['喂宠物开关']):
            key = keys.get('宠物食物键(可留空)', '')
            if key:
                self.send_key(key)
                self._last_pet_feed = now

    def _do_sit_chair(self, cfg, keys, now):
        """坐椅:检测模式、区内没怪且没在寻怪(真正站桩闲置)、离上次"忙"
        (攻击/寻怪/走位)已过 坐椅延迟 → 按一次椅子键坐下。坐下后再按一次椅子键
        会起身,所以同一轮闲置只按一次(_sitting 标记)。起身不显式按键——怪进区/
        开始寻怪/走位时,长按的攻击键/方向键/走位按键本身就会带角色站起来,
        下一轮闲置由 _mark_busy 清标记后重新坐下。定频模式不坐:它按攻击间隔
        定时按键,坐下立刻会被带起身。"""
        if (cfg['坐椅开关'] and cfg['攻击模式'] == '检测'
                and self._last_mob_present is False and self._seek_dir is None
                and not self._sitting
                and farm_logic.should_attack(now, self._last_busy, cfg['坐椅延迟(秒)'])):
            key = keys.get('椅子键(可留空)', '')
            if key:
                self.send_key(key)
                self._sitting = True
                self.log_info(f'闲置 {now - self._last_busy:.1f} 秒,按椅子键坐下')

    def _mark_busy(self, now):
        """在打/在追/在走 = 忙:坐椅延迟从头算,并清坐椅标记(可能刚坐下就接战,
        长按的攻击键/方向键会带角色起身,下一轮闲置需重新按键坐下)。"""
        self._last_busy = now
        self._sitting = False

    def _do_attack_hold(self, cfg, keys):
        """攻击:检测模式且最近一次检测区内有怪 → 长按攻击键,游戏按动画速度
        连续挥砍,不再等 攻击间隔 的拍点(每次打完不再"愣一下";接战刷新拍也
        立即接管,不留节流空档)。每拍重按补发漏键。无怪/切到定频 → 松开。
        定频模式不在这里管,仍按 攻击间隔 定时轻点。"""
        if cfg['攻击模式'] == '检测' and self._last_mob_present:
            self.send_key_down(keys['攻击键'])
            self._attack_held = True
        elif self._attack_held:
            self._release_attack_key()

    def _do_seek_move(self, cfg, keys):
        """寻怪移动:长按方向键向怪连续走(每拍重按一次、从不松开,直到
        变向/接战/无怪/开关关才松)——旧版每拍按下又松开(按 0.1s),
        刷新拍的 OCR+YOLO 阻塞期间键没按住,追怪时走走停停"一下一下";
        每拍重按还能在窗口短暂不可点击导致按键漏发时自动补上。"""
        if cfg['寻怪开关'] and self._seek_dir is not None:
            key = '左移键' if self._seek_dir == 'left' else '右移键'
            if self._seek_key is not None and self._seek_key != key:
                self.send_key_up(keys[self._seek_key])  # 换向:先松旧键
            self.send_key_down(keys[key])
            self._seek_key = key
            self._facing = 'LEFT' if self._seek_dir == 'left' else 'RIGHT'
        elif self._seek_key is not None:
            self._release_seek_key()

    def _release_seek_key(self):
        """松开寻怪长按的方向键(没按着就无事可做)。尽力而为:任何失败都只记日志
        不抛出——松键失败不能把停任务/暂停流程搞崩,按键最终也会随窗口失焦自然失效。"""
        if self._seek_key is None:
            return
        try:
            keys = self.get_global_config('游戏按键')
            self.send_key_up(keys[self._seek_key])
        except Exception as e:
            self.log_error(f'松开寻怪方向键失败: {e!r}')
        self._seek_key = None

    def _release_attack_key(self):
        """松开攻击长按(没按着就无事可做)。尽力而为:任何失败都只记日志
        不抛出——松键失败不能把停任务/暂停流程搞崩,按键最终也会随窗口失焦自然失效。"""
        if not self._attack_held:
            return
        try:
            keys = self.get_global_config('游戏按键')
            self.send_key_up(keys['攻击键'])
        except Exception as e:
            self.log_error(f'松开攻击键失败: {e!r}')
        self._attack_held = False

    def _release_held_keys(self):
        """松开全部长按键(寻怪方向键 + 攻击键)。"""
        self._release_seek_key()
        self._release_attack_key()

    def _on_executor_paused(self, paused):
        """F9 全局暂停时松开所有长按键——executor 暂停后 run() 不再被调用,
        不在这松键角色会一直走下去/打下去;恢复(False)不做事,下一拍会自动重新按下。"""
        if paused:
            self._release_held_keys()

    def disable(self):
        """停任务前松开可能还按着的长按键,防止角色在任务停止后继续走/打。"""
        self._release_held_keys()
        self._clear_debug()
        super().disable()

    def on_destroy(self):
        """应用退出/executor 销毁前松键(interaction 在任务之后才销毁,此时松键仍可用)。"""
        self._release_held_keys()
        self._clear_debug()
        super().on_destroy()

    def run(self):
        # TaskExecutor 调度 trigger task 前已取帧(TaskExecutor.py:555),不要再 next_frame()
        frame = self.frame
        if frame is None:
            return
        h, w = frame.shape[:2]
        if (w, h) != CALIBRATED_SIZE:
            # 窗口切换/最小化瞬间会拿到异常尺寸帧,连续 10 帧确认再停
            self._bad_size_frames += 1
            if self._bad_size_frames >= 10:
                self.stop_farming(f'分辨率 {w}x{h} 非校准值 {CALIBRATED_SIZE[0]}x{CALIBRATED_SIZE[1]},请调回后再挂机')
            return
        self._bad_size_frames = 0

        now = time.time()
        keys = self.get_global_config('游戏按键')
        cfg = self.config

        hp = bars.read_hp(frame)
        mp = bars.read_mp(frame)

        # 0. 死亡判定(连续 N 帧空血;死亡弹窗后背景动画仍在,静止守卫兜不住,必须专判)
        #    确认窗口内无条件 return:血已空,喝药/回城都无意义;
        #    也防止血条被弹窗遮挡的单帧误读立刻烧掉一张回城卷
        if farm_logic.is_dead(hp, cfg['死亡判定线']):
            self._dead_frames += 1
            if self._dead_frames >= cfg['死亡确认帧数']:
                self.stop_farming('角色死亡')
            return
        self._dead_frames = 0

        # 1. 保命:先喝血 → 再回城 → 再停(尽力而为,不保证存活)
        if farm_logic.is_emergency(hp, cfg['保命血线']):
            if cfg['喝药开关']:
                self.send_key(keys['血药键'])
            scroll = keys.get('回城卷键(可留空)', '')
            if farm_logic.emergency_action(scroll) == 'return_scroll':
                self.log_warning(f'HP {hp:.0%} 触保命血线,使用回城卷', notify=True)
                self.send_key(scroll, after_sleep=2)
            else:
                self.log_warning(f'HP {hp:.0%} 触保命血线,未配置回城卷', notify=True)
            self.stop_farming('低血保命')
            return

        # 2-3.5. 喝血/喝蓝/药水耗尽保护。喝药开关关闭时整段跳过:
        # 不按血/蓝药键、不 OCR 快捷栏,「连续喝药无效」检测也不跑。
        if cfg['喝药开关']:
            # 2. 喝血(连续无效检测:按 1s 窗口判定——按下药键一个窗口后 HP 仍未涨过 1%
            #    才累计,超上限停任务。绝不在按下药键的同一帧判定:那一帧药效还没出来,
            #    渐进回血(战斗中常见)每 0.1s 一跳往往不足 1%,逐帧判定必误停;
            #    窗口内也只按一次药键,避免 10Hz 连按浪费药水)
            if farm_logic.need_hp_potion(hp, cfg['喝血阈值']):
                if farm_logic.potion_window_elapsed(now, self._last_hp_potion_press,
                                                    cfg['喝药判定间隔(秒)']):
                    # 上一窗口已结束,和按下药键时的 HP 对比:涨了说明药在起效,清零
                    if self._last_hp_potion_press > 0:
                        self._hp_streak = self._hp_streak + 1 if hp <= self._hp_at_press + 0.01 else 0
                    self._hp_at_press = hp
                    self.send_key(keys['血药键'])
                    self._last_hp_potion_press = now
                    if farm_logic.potion_not_working(self._hp_streak, cfg['喝药无效上限']):
                        self.stop_farming('连续喝药无效')
                        return
            else:
                # 血回到阈值上:清零,下次掉血视为"新的一轮"(只记基线,不计无效)
                self._hp_streak = 0
                self._last_hp_potion_press = 0.0

            # 3. 喝蓝
            if farm_logic.need_mp_potion(mp, cfg['喝蓝阈值']):
                self.send_key(keys['蓝药键'])

            # 3.5 药水耗尽保护(低频 OCR)
            if cfg['药水耗尽保护'] and now - self._last_potion_check >= cfg['药水检查间隔(秒)']:
                self._last_potion_check = now
                hp_count = potions.read_slot_count(frame, self._slot_of(keys['血药键']))
                mp_count = potions.read_slot_count(frame, self._slot_of(keys['蓝药键']))
                empty = farm_logic.potions_exhausted(hp, cfg['喝血阈值'], hp_count,
                                                     mp, cfg['喝蓝阈值'], mp_count)
                if empty:
                    self.stop_farming(f'{"血" if empty == "hp" else "蓝"}药耗尽')
                    return
        else:
            # 关着的时间段不积累任何喝药状态:切换回来第一次喝药按哨兵路径处理
            # (只记基线不判无效),防止用切换前的旧基线误判「连续喝药无效」。
            self._hp_streak = 0
            self._hp_at_press = 0.0
            self._last_hp_potion_press = 0.0

        # 4. 攻击
        if cfg['攻击模式'] == '检测':
            # 完整检测拍(OCR 锚点 + YOLO)按攻击间隔节流;寻怪激活时另用更快的
            # 刷新间隔(默认 0.4s)重算方向/接战——目标死了/换近了不用等满攻击间隔
            if farm_logic.should_attack(now, self._last_detect, cfg['攻击间隔(秒)']):
                self._last_detect = now
                self._detect_and_act(frame, now, cfg, keys)
            elif cfg['寻怪开关'] and self._seek_dir is not None and farm_logic.should_attack(
                    now, self._last_seek_refresh, cfg['寻怪刷新间隔(秒)']):
                # 寻怪中快速刷新:只重跑找怪(锚点走缓存/快通道),方向立即更新;
                # 怪进攻击区立即停追接战,攻击长按同步接管,不留空档
                self._last_seek_refresh = now
                self._detect_and_act(frame, now, cfg, keys)
            # 攻击/寻怪移动:区内有怪 → 长按攻击键连续挥砍;寻怪 → 长按方向键。
            # 各自在条件不成立时松键(无怪/接战/无同层怪/开关关/切模式)
            self._do_attack_hold(cfg, keys)
            self._do_seek_move(cfg, keys)
            # 在打/在追 = 忙:坐椅延迟从头算;长按的攻击/方向键已带角色起身,清坐椅标记
            if self._last_mob_present or self._seek_dir is not None:
                self._mark_busy(now)
        else:
            self._clear_debug()  # 定频模式没有锚点/攻击区,之前检测模式画过的框清掉
            if farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
                self.send_key(keys['攻击键'])
                self._last_attack = now

        # 4.5 防挂机走位(默认开启)。有独立的 120s 节奏,不挂在 1.5s 攻击节拍上;
        # 检测模式下如果这一拍刚好判定有怪(正在打)或在寻怪(正在走),
        # 顺延到下一次判定"无怪且不寻怪"再走,不打断输出。定频模式没有"有没有怪"这个概念,到点直接走。
        if cfg['走位开关'] and farm_logic.should_attack(now, self._last_walk, cfg['走位间隔(秒)']):
            can_walk = cfg['攻击模式'] == '定频' or (self._last_mob_present is False
                                                    and self._seek_dir is None)
            if can_walk:
                self._do_walk(keys)
                self._last_walk = now
                self._mark_busy(now)  # 走位中角色在动,不算闲置(坐着的也会被走位键带起身)

        # 4.6 坐椅(检测模式专属):闲置超过延迟自动坐椅子回血蓝。
        # 定频模式不坐——它按攻击间隔定时按键,坐下也会立刻被带起身
        self._do_sit_chair(cfg, keys, now)

        # 5. 拾取(默认关闭,靠宠物)
        if farm_logic.should_pickup(now, self._last_pickup, cfg['拾取间隔(秒)'], cfg['拾取开关']):
            self.send_key(keys['拾取键'])
            self._last_pickup = now

        # 5.5 喂宠物(默认 15 分钟一次;食物键留空则不喂)
        self._do_pet_feed(cfg, keys, now)

        # 6. 兜底守卫
        sig = guards.signature(frame)
        if self._last_sig is None or not guards.frame_frozen(self._last_sig, sig):
            self._last_sig = sig
            self._last_change_time = now
        elif now - self._last_change_time > cfg['画面静止上限(秒)']:
            self.stop_farming('画面长时间静止(卡死/掉线/弹窗)')
            return

        exp = bars.read_exp(frame)
        # 升级后 EXP 条归零:exp 大幅下降同样视为"有收益",复位计时器,否则旧高位卡死计时器必然误停
        if self._last_exp is None or exp > self._last_exp + 0.001 or exp < self._last_exp - 0.05:
            self._last_exp = exp
            self._last_exp_gain_time = now
        elif now - self._last_exp_gain_time > cfg['经验停滞上限(分钟)'] * 60:
            self.stop_farming('经验长时间不涨(无效挂机)')
            return
