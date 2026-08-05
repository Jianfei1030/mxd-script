import time

from qfluentwidgets import FluentIcon

from ok import Logger, TriggerTask
from src.detect import bars, guards, potions
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
    '药水检查间隔(秒)': 30,
    '药水耗尽保护': True,
    '拾取开关': False,
    '拾取间隔(秒)': 30,
    '画面静止上限(秒)': 60,
    '经验停滞上限(分钟)': 10,
}

CALIBRATED_SIZE = (2560, 1440)  # 只在此分辨率挂机(README 约束)


class MapleFarmTask(TriggerTask, BaseMapleTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动打怪"
        self.description = "站桩定频攻击+自动喝药+低血保命"
        self.icon = FluentIcon.GAME
        self.trigger_interval = 0.1  # ~10Hz 轮询,保命响应足够快
        self.default_config.update(DEFAULT_CONFIG)
        self._reset_state()

    def _reset_state(self):
        """全部可变运行时状态。__init__ 与测试共用,新增状态只改这里。"""
        self._last_attack = 0.0
        self._last_pickup = 0.0
        self._hp_streak = 0
        self._last_hp = 1.0
        self._dead_frames = 0
        self._bad_size_frames = 0
        self._last_potion_check = 0.0
        self._last_sig = None
        self._last_change_time = 0.0
        self._last_exp = None
        self._last_exp_gain_time = 0.0

    def on_create(self):
        super().on_create()
        if self.config.get('药水耗尽保护'):
            potions.prewarm()

    @staticmethod
    def _slot_of(key_name):
        return key_name.lower()

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
            self.send_key(keys['血药键'])
            scroll = keys.get('回城卷键(可留空)', '')
            if farm_logic.emergency_action(scroll) == 'return_scroll':
                self.log_warning(f'HP {hp:.0%} 触保命血线,使用回城卷', notify=True)
                self.send_key(scroll, after_sleep=2)
            else:
                self.log_warning(f'HP {hp:.0%} 触保命血线,未配置回城卷', notify=True)
            self.stop_farming('低血保命')
            return

        # 2. 喝血(连续无效检测:喝完 HP 不涨则累计,超上限停任务)
        if farm_logic.need_hp_potion(hp, cfg['喝血阈值']):
            self.send_key(keys['血药键'])
            self._hp_streak = self._hp_streak + 1 if hp <= self._last_hp + 0.01 else 0
            self._last_hp = hp
            if farm_logic.potion_not_working(self._hp_streak, cfg['喝药无效上限']):
                self.stop_farming('连续喝药无效')
                return
        else:
            self._hp_streak = 0
            self._last_hp = hp

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

        # 4. 定频攻击
        if farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)']):
            self.send_key(keys['攻击键'])
            self._last_attack = now

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
