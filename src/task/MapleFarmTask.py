import random
import time

from qfluentwidgets import FluentIcon

from ok import Logger, TriggerTask
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
}

CALIBRATED_SIZE = (2560, 1440)  # 只在此分辨率挂机(README 约束)

FAST_HALF_W = 240        # 快通道搜索窗半宽(像素)
FAST_HALF_H = 80         # 快通道搜索窗半高
FALLBACK_WARN_INTERVAL = 60   # 回退屏幕中心的告警最小间隔(秒),防刷屏
DETECT_ERROR_LOG_INTERVAL = 60   # 检测(OCR/YOLO)异常日志最小间隔(秒),10Hz 主循环下不限频会刷爆日志


class MapleFarmTask(TriggerTask, BaseMapleTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动打怪"
        self.description = "站桩定频攻击+自动喝药+低血保命"
        self.icon = FluentIcon.GAME
        self.trigger_interval = 0.1  # ~10Hz 轮询,保命响应足够快
        self.default_config.update(DEFAULT_CONFIG)
        self.config_type['攻击模式'] = {'type': 'drop_down', 'options': ['定频', '检测']}
        self.config_description.update({
            '角色名': '检测模式用它 OCR 定位角色(名字牌)。留空则攻击区锚在画面中心',
            '攻击区宽(像素)': '2560x1440 下标定。用 scripts/calibrate_attack_zone.py 看图调',
            '名字牌到身体偏移(像素)': '名字牌在角色脚下,该值是牌子中心到身体中心的距离',
            '喝药判定间隔(秒)': 'HP 低于阈值时,两次喝药/判效的最小间隔。药水起效需要时间,间隔太短会误判"喝药无效"',
            '喝药开关': '总开关:关闭后不自动喝血/喝蓝;保命时也不按血药键(回城卷与停任务照常)',
        })
        self._reset_state()

    def _reset_state(self):
        """全部可变运行时状态。__init__ 与测试共用,新增状态只改这里。"""
        self._last_attack = 0.0
        self._last_pickup = 0.0
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
        self._last_anchor_scan = 0.0
        self._last_detect = 0.0
        self._last_fallback_warn = 0.0
        self._last_detect_error_log = 0.0
        self._last_walk = 0.0
        self._last_mob_present = None

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

    def _resolve_anchor(self, frame, now, cfg):
        """按四级阶梯拿角色锚点,返回 (Anchor, 来源标签)。任何一级都不停任务。

        快通道(上次锚点附近小窗) → 慢通道(中央区分块,节流) → 沿用上次 → 回退屏幕中心。
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
            try:
                hit = anchor.find_in_window(frame, name, self._anchor, FAST_HALF_W, FAST_HALF_H)
            except Exception as e:
                hit = None
                self._log_detect_error(now, '快通道锚点 OCR', e)
            if hit is not None:
                self._anchor, self._anchor_time = (hit.x, hit.y), now
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
                self._anchor, self._anchor_time = (hit.x, hit.y), now
                return hit, 'region'

        if not farm_logic.anchor_expired(now, self._anchor_time, cfg['锚点保鲜(秒)']):
            return anchor.Anchor(self._anchor[0], self._anchor[1], 0), 'cached'

        if now - self._last_fallback_warn >= FALLBACK_WARN_INTERVAL:
            self._last_fallback_warn = now
            self.log_warning(f'{cfg["锚点保鲜(秒)"]}s 未定位到角色「{name}」,攻击区暂锚在画面中心')
        return centre, 'fallback'

    @staticmethod
    def _slot_of(key_name):
        return key_name.lower()

    def _do_walk(self, keys):
        """防挂机走位:随机一侧走出去再走回来,净位移 0,不会走出站桩点或掉下平台。"""
        hold = self.config['走位持续时间(秒)']
        first = random.choice(('左移键', '右移键'))
        second = '右移键' if first == '左移键' else '左移键'
        self.send_key(keys[first], down_time=hold)
        self.send_key(keys[second], down_time=hold)

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
            # 节流用独立的 _last_detect:无怪时不更新 _last_attack,否则 10Hz 每拍都要跑
            # 一遍 OCR + YOLO(旧代码的行为)
            if farm_logic.should_attack(now, self._last_detect, cfg['攻击间隔(秒)']):
                self._last_detect = now
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
                if mob_present:
                    self.send_key(keys['攻击键'])
                    self._last_attack = now
        elif farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
            self.send_key(keys['攻击键'])
            self._last_attack = now

        # 4.5 防挂机走位(默认开启)。有独立的 120s 节奏,不挂在 1.5s 攻击节拍上;
        # 检测模式下如果这一拍刚好判定有怪(正在打),顺延到下一次判定"无怪"再走,
        # 不打断输出。定频模式没有"有没有怪"这个概念,到点直接走。
        if cfg['走位开关'] and farm_logic.should_attack(now, self._last_walk, cfg['走位间隔(秒)']):
            can_walk = cfg['攻击模式'] == '定频' or self._last_mob_present is False
            if can_walk:
                self._do_walk(keys)
                self._last_walk = now

        # 5. 拾取(默认关闭,靠宠物)
        if farm_logic.should_pickup(now, self._last_pickup, cfg['拾取间隔(秒)'], cfg['拾取开关']):
            self.send_key(keys['拾取键'])
            self._last_pickup = now

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
