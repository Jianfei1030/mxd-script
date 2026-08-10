import os
import time

import numpy as np
from qfluentwidgets import FluentIcon
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

from ok import Logger, TriggerTask
from ok.gui.Communicate import communicate
from src.detect import anchor, bars, facing, guards, ocr_engine, potions
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
    '攻击区形状': '单体(面朝)',
    '攻击区宽(像素)': 600,
    '攻击区高(像素)': 200,
    '群攻怪数阈值': 3,
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
    '空闲刷新间隔(秒)': 0.3,
    '玩家宽(像素)': 60,
    '玩家高(像素)': 120,
    '模板分片匹配开关': True,
    '模板匹配阈值': 0.2,
    'YOLO角色定位开关': True,
    '身份保鲜(秒)': 10,
    '身份复验开关': True,
    '身份复验间隔(秒)': 3,
    '丢锚立即重扫开关': True,
    '丢锚唯一框接管开关': True,
    '丢怪保持(秒)': 1.0,
    '寻怪起步宽限(秒)': 0.3,
    '寻怪保持(秒)': 0.5,
    '转向冷却(秒)': 1.5,
    '受击防抖(秒)': 1.0,
    '硬直抑制窗(秒)': 0.0,
    '朝向纠正开关': True,
    '攻击前垫步开关': False,
    '朝向观测开关': False,
    '决策日志开关': False,
    # 调试可视化开关（勾选 GUI「启用标记框」时显示）
    '显示玩家框': True,
    '显示攻击区': True,
    '显示名字搜索范围': True,
    '显示寻怪同层带': True,
    '显示怪物框': True,
}

CALIBRATED_SIZE = (2560, 1440)  # 校准分辨率;不符时只提醒不硬停(见 run(),2026-08-10 用户口径)

FAST_HALF_W = 240        # 快通道搜索窗半宽(像素)
FAST_HALF_H = 80         # 快通道搜索窗半高
ANCHOR_EXTRAPOLATE_MIN_AGE = 0.5  # 锚点年龄 ≥ 此值才开始外推:新鲜锚点不需要推
ANCHOR_VX_MAX_AGE = 2.0           # 实测速度在此窗口内可信,超时退化用配置速度
ANCHOR_VX_MAX_SPEED = 600         # 实测速度上限(像素/秒):跳变 = 回退/误检,不学
ANCHOR_VX_PLATFORM_DY = 30        # 名字牌 y 位移超此值视为换平台,不学速度
ANCHOR_DEFAULT_SPEED = 250        # 无实测速度时的水平外推速度(像素/秒)
ANCHOR_EXTRAPOLATE_MAX_DX = 500   # 外推位移上限(px)≈2s 行走量:拆丢锚期外推↔寻怪振荡回路
NAMETAG_TEMPLATE_DIR = 'screenshots/nametag_templates'  # 名字牌模板持久化目录(白字二值化)
NAMETAG_TEMPLATE_HALF_H = 18   # 模板裁剪半高:名字牌文字高 ~26px
NAMETAG_TEMPLATE_PAD = 12      # 模板裁剪两侧边距(文字框外留白)
FALLBACK_WARN_INTERVAL = 60   # 回退屏幕中心的告警最小间隔(秒),防刷屏
DETECT_ERROR_LOG_INTERVAL = 60   # 检测(OCR/YOLO)异常日志最小间隔(秒),10Hz 主循环下不限频会刷爆日志
TURN_TAP_SECONDS = 0.05  # 转向轻点:方向键按 50ms 即翻转朝向,位移可忽略(约几像素,方向随怪侧轮换不累积)
PAD_STEP_TAP_SECONDS = 0.015  # 攻击前垫步:方向键按 15ms,位移更小——垫步只需"点一下朝向",不需完整翻转
FACING_TEMPLATE_DIR = 'screenshots/facing_templates'  # 朝向模板持久化目录(灰度头+肩)
_FACING_SHORT = {'LEFT': 'L', 'RIGHT': 'R'}   # 决策行里 实测= 字段的短写
FACING_CAPTURE_MIN_DX = 40   # 采朝向模板要求的最小确认位移(像素):角色真走了这么远,朝向才是观测出来的而不是猜的


def decision_log_line(source, body_x, anchor_y, centres, in_zone, left,
                      same_feet, same_center, near,
                      raw_present, mob_present, attack_in, attack_present,
                      facing_before, facing_now, turn, seek_dir, key_sendable,
                      observed, obs_s, obs_flip, yolo_cands=None, yolo_dist=None,
                      yolo_full=None):
    """决策日志行(不含时间戳前缀)—— 格式的唯一事实源。

    scripts/analyze_facing.py 与 scripts/analyze_seek.py 的正则按它解析,
    tests/test_analyze_facing.py、tests/test_analyze_seek.py 也调它构造样本行:
    改这里任何字段,绑定测试立刻红。2026-08-08 评审坐实过假绑定 ——
    当时测试里手抄了一份格式,把 `实测=` 改名后 15 个「绑定」测试全过。

    同层脚 / 同层心 是两个口径的同层怪数(spec §2.3):
    同层脚 = 怪脚底 vs 名字牌 y,容差 寻怪同层容差(旧口径,Task 6 后退休);
    同层心 = 怪中心 y 落在接敌区纵向范围内(新口径,与 mob_in_zone 同源)。
    两个都写出来,是为了量出「攻击区罩得到却判不同层」那条带上到底有多少怪。
    near = 水平最近那只怪的 (dx, dy脚, dy心);屏幕无怪时 None → 三项写 '-',
    绝不写 0(0 会被判据脚本当成真值)。

    yolo候选 / 关联距 是 YOLO 关联级(spec §3.6)的观测:候选 = **门内**候选数
    (gate_player_boxes 口径——全屏数混着门外路人,调关联门/查误认会误导),
    关联距 = 命中框中心与外推位置的水平距离。
    yolo全屏 = 同拍全屏 player 框数(含门外):候选=0 全屏≥1 = 检出被门拒,
    候选=0 全屏=0 = YOLO 跑了但全屏无 player 框,全=- = YOLO 级未到达
    (模板/快窗命中)或定频无推理(2026-08-10 spec §3.3)。
    非 yolo 来源的拍这些字段都写 '-',绝不写 0。追加在行尾:analyze 脚本前缀匹配。
    """
    near_s = ('近怪dx=- dy脚=- dy心=-' if near is None else
              f'近怪dx={near[0]:+.0f} dy脚={near[1]:+.0f} dy心={near[2]:+.0f}')
    return (f'决策 src={source} body_x={body_x:.0f} anchor_y={anchor_y:.0f} '
            f'怪={len(centres)} 区内={len(in_zone)}(左{left}/右{len(in_zone) - left}) '
            f'同层脚={same_feet} 同层心={same_center} {near_s} '
            f'实测有怪={raw_present} 有怪={mob_present} '
            f'可打区内={len(attack_in)} 可打={attack_present} '
            f'朝向={facing_before or "-"}→{facing_now or "-"} '
            f'转向={turn or "-"} 寻怪={seek_dir or "-"} '
            f'可发键={key_sendable} '
            f'实测={_FACING_SHORT.get(observed, "?")} '
            f'分值={max(obs_s, obs_flip):.2f}/{abs(obs_s - obs_flip):.2f}'
            f' yolo候选={yolo_cands if yolo_cands is not None else "-"}'
            f' 关联距={f"{yolo_dist:.0f}" if yolo_dist is not None else "-"}'
            f' yolo全屏={yolo_full if yolo_full is not None else "-"}')


def divergence_log_line(facing_before, observed, obs_s, obs_flip,
                        dt_attack, dt_hit, dt_turn):
    """朝向分歧日志行 —— 格式唯一事实源(同上)。判据 D 按 距上次攻击 分桶。"""
    return (f'朝向分歧 信念={facing_before} 实测={observed} '
            f'分值={max(obs_s, obs_flip):.2f}/{abs(obs_s - obs_flip):.2f} '
            f'距上次攻击={dt_attack:.2f}s 距上次受击={dt_hit:.2f}s '
            f'距上次转向={dt_turn:.2f}s')


def template_captured_line(direction, min_dx):
    """朝向模板已采集日志行 —— 判据 A 的分母从它之后开始算。"""
    return f'朝向模板已采集 方向={direction} (寻怪走动确认 ≥{min_dx}px)'


def aoe_log_line(count, threshold):
    """群攻触发行 —— 格式唯一事实源(同 decision_log_line)。

    判据 A 直接 grep 「群攻」数行数,并核对每行的 区内 >= 阈值。
    不塞进决策行是有意的:decision_log_line 被两个 analyze 脚本的正则和一批
    绑定测试吃着,为一个偶发事件改它的格式不划算(spec §4)。
    """
    return f'群攻 区内={count} 阈值={threshold}'


DEBUG_OVERLAY_KEY = 'maple_farm_debug'   # 调试 overlay 的画笔 key(WarriorDebugTask 已移除,原 'warrior_debug' key 不复存在)
PLAYER_COLOR = QColor(0, 255, 0)
ZONE_IDLE_COLOR = QColor(0, 128, 255)
ZONE_HOT_COLOR = QColor(255, 0, 0)
MOB_COLOR = QColor(255, 255, 0)
MOB_FOOT_COLOR = QColor(0, 255, 255)
ANCHOR_SEARCH_COLOR = QColor(0, 0, 255)   # 名字搜索范围框（蓝虚线）
SEEK_BAND_COLOR = QColor(0, 255, 255)     # 寻怪同层高度带（青虚线）


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
        self._register_config_types()
        self.config_description.update({
            '攻击间隔(秒)': '攻击按键节奏,两种模式都按它轻点(检测模式同时用作完整检测拍「锚点OCR+YOLO」的节流)。2026-08-07 从长按连挥改回轻点:长按期间游戏收不到新的按下边沿,被怪击退打断施法后不会重新起手',
            '角色名': '检测模式用它 OCR 定位角色(名字牌)。留空则攻击区锚在画面中心',
            '攻击区形状': '单体(面朝):只打面朝侧半区,射程 = 攻击区宽的一半。魔法箭/近战这类面朝向技能选它——对称区会在「怪在背侧且转向还在冷却」时按出空技能。群体(对称):打整个攻击区,行为等同于此功能上线前,作为安全退路保留',
            '攻击区宽(像素)': '2560x1440 下标定。用 scripts/calibrate_attack_zone.py 看图调',
            '群攻怪数阈值': '接敌区内怪数达到此值就改用群攻(前后双向命中),那一拍不转向、也不按单体攻击键。群攻不另设节拍,和单体共用「攻击间隔(秒)」——到点了看区内怪数决定按哪个键。需要先在设置页「游戏按键」绑定「群攻键(可留空)」,留空则本项无效。注意数的是**接敌区内**(默认 600x200,即身体左右各 300px、上下各 100px)的怪,不是屏幕上的怪:2026-08-10 实测 359 个检测拍里 区内=0/1/2/3 各占 78.3%/16.4%/4.7%/0.6%,而「屏幕有怪但区内=0」的拍里 62% 是最近的怪根本在别的平台上。所以默认 3 实际几乎不触发(4.7 分钟只 2 拍),觉得「围了一圈却不放群攻」时先调成 2(覆盖率 0.6%→5.3%),别急着调大攻击区宽/高——那个同时改单体攻击区和转向/寻怪/坐椅。实跑后按决策日志里的 区内=N 分布回调',
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
            '空闲刷新间隔(秒)': '既不在打也不在追时,多久跑一次检测拍。**「起步寻怪」只能在检测拍里发生,所以这个值直接决定「停手到迈腿」有多快。**旧实现里这一步被绑在 攻击间隔 上(0.7s),而 寻怪刷新间隔 只能刷新一个已经存在的寻怪、发起不了新的,所以把它调小对起步毫无作用——2026-08-08 实测停手→起步中位 1.19s、p90 3.61s,屏幕上有怪却既不打也不追的时间占 25.2%。默认 0.3:一个完整检测拍(模板/OCR+YOLO+朝向观测)实测耗时中位 0.178s、p90 0.286s,10Hz 主循环实际只跑得到 5.6Hz,取 0.1 只会把 CPU 打满而并不会更快。调回 0.7 = 旧行为',
            '寻怪外推速度(像素/秒)': '寻怪中名字牌被怪遮挡、OCR 连续失败时,攻击区按此速度跟随走动中的角色(水平外推),怪进区即可接战;名字牌一露头快通道立刻重新咬住。无实测速度时用此值,实测行走速度约 250',
            '玩家宽(像素)': '仅用于调试可视化画框(勾选 GUI「启用标记框」时显示),不影响攻击判定',
            '玩家高(像素)': '同「玩家宽(像素)」,仅调试画框用',
            '模板分片匹配开关': '名字牌模板快通道:OCR 完整命中时自动把名字牌裁成白字二值化模板(存 screenshots/nametag_templates/),之后每帧先用模板竖切分片匹配定位角色——怪/宠的名字牌盖住一半也照样命中,且不跑 OCR;匹配失败自动落回 OCR。怪堆里"一直寻怪不攻击"(名字牌被盖 → OCR 失败 → 锚点冻结)的主要解法。命中后还会验证位置周围有暗底(名字牌有暗色半透明底框),拒绝云/天空误匹配',
            '模板匹配阈值': '模板分片匹配的接受阈值(归一化平方差,0=完全一致):越严(越小)误匹配越少,但遮挡/抗锯齿下越容易漏。默认 0.2 参考 MapleStoryAutoLevelUp',
            'YOLO角色定位开关': '锚点阶梯第三级:名字牌模板与快窗 OCR 都没拿到时,用同一拍 YOLO 检出的 player 框接管角色位置(检测的是角色本体,任何名字牌遮挡都不影响;推理与找怪同拍共享,零额外开销)。身份仍由名字牌校准:该级只在已有锚点时参战,认错人风险由「身份保鲜(秒)」兜底。关掉 = 完全退回旧阶梯。丢锚拍占比 28.5%(2026-08-08 全天)的主解,详见 specs/2026-08-09-player-anchor-yolo-fusion-design.md',
            '身份保鲜(秒)': '距上次名字牌真实命中(模板/快窗/慢扫)超过此时长后,若屏幕上有多个玩家框,YOLO 级拒绝裁决(宁可退到慢扫/缓存,不认错路人);恰好只有一个玩家框时不受此限。调小 = 收紧防误认,调大 = 怪堆重度遮挡下更少丢锚。绿框跳到别的玩家身上时,先调小它',
            '身份复验开关': '身份过期(距上次名字牌真实命中超过「身份保鲜(秒)」)时,把慢扫提到 YOLO 级**之前**跑一次验名。为什么必须提前:YOLO 级一命中就返回,排在它后面的慢扫根本轮不到——2026-08-09 实测慢扫占比被饿到 0.6%(加 YOLO 前的基线是 2.2%),而慢扫是唯一验名、也是唯一能在上次锚点小窗之外找回角色的通道。没有它,YOLO 一旦认错人,伪锚点会继续刷新锚点时间戳、连「丢锚立即重扫」都不会触发,绿框就永久钉在路人身上。慢扫没找到照样落回 YOLO 级,只加验名机会,不新增丢锚。关掉 = 旧阶梯',
            '身份复验间隔(秒)': '身份复验慢扫的限频(慢扫中位 118ms、最坏 235ms,不许每拍都跑)。它同时是「认错人最长持续时间」的上界:调小=纠错更快、CPU 更吃,调大=反之。只在身份已过期且名字牌两级都失效的拍才计次,正常打怪期间根本不会触发',
            '丢锚立即重扫开关': '本拍模板/快窗OCR/YOLO 三级全没拿到位置,且(刚受击 或 锚点已超过「锚点刷新间隔」没更新)时,立刻跑一次慢扫,不等 2 秒节流——丢锚常由击退位置跳变引起,常规节流恰好卡在最需要慢扫的时刻(基线里慢扫只占 2.2%)。强制扫描自身限频 0.5 秒(慢扫最坏 235ms,不许打满主循环)。关掉 = 旧节流行为',
            '丢锚唯一框接管开关': '丢锚超过 1 秒、常规关联门裁决失败时,若全屏恰好只有 1 个玩家框且与最后已知层高同层(±300px),直接认定是自己接管位置——唯一性就是身份判据(单人挂机全屏 1 框几乎恒是自己),横向不再看已失效的外推门。认错路人的上界 = 名字牌下次可读 + 身份复验间隔(秒级),复验慢扫会纠正;全屏 ≥2 个玩家框时不接管(多人图保守)。关掉 = 只靠慢扫找回(旧行为)',
            '经验停滞上限(分钟)': '经验条这么久没涨就停任务(兜底"无效挂机")。屏幕上一只怪都没有的时段不计入——空图/刷新间隙本来就没收益,不该被判停;检测模式才有此豁免,定频模式没有找怪信息,照常计时',
            '丢怪保持(秒)': '攻击区里检测不到怪之后,还按"有怪"继续挥多久。YOLO 一拍漏检(单帧 recall 约 0.89,自己的攻击特效还会盖住目标)就松手的话,法师一次施法要 1 秒、技能根本放不出来。要大于一个攻击间隔才兜得住漏检。设 0 = 关掉,退回一拍空立刻停手',
            '寻怪起步宽限(秒)': '区内检测不到怪之后,还要再等多久才允许起步去追。**必须小于「丢怪保持(秒)」**,取等 = 退回修复前行为。为什么要分成两个值:丢怪保持是为 YOLO 漏检兜底的(单帧 recall 0.886,一拍漏检就松开攻击键,法师一次施法都放不出来),那个理由只对攻击键成立——多挥一刀空的代价,远小于多站一秒不动。2026-08-08 实测有 11.5% 的拍卡在丢怪保持窗里,其中 3310 拍屏幕上明明有怪却结构性禁止寻怪。攻击键本身不受此项影响(它由「有向攻击区内有没有怪」单独去抖)。寻怪方向一旦定下来,还被丢怪保持撑着的攻击信号会立刻作废,不会出现「一边追一边挥」',
            '寻怪保持(秒)': '寻怪中的去抖:追怪途中某一拍 YOLO 一只同层怪都没检出,还按上一拍的方向继续走多久。和 丢怪保持 同理——单帧 recall 0.886,一拍漏检就原地停的话,追怪会一卡一卡(起步宽限 0.3s + 这一拍,一漏检就得重走「无怪窗口 + 重新定位」的全套)。0 = 退回修复前行为(一拍判失立刻停)。默认 0.5:必须小于 丢怪保持(1.0),追错方向的代价本来就高于挥空一刀,不该比它保持得还久',
            '转向冷却(秒)': '两次转向之间的最小间隔。攻击区里常常只有一只怪,而它反复在身体左右两侧之间换,不加冷却角色就原地左右扭(实测转向 17 次里 12 次是反向)。要大于一次施法时间才压得住;设太大则怪真绕到背后时反应慢。设 0 = 关掉',
            '受击防抖(秒)': '受击(HP 掉 2%+)事件的最小间隔。游戏受击后约 1 秒无敌,1 秒内不可能有新的真实掉血,但血条渐变动画会把一次掉血拆成多拍读数、每拍都触发受击——每次受击都会作废朝向并重置转向冷却,重复触发让冷却形同虚设,怪穿过时左右扭+打空。取 1 秒 = 游戏无敌时长,不会漏真受击。设 0 = 关掉防抖',
            '硬直抑制窗(秒)': '受击后多久内不按转向/攻击键。**默认 0 = 关闭,实测有害,别开**。原意是躲开击退硬直(硬直中按键被游戏吞掉,但转向代码照常盲写朝向 → 信念分叉打空),但 2026-08-08 逐拍实测证明它把问题放大了:受击会把 _facing 清成 None,而 facing_half_zone 在 None 时退化成整个对称区,于是抑制窗禁止转向的这段时间里,有向攻击区失效、照常朝背后的怪开火。设 0.8 时「朝向未知」占挂机时间 23.3%、受击到下次成功转向中位 1.55s;设 0 后回落到 8.1% / 0.70s(四条事先写死的判据全过)。真正的解法是「只在角色可操作的时刻发键」,见 docs/superpowers/specs/2026-08-08-facing-observer-design.md §6。保留此项只为复现当时的对照实验',
            '朝向纠正开关': '观测到角色真实朝向与信念不符时,以观测为准写回。_facing 原本是纯信念(只有"我们自己按了方向键所以认为转过去了"这一种写入),键被游戏吞掉就会与现实分叉、朝空处放技能。2026-08-08 实弹 30 分钟:观测器可用率 77.3%、随机噪声 0.4%(事先写死的线是 >=50% 与 <=5%),够格当纠正依据。它同时接管了「受击作废朝向」原本顺带提供的破死锁作用,所以那行清空已经删掉。依赖朝向模板,模板要等第一次寻怪走动确认才采得到,在那之前不生效(行为同改动前)。关掉 = 观测器退回只读',
            '攻击前垫步开关': '战士专用(默认关,不影响法师等其他职业):每次攻击前先朝攻击区内最近怪所在侧轻点方向键(20ms,见 PAD_STEP_TAP_SECONDS),再按攻击键。目的是兜住 _facing 信念被击退/按键丢失破坏的盲区——此时攻击区内有怪、attack_turn_direction 认为"面朝侧还有目标"不转向,角色背对怪一直砍空气且无修正机会。垫步不信任信念:信念错则物理修正朝向,信念对则轻点是 no-op(已朝该侧按方向键零代价)。垫步只在 攻击间隔 放行的拍执行,节奏与攻击一致。需要 攻击模式=检测(定频无怪位置信息,无从定向)',
            '朝向观测开关': '只读排查用:每个锚点真命中的检测拍,用模板匹配读出角色**真实**朝向,与信念朝向一起写进决策日志(字段 实测= / 分值=),不一致时另写一行「朝向分歧」。它不改变任何决策,纯粹是尺子——_facing 是纯信念,项目在它上面改过四轮却一直没有直接证据。开着会在没模板时先等一次寻怪走动来采模板(要求沿按键方向真走够 40px,避免用信念标定模板)。需要同时开 决策日志开关。排完记得关',
            '决策日志开关': '排查用:每个检测拍往 logs/ok-script.log 写一行决策数据(锚点来源、身体x、区内怪的左右分布、是否有怪、可打区内怪数、可打、朝向变化、转向、寻怪方向、按键能否送出),另外每次检测到受击(HP 下降)写一行「受击」。排"左右转向不攻击/打空"这类问题时打开,挂机两分钟后 grep 「决策」/「受击」看。寻怪刷新间隔小时会写得很密(0.1s = 每秒 10 行),排完记得关',
        })
        self._reset_state()

    def _register_config_types(self):
        """GUI 控件类型注册。抽成方法是为了能离线断言注册内容——
        这几个键写成自由文本框的话,用户手打错一个字会静默退回默认分支。"""
        self.config_type['攻击模式'] = {'type': 'drop_down', 'options': ['定频', '检测']}
        self.config_type['朝向'] = {'type': 'drop_down', 'options': ['自动', '左', '右']}
        self.config_type['攻击区形状'] = {'type': 'drop_down',
                                          'options': ['单体(面朝)', '群体(对称)']}

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
        self._size_warned = False      # 分辨率不符的提醒,整个任务只发一次
        self._last_potion_check = 0.0
        self._prev_hp = None          # 上一拍 HP(受击检测用);None=第一拍
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
        self._last_mob_seen = None    # 上次攻击区内真检测到怪的时刻;None=从未见过(去抖用)
        self._last_attack_present = None  # 有向攻击区内有没有怪(去抖后);行为上只有 _do_attack 读它(另有 overlay/日志读)
        self._last_attack_seen = None     # 上次有向攻击区内真检测到怪的时刻;None=从未见过(去抖用)
        self._detect_attacking = None     # 检测节拍用的「在打」快照(短宽限去抖);只有 should_detect 读它
        self._last_any_mob = None     # 最近一次检测拍屏幕上有没有怪(不限攻击区);None=没跑过找怪(定频)
        self._last_zone_count = 0     # 最近一次检测拍接敌区内怪数(群攻判据用);0=还没检测过
        self._last_zone_count_time = None  # 上面那个计数是哪一拍测的;None=还没测过。
                                           # 群攻只认「本拍现测」的计数,见 _aoe_ready
        self._last_turn = 0.0         # 上次转向轻点时刻;0.0 哨兵=从未转向,不受冷却限制
        self._last_centres = []       # 最近一次检测拍的怪中心列表(垫步定向用)
        self._last_zone = None        # 最近一次检测拍的接敌区(垫步定向用)
        self._last_hit = 0.0          # 上次受击(作废朝向)时刻;受击防抖用,0.0 哨兵=从未受击
        self._facing = None           # 角色面朝方向;None=未知(首次走位前),配置 左/右 时走位前由配置定
        self._seek_dir = None         # 自动寻怪目标方向 'left'/'right';None=不寻怪(区内有怪/无同层怪/开关关)
        self._last_seek_seen = None   # 上次寻怪定位到方向(真检出同层怪)的时刻;None=从未(寻怪去抖用)
        self._seek_key = None         # 寻怪长按中按下的方向键名('左移键'/'右移键');None=未按住
        self._seek_start_body_x = None    # 本次寻怪长按起点的 body_x,走动确认用
        self._last_body_x = None          # 上一检测拍的身体中心 x,走动确认起算用
        self._attack_held = False     # 攻击键是否长按中(检测模式,区内有怪时按住连续挥砍)
        self._sitting = False         # 本轮闲置是否已按过椅子键(再按一次会起身,只能按一次)
        self._last_busy = 0.0         # 最近一次"忙"(攻击/寻怪/走位)时刻,坐椅延迟按它算
        self._nametag_template = None  # 白字二值化名字牌模板(模板分片匹配快通道用),None=尚未捕获
        self._facing_template = None      # 朝向模板(灰度 58x66);None=还没采到
        self._facing_template_dir = None  # 模板自身朝向 'LEFT'/'RIGHT';None=未知
        self._debug_drawn = False      # 调试 overlay 当前是否已画(True 时开关关掉/模式切换才需要真的调 clear_draw)
        self._last_identity_hit = 0.0  # 上次名字牌真实命中(template/window/region)时刻;0.0=从未。多候选裁决只在保鲜窗内放行;yolo 不刷新它(它不验名,spec §3.4)
        self._last_yolo_info = None    # 本拍 YOLO 关联观测 (门内候选数, 关联距 or None, 全屏框数);None=本拍 YOLO 级未到达(决策日志用)
        self._force_rescan = False        # 受击置位:下一检测拍绕过慢扫节流(spec §3.5);任一通道命中即清(跳变已消化)
        self._last_forced_rescan = 0.0    # 上次强制慢扫时刻;0.0 哨兵=从未,配合 FORCED_RESCAN_MIN_INTERVAL 限频
        self._last_identity_scan = 0.0    # 上次身份复验慢扫时刻;0.0 哨兵=从未,配合「身份复验间隔(秒)」限频

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
            name = self.config.get('角色名').strip()
            # 加载上次存的名字牌模板:模板分片匹配通道开箱即用,不用等第一次完整命中
            self._nametag_template = anchor.load_template(
                os.path.join(NAMETAG_TEMPLATE_DIR, f'{name}.png'))

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
        self._force_rescan = False   # 任一通道命中 = 位置重新观测到,悬着的强制扫描作废

    def _extrapolated_anchor_x(self, now, cfg):
        """寻怪中锚点超龄 → 角色此刻应在的水平 x(实测速度优先,无实测用配置速度 × 寻怪方向)。

        只在"正在寻怪(角色在走动)"时推:站桩外推只会把攻击区推离原地;
        锚点新鲜(年龄 < 0.5s)不推——刚命中过,位置就是真值,推了反而引入误差;
        已过期(年龄 > 保鲜)不推——位置本身已不可信,交给回退分支。
        位移钳在 ±ANCHOR_EXTRAPOLATE_MAX_DX:丢锚期外推随年龄线性放大会与寻怪决策
        形成振荡反馈(2026-08-10 21:18 日志,pred 每拍跳 ±1250px);反向学习速度由
        farm_logic.extrapolate_vx 拦截。返回值再钳在 [0, 2560] 内,极端外推不出帧。
        """
        if self._seek_dir is None or self._anchor is None or self._anchor_time is None:
            return self._anchor[0] if self._anchor is not None else None
        age = now - self._anchor_time
        if age < ANCHOR_EXTRAPOLATE_MIN_AGE or age > cfg['锚点保鲜(秒)']:
            return self._anchor[0]
        learned = (self._anchor_vx
                   if now - self._last_anchor_hit <= ANCHOR_VX_MAX_AGE else 0.0)
        speed = cfg.get('寻怪外推速度(像素/秒)', ANCHOR_DEFAULT_SPEED)
        vx = farm_logic.extrapolate_vx(learned, self._seek_dir, speed)
        dx = max(-ANCHOR_EXTRAPOLATE_MAX_DX,
                 min(ANCHOR_EXTRAPOLATE_MAX_DX, vx * age))
        return max(0.0, min(CALIBRATED_SIZE[0], self._anchor[0] + dx))

    def _capture_nametag_template(self, frame, hit):
        """OCR 完整命中 → 裁名字牌区域做白字二值化模板,供模板分片匹配快通道用。

        部分匹配('ng咕咕')是名字牌被挡的产物,裁出来是残缺牌子,不配当模板;
        裁出来没有白字(黑帧/OCR 误报)→ 不存。模板变了才落盘
        (screenshots/nametag_templates/{角色名}.png),下次启动直接加载。"""
        tmpl = anchor.capture_template(frame, hit, half_h=NAMETAG_TEMPLATE_HALF_H,
                                       pad=NAMETAG_TEMPLATE_PAD)
        if tmpl is None or (self._nametag_template is not None
                            and np.array_equal(tmpl, self._nametag_template)):
            return
        self._nametag_template = tmpl
        try:
            os.makedirs(NAMETAG_TEMPLATE_DIR, exist_ok=True)
            name = (self.config.get('角色名') or '').strip()
            anchor.save_template(tmpl, os.path.join(NAMETAG_TEMPLATE_DIR, f'{name}.png'))
        except Exception as e:
            self.log_error(f'名字牌模板落盘失败(不影响本次运行,下次完整命中会再存): {e!r}')

    def _maybe_capture_facing_template(self, frame, hit, source, name):
        """采朝向模板:只在「寻怪长按 + 位移已确认 + OCR 完整命中 + 还没模板」时采。

        模板自带朝向,而 `s > s_flip` 只说明「与模板同向」——要换算成 L/R 就必须
        知道模板本身朝哪边。**不能用 `_facing` 标定**(那正是被检验的对象,循环论证),
        所以改用位移观测:寻怪是长按方向键连续走,角色真的沿按键方向走了
        FACING_CAPTURE_MIN_DX 像素,它就必定面朝那边(见 farm_logic.walk_confirmed)。

        OCR 完整命中这道门与 _capture_nametag_template 同源:部分匹配 'ng咕咕' 的
        框中心系统性右偏,裁出来的 ROI 是草地和宠物脸(附录 A.3,第一次实验因此作废)。
        """
        if self._facing_template is not None:
            return
        if source not in ('window', 'region'):
            return
        if (getattr(hit, 'text', '') or '').strip() != name:
            return
        if not farm_logic.walk_confirmed(self._seek_dir, self._seek_start_body_x,
                                         anchor.body_center(hit, self.config['名字牌到身体偏移(像素)'])[0],
                                         FACING_CAPTURE_MIN_DX):
            return
        tmpl = facing.capture(frame, hit)
        if tmpl is None:
            return
        self._facing_template = tmpl
        self._facing_template_dir = 'LEFT' if self._seek_dir == 'left' else 'RIGHT'
        self.log_info(template_captured_line(self._facing_template_dir,
                                             FACING_CAPTURE_MIN_DX))
        try:
            os.makedirs(FACING_TEMPLATE_DIR, exist_ok=True)
            suffix = 'L' if self._facing_template_dir == 'LEFT' else 'R'
            anchor.save_template(tmpl, os.path.join(
                FACING_TEMPLATE_DIR, f'{name}_{suffix}.png'))
        except Exception as e:
            self.log_error(f'朝向模板落盘失败(不影响本次运行): {e!r}')

    def _observe_facing(self, frame, hit, source):
        """一次只读朝向观测 → (朝向, s, s_flip)。任何失败都返回 (None, 0.0, 0.0)。

        观测的**计算**在「纠正开关 或 观测开关」任一为真时执行;`朝向观测开关`
        此后只管**日志详略**(见配置说明)。这样纠正作为常驻功能可用,不必逼用户
        为了用它去打开排查级日志。异常一律吞掉,观测器不能把挂机搞崩。
        """
        if not (self.config.get('朝向纠正开关')
                or self.config.get('朝向观测开关')):
            return None, 0.0, 0.0
        if source not in ('window', 'region', 'template'):
            return None, 0.0, 0.0   # cached/fallback 的锚点会让 ROI 整体错位
        if self._facing_template is None:
            return None, 0.0, 0.0
        try:
            return facing.observe(frame, hit, self._facing_template,
                                  self._facing_template_dir)
        except Exception as e:
            self._log_detect_error(time.time(), '朝向观测', e)
            return None, 0.0, 0.0

    def _scan_region(self, frame, w, h, name, cfg, now):
        """慢通道:中央搜索区分块 OCR。命中则更新锚点、刷新身份时间戳、按需裁模板。

        节流由调用方决定(常规节流 / 丢锚立即重扫 / 身份复验),这里只管扫和记账 ——
        两个调用点各抄一份"命中后要做什么"迟早分叉,身份时间戳漏刷一处就等于验名失效。
        OCR 抛异常按"这一级没拿到"处理,绝不冒泡(见 _resolve_anchor 文档)。
        """
        region = anchor.search_region(w, h, cfg['锚点搜索区宽(比例)'], cfg['锚点搜索区高(比例)'],
                                      cfg['锚点搜索区中心Y(比例)'])
        try:
            hit = anchor.find_in_region(frame, name, region)
        except Exception as e:
            hit = None
            self._log_detect_error(now, '慢通道锚点 OCR', e)
        if hit is None:
            return None
        self._update_anchor(hit, now)
        self._last_identity_hit = now   # 名字牌真实命中:身份保鲜从这刻起算
        if (hit.text or '').strip() == name:
            self._capture_nametag_template(frame, hit)
        return hit

    def _resolve_anchor(self, frame, now, cfg, players=None):
        """按阶梯拿角色锚点,返回 (Anchor, 来源标签)。任何一级都不停任务。

        模板分片快通道(白字二值化模板竖切分片匹配 + 暗底验证,零 OCR 开销;
        怪/宠的名字牌盖住一半也照样命中,命中后验证暗底拒绝云/天空误匹配)
        → OCR 快通道(上次锚点附近小窗,寻怪中超龄时小窗跟外推位置) → **YOLO 关联级**
        (名字牌两级都没拿到时,用同拍检出的 player 框接管;身份保鲜兜底防认错路人,
        spec §3.3/§3.4) → 慢通道(中央区分块,节流) → 沿用上次(寻怪中超龄则按外推
        位置回) → 回退(屏幕中心 x + 最后已知层高 y)。
        名字牌被遮挡 OCR 连续失败时,攻击区不再冻在旧位置——有模板一帧咬住真实位置,
        没模板则边走路边外推,怪进区就能接战(2026-08-06 实测"身边很多怪时一直寻怪
        不攻击"根因,spec §4.2)。
        OCR/模板调用可能抛异常(模型/引擎故障等),任一通道抛出都当作"这一级没拿到
        锚点"处理,绝不允许异常冒泡出去——冒泡到 run() 外层会被框架 TaskExecutor 的
        通用 except 抓住并直接 disable() 整个任务,连保命/喝药都会停,违反
        "无怪只停手,任务继续跑"的契约。
        players=None(旧 3 参调用/定频模式,本拍无推理)时 YOLO 级短路、行为完全退回
        旧阶梯;players=[](推理了但全屏无 player 框)正常走完 YOLO 级并记 yolo全屏=0。
        用 None/[] 区分「没推理」与「推理了没框」——全屏=0 要可达,否则「YOLO 到底
        有没有看见人」仍是盲区。生产唯一调用点恒传真实 list,None 默认值只服务旧测试调用。
        """
        self._last_yolo_info = None   # 本拍观测先清:(门内候选数, 关联距 or None, 全屏框数);None=本拍 YOLO 级未到达
        h, w = frame.shape[:2]
        centre = anchor.Anchor(w / 2.0, h / 2.0, 0)
        name = (cfg['角色名'] or '').strip()
        if not name:
            return centre, 'fallback'

        # 蓝框=锚点搜索区(与 _draw_debug 画的「名字搜索范围」同一区域)。
        # 模板匹配与快通道 OCR 的窗口都裁到它里面——蓝框是锚点搜索的合法边界,
        # 不许任何通道跑框外(框外的组队列表/状态栏写着一模一样的角色名)。
        region = anchor.search_region(w, h, cfg['锚点搜索区宽(比例)'],
                                      cfg['锚点搜索区高(比例)'],
                                      cfg['锚点搜索区中心Y(比例)'])

        if self._anchor is not None:
            search_x = self._extrapolated_anchor_x(now, cfg)
            center = (search_x, self._anchor[1])
            # 模板分片快通道:每次 OCR 完整命中都会自动更新模板(见 _capture_nametag_template),
            # 名字牌一被怪盖住左半,右半片照样命中,OCR 反而读不出东西——这条通道正是为
            # 这个时刻准备的。verify_dark=True:命中后再验证位置周围有暗底,
            # 拒绝云/天空误匹配(名字牌有暗色半透明底框,云没有)。
            if self._nametag_template is not None and cfg['模板分片匹配开关']:
                try:
                    hit = anchor.split_match(frame, self._nametag_template, center,
                                             FAST_HALF_W, FAST_HALF_H, cfg['模板匹配阈值'],
                                             verify_dark=True, clamp_region=region)
                except Exception as e:
                    hit = None
                    self._log_detect_error(now, '模板分片匹配', e)
                # 纵向合理性(spec §3.8):模板拿自己上一拍的输出当下一拍搜索中心,
                # 一次误匹配就自我强化——匹配落在窗顶边时每拍恒定上移
                # half_h - 模板高/2 = 62px,实测一路飘到屏幕顶再也回不来。
                # 超帽子的当误匹配丢弃,落到验名的 OCR 通道去重建 y。
                if hit is not None and not farm_logic.template_hit_plausible(
                        hit.y, self._anchor[1]):
                    hit = None
                if hit is not None:
                    self._update_anchor(hit, now)
                    # 模板**不**刷新身份时间戳:它是像素匹配,命中的 text 是空串,
                    # 根本没验名。让它刷新 = 误匹配把 §3.7 的复验永久锁死,
                    # 「飘到半空再也回不来」的另一半根因(spec §3.4 修正)
                    return hit, 'template'
            try:
                hit = anchor.find_in_window(frame, name, center, FAST_HALF_W, FAST_HALF_H,
                                            clamp_region=region)
            except Exception as e:
                hit = None
                self._log_detect_error(now, '快通道锚点 OCR', e)
            if hit is not None:
                self._update_anchor(hit, now)
                self._last_identity_hit = now   # 名字牌真实命中:身份保鲜从这刻起算
                if (hit.text or '').strip() == name:  # 完整命中才裁模板
                    self._capture_nametag_template(frame, hit)
                return hit, 'window'
            identity_fresh = now - self._last_identity_hit <= cfg['身份保鲜(秒)']
            # 身份复验慢扫(spec §3.7):身份过期时,慢扫必须排在 YOLO 之前。
            # YOLO 级一命中就 return,下面那段慢扫根本走不到——实测慢扫占比被饿到
            # 0.6%(8-08 基线 2.2%),而它是唯一验名、也是唯一能在任意位置(不限
            # 上次锚点附近的小窗)找回角色的通道。没有它,YOLO 认错人之后
            # _update_anchor 还会刷新 _anchor_time、清掉 _force_rescan,丢锚立即
            # 重扫也不会触发,锚点就永久钉在路人身上。扫不到照样落到 YOLO 级,
            # 只加验名机会,不新增丢锚。
            if (cfg.get('身份复验开关') and not identity_fresh
                    and now - self._last_identity_scan >= cfg['身份复验间隔(秒)']):
                self._last_identity_scan = now
                # 慢扫最坏 235ms,同一拍绝不扫第二次:两个节流都记上,底下常规/强制
                # 两条路径本拍自然都不会再扫。受击/超龄想要的那次慢扫已经发生,
                # 悬着的 _force_rescan 按已消费处理(spec §3.5「命中即清」的同源语义)
                self._last_anchor_scan = now
                self._last_forced_rescan = now
                self._force_rescan = False
                hit = self._scan_region(frame, w, h, name, cfg, now)
                if hit is not None:
                    return hit, 'region'
            # YOLO 关联级(spec §3.3):名字牌两条通道都没拿到,用同拍 player 框接管。
            # 放在 OCR 之后——名字牌可读时身份持续刷新;放最前快通道永远轮不到,
            # 身份就再也不校准。冷启动(_anchor is None)不进本块:外层 if 已保证。
            if cfg.get('YOLO角色定位开关') and players is not None:
                # 门随「距上次真观测的时长」缩放(位移合理性,spec §3.3):相邻拍
                # 收到 ~170px,路人挤不进来;久未观测再放回固定上限
                gate_w, gate_h = farm_logic.player_gate_size(
                    now - self._last_anchor_hit if self._last_anchor_hit else None)
                gated = farm_logic.gate_player_boxes(players, center, gate_w, gate_h)
                # 到达即留痕(spec §3.3):拒绝拍记门内/全屏(全屏含 0——
                # 「没检出 vs 未到达」不再盲区),接受拍在下面用真实关联距覆盖
                self._last_yolo_info = (len(gated), None, len(players))
                pbox = farm_logic.select_player_box(
                    gated, center, identity_fresh, gate_w, gate_h)
                if pbox is None and cfg.get('丢锚唯一框接管开关'):
                    # 末级安全网(spec 2026-08-10 §3.4):丢锚超 1s + 全屏唯一框
                    # + 同层 → 直接接管。pred_y 用搜索中心 y(=最后锚点 y,
                    # 外推不推 y,纵向先验仍可信)
                    pbox = farm_logic.select_lost_unique_box(
                        players, center[1], now - self._anchor_time)
                if pbox is not None:
                    px_, py_ = farm_logic.player_box_anchor(pbox)
                    pseudo = anchor.Anchor(px_, py_, pbox.width)
                    # 伪锚点 = 框中心换算到**名字牌**坐标系(实测框中心比名字牌高
                    # 64px)。_anchor 存的一直是名字牌位置,下一拍的 OCR 小窗、模板
                    # 窗、关联门都按它定心——换算成身体坐标会让整条阶梯错位
                    # 64px。body_center() 再减 88 得到的落点,与名字牌拍完全一致,
                    # 下游(接敌区/同层/朝向)全部不用改(spec §3.4)
                    self._last_yolo_info = (len(gated),
                                            abs(pseudo.x - center[0]),
                                            len(players))
                    self._update_anchor(pseudo, now)
                    return pseudo, 'yolo'

        # 丢锚立即重扫(spec §3.5):三级全失 + (受击 或 锚点超龄) → 绕过常规 2s 节流。
        # 丢锚常由击退位置跳变引起,常规节流恰好卡在最需要慢扫的时刻(基线慢扫占 2.2%)。
        # _anchor_time is None(冷启动)不参战:无锚常态保持旧 2s 节奏,不许 0.5s 高频扫。
        force = (cfg.get('丢锚立即重扫开关')
                 and (self._force_rescan
                      or (self._anchor_time is not None
                          and now - self._anchor_time > cfg['锚点刷新间隔(秒)'])))
        if farm_logic.should_rescan_anchor(now, self._last_anchor_scan,
                                           cfg['锚点刷新间隔(秒)'], force=force,
                                           last_forced=self._last_forced_rescan):
            self._last_anchor_scan = now
            if force:
                self._last_forced_rescan = now
            self._force_rescan = False   # 消费:这次扫描就是它要的那次
            hit = self._scan_region(frame, w, h, name, cfg, now)
            if hit is not None:
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

    def _key_sendable(self):
        """按键此刻能否真送进游戏(窗口在前台)。

        pydirect 在窗口失焦时只 log 一条 ERROR 就 return
        (ok/device/interaction_methods/pydirect.py:34),而 BaseTask.send_key 照样
        返回 True——任务层看不出失败。朝向是纯"盲写"状态:按键丢了却仍把 _facing
        推进,之后 attack_turn_direction 认为朝向已对不再补转,角色会背对着怪一直
        按攻击键,且不会自愈(日志实测有 can't click on left/right 记录)。
        拿不到 executor/interaction(裸构造、离线测试)时按"能发"处理,不改变原行为。
        """
        try:
            return self.executor.interaction.clickable()
        except Exception:
            return True

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

    def _draw_debug(self, cfg, body, zone, attack_area, mobs, mob_present, attack_present,
                    aoe_ready=False, search_region=None, feet_y=None, frame_w=None):
        """画玩家框(绿)/接敌区框(细,蓝=无怪红=有怪)/攻击区框(粗,同色)/怪物框(黄)+脚底点(青)。
        群攻就绪时接敌区框加粗(1→3)且标签改 接敌区(群攻),给 E2E 判据 D 一个可视对象。
        画法照抄已移除的 WarriorDebugTask._draw_debug 的 get_overlay_view().draw + frame_ratio 换算(见 git 历史),
        用独立 key(DEBUG_OVERLAY_KEY)。"""
        overlay = self.get_overlay_view()
        if overlay is None:
            return
        pw, ph = cfg['玩家宽(像素)'], cfg['玩家高(像素)']
        zx0, zy0, zx1, zy1 = zone
        zone_color = ZONE_HOT_COLOR if mob_present else ZONE_IDLE_COLOR
        # 群攻态在闭包外定死:paint 是 Qt 重绘时才执行的,那时 now 早过去了,
        # 在闭包里现调 _aoe_ready 会画出与本拍决策不一致的框(spec §4)。
        zone_pen_width = 3 if aoe_ready else 1
        zone_label = '接敌区(群攻)' if aoe_ready else '接敌区'
        ax0, ay0, ax1, ay1 = attack_area
        attack_color = ZONE_HOT_COLOR if attack_present else ZONE_IDLE_COLOR

        def paint(painter, widget):
            ratio = widget.frame_ratio()
            # 每帧读最新配置（GUI 改开关后可能重建 dict 对象）
            c = self.config

            def rect(x, y, w, h):
                return QRectF(x * ratio, y * ratio, w * ratio, h * ratio)

            # 名字搜索范围（蓝虚线）
            if c.get('显示名字搜索范围', True) and search_region is not None:
                painter.setPen(QPen(ANCHOR_SEARCH_COLOR, 2, Qt.PenStyle.DashLine))
                painter.drawRect(rect(search_region[0], search_region[1],
                                      search_region[2] - search_region[0],
                                      search_region[3] - search_region[1]))

            # 寻怪同层带（青虚线）
            if c.get('显示寻怪同层带', True) and feet_y is not None and frame_w is not None:
                tol = c.get('寻怪同层容差(像素)', 60)
                painter.setPen(QPen(SEEK_BAND_COLOR, 2, Qt.PenStyle.DashLine))
                painter.drawRect(rect(0, feet_y - tol, frame_w, 2 * tol))

            # 玩家框（绿）
            if c.get('显示玩家框', True):
                painter.setPen(QPen(PLAYER_COLOR, 2))
                painter.drawRect(rect(body[0] - pw / 2, body[1] - ph / 2, pw, ph))
                painter.drawText(rect(body[0] - pw / 2, body[1] - ph / 2 - 20, 100, 20), '玩家')

            # 接敌区（细线）+ 攻击区（粗线）
            if c.get('显示攻击区', True):
                painter.setPen(QPen(zone_color, zone_pen_width))
                painter.drawRect(rect(zx0, zy0, zx1 - zx0, zy1 - zy0))
                painter.drawText(rect(zx0, zy0 - 20, 140, 20), zone_label)

                painter.setPen(QPen(attack_color, 4))
                painter.drawRect(rect(ax0, ay0, ax1 - ax0, ay1 - ay0))
                painter.drawText(rect(ax0, ay1 + 4, 100, 20), '攻击区')

            # 怪物框（黄）+ 脚底点（青）
            if c.get('显示怪物框', True):
                for mob in mobs:
                    painter.setPen(QPen(MOB_COLOR, 2))
                    painter.drawRect(rect(mob.x, mob.y, mob.width, mob.height))
                    painter.drawText(rect(mob.x, mob.y - 20, 100, 20), '怪物')
                    fx, fy = farm_logic.mob_feet(mob)
                    painter.setPen(QPen(MOB_FOOT_COLOR, 4))
                    painter.drawPoint(QPointF(fx * ratio, fy * ratio))

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

        完整检测拍与寻怪快速刷新拍共用。攻击键本身不在这里按——由 _do_attack
        按"_last_attack_present"以 攻击间隔 轻点。"""
        # 一拍一次推理(find_all),mob/player 从结果里纯过滤分流(spec §3.2):
        # 找怪走 find_mobs(boxes=)(不含 player),锚点 YOLO 级走 players。模型类
        # 别 1 = 任意玩家角色,身份判别完全在融合层(spec §3.3),这里只按名字筛。
        try:
            all_boxes = self.find_all(frame)
        except Exception as e:
            all_boxes = []
            self._log_detect_error(now, 'YOLO 检测', e)
        players = [b for b in all_boxes if getattr(b, 'name', None) == 'player']
        anchor_hit, source = self._resolve_anchor(frame, now, cfg, players)
        body = anchor.body_center(anchor_hit, cfg['名字牌到身体偏移(像素)'])
        self._last_body_x = body[0]          # 走动确认要用
        if cfg.get('朝向观测开关'):
            self._maybe_capture_facing_template(
                frame, anchor_hit, source, (cfg['角色名'] or '').strip())
        observed, obs_s, obs_flip = self._observe_facing(frame, anchor_hit, source)
        # 纠正前的信念必须先存下来:它是判据 C 的尺子。纠正之后 self._facing
        # 恒等于 observed,分歧行就永远不会触发了——修复会把测量它的仪器弄瞎,
        # 之后没人分得清分叉率是真降了还是只是看不见了(spec §3.4)。
        belief_before_obs = self._facing
        # 朝向纠正:观测给出答案就以它为准。位置是关键——必须在下面
        # facing_half_zone 取用 self._facing 之前,晚一行本拍攻击区仍按错朝向算,
        # 白纠正一拍(spec §3.2)。判据 A=77.3%/B=0.4% 已放行写回(spec §2.1)。
        if (cfg.get('朝向纠正开关') and observed is not None
                and observed != self._facing):
            self._facing = observed
        zone = farm_logic.attack_zone(body, cfg['攻击区宽(像素)'], cfg['攻击区高(像素)'])
        self._last_zone = zone   # 垫步定向读:最近一次检测拍的接敌区
        # 有向攻击区 = 接敌区的面朝侧一半(spec §4)。zone 从此是「接敌区」:
        # 管转向/寻怪/坐椅/走位;attack_area 管「能不能打」,只喂 _do_attack。
        # 用的是本拍转向「之前」的 self._facing——此处 facing_before 还没赋值,
        # 但同值。拿转向后的新朝向立刻判定等于又一次相信盲写信念(spec §5.1)。
        attack_area = (zone if cfg.get('攻击区形状') == '群体(对称)'
                       else farm_logic.facing_half_zone(zone, body[0], self._facing))
        try:
            mobs = self.find_mobs(frame, boxes=all_boxes)
        except Exception as e:
            mobs = []
            self._log_detect_error(now, 'YOLO 找怪', e)
        centres = [(m.x + m.width / 2, m.y + m.height / 2) for m in mobs]
        self._last_centres = centres   # 垫步定向读:最近一次检测拍的怪中心
        # 屏幕上有没有怪(不限攻击区):经验停滞守卫据此判断"是真没收益"还是"本来就没得打"
        self._last_any_mob = len(mobs) > 0
        # 去抖:漏检一拍不退出攻击态(见 farm_logic.mob_present_debounced)。
        # 必须在 mob_present 这一层去抖而不是只包住攻击键——它同时门控寻怪与坐椅,
        # 只抖攻击键会出现"一边追一边挥"的错乱状态
        raw_present = farm_logic.mob_in_zone(centres, zone)
        if raw_present:
            self._last_mob_seen = now
        mob_present = farm_logic.mob_present_debounced(
            raw_present, now, self._last_mob_seen, cfg['丢怪保持(秒)'])
        self._last_mob_present = mob_present
        # 接战/寻怪的分支门用一个更短的宽限:丢怪保持(1.0s)是为攻击键兜 YOLO
        # 漏检的,那个理由不适用于寻怪 —— 它把「起步走路」也禁掉了整整一秒
        # (实测 11.5% 的拍卡在这个窗里,其中 3310 拍屏幕上有怪,spec §3.2)。
        # _last_mob_present 仍用长宽限:坐椅/防挂机走位不该在怪刚消失 0.3s 就触发。
        seek_hold = farm_logic.mob_present_debounced(
            raw_present, now, self._last_mob_seen, cfg['寻怪起步宽限(秒)'])
        raw_attack = farm_logic.mob_in_zone(centres, attack_area)
        if raw_attack:
            self._last_attack_seen = now
        # 保持只为 YOLO 漏检服务:怪确在接敌区但不在攻击区(raw_present and not raw_attack)
        # 是「确定性换边」的证据,必须立刻清掉攻击信号,不许被保持窗口吞掉——
        # 否则每次换边后仍有 ≤ 丢怪保持(秒) 的空按(§1 bug 的有界残余)。
        # 群体(对称)模式下 raw_attack == raw_present,此条件恒为 False,惰性。
        self._last_attack_present = farm_logic.mob_present_debounced(
            raw_attack, now, self._last_attack_seen, cfg['丢怪保持(秒)']) \
            and not (raw_present and not raw_attack)
        # 节拍门与分支门同源:分支用 寻怪起步宽限 判「该起步寻怪了」,节拍必须在同一刻
        # 松开攻击档。攻击键可以被 丢怪保持(1.0s) 撑着继续挥(YOLO 单帧漏检的保护),
        # 但检测节拍跟着一起慢就会出现:攻击区早空了、分支已走寻怪路径,下一拍却仍按
        # 攻击间隔排,起步寻怪白等一个攻击拍(spec §3.1/§3.2 衔接漏洞)。
        # 2026-08-08 实弹:这种拍占 5.6%(444/7896),其后拍间隔中位 0.708s。
        # 必须在检测拍取快照、不能在 should_detect 处按 now 现算:稳态在打时拍间隔
        # (攻击间隔)本就大于宽限,现算会让攻击档整个塌成空闲档,负载回归。
        self._detect_attacking = farm_logic.mob_present_debounced(
            raw_attack, now, self._last_attack_seen, cfg['寻怪起步宽限(秒)'])
        # 群攻计数:接敌区内怪数(原始值,不去抖,见 farm_logic.crowd_present)。
        # 这一份 in_zone 同时喂给决策日志——同一个数算两遍是将来漂移的种子。
        in_zone = [x for x, y in centres if farm_logic.point_in_zone((x, y), zone)]
        self._last_zone_count = len(in_zone)
        self._last_zone_count_time = now   # 新鲜度戳,群攻判据要用(见 _aoe_ready)
        # 本拍会不会放群攻:转向门与 overlay 都用这一份,不各自再调一次 ——
        # 判据必须与 _do_attack 那次求值同值,否则会出现「以为要群攻所以没转向、
        # 结果群攻没发」的两头落空拍(spec §3.4)。
        aoe_ready = self._aoe_ready(cfg, keys, now)
        # 取纠正前的信念:决策行的 朝向=A→B 因此能同时反映「纠正」与「转向」两种
        # 变化(A=纠正前、B=本拍结束),分歧行也据它判(spec §3.4)。
        facing_before, turn = belief_before_obs, None
        if seek_hold:
            self._seek_dir = None  # 怪进攻击区了,停追,原地攻击
            # 先松开寻怪长按的方向键:长按没松的话,下面的转向轻点会被"还在走"吞掉,
            # 攻击长按时面朝还对着反方向 → 打空(_release_seek_key 自带 None 守卫)
            self._release_seek_key()
            # 面向怪再攻击:面朝侧攻击区内已经没怪了才转向(目标侧锁定,
            # 见 farm_logic.attack_turn_direction)。旧版每拍重选最近怪再判边,
            # 区内左右都有怪时最近的那只一换边就转一次,实测换边率 38%,
            # 角色光转向打不出输出——这是"左右转向不攻击"的主因。
            # 转向键送不出去(窗口失焦)时整块跳过:_facing 不许盲写推进,
            # 否则之后认为朝向已对不再补转,角色背对怪一直挥空且无法自愈。
            # 攻击键本身由 _do_attack 按 攻击间隔 轻点,不在这里按
            turn = farm_logic.attack_turn_direction(self._facing, body[0], centres, zone)
            # 硬直抑制:受击后 硬直抑制窗(秒) 内不按转向键——击退硬直中 tap 会被
            # 游戏吞掉,但下面的盲写 _facing 照常执行,键没生效信念却已翻转 → 打空。
            # 抑制窗把转向与盲写整块跳过,等硬直过了再补转(见 farm_logic.stun_suppressed)。
            # 群攻拍不转向:双向命中不需要朝向,转向在这一拍是纯支出 ——
            # 一次方向键 tap + 下面那句 self._last_detect = 0.0 作废检测节拍。
            # 只跳过「真发群攻」的这一拍;群攻冷却中的拍照常转向,否则冷却那
            # 2 秒里怪全在背侧时,单体攻击区(面朝侧半区)是空的,角色站着挨打
            # (spec §3.6)。_facing 在群攻拍完全不动,也就不会有「盲写了朝向、
            # 下一拍单体按着错朝向打空」的新分叉。
            if (turn is not None
                    and not aoe_ready
                    and farm_logic.turn_allowed(now, self._last_turn, cfg['转向冷却(秒)'])
                    and not farm_logic.stun_suppressed(
                        now, self._last_hit, cfg['硬直抑制窗(秒)'])
                    and self._key_sendable()):
                key = '左移键' if turn == 'left' else '右移键'
                self.send_key(keys[key], down_time=TURN_TAP_SECONDS)
                self._last_turn = now
                self._facing = 'LEFT' if turn == 'left' else 'RIGHT'
                # 转向本身就是"活动":走位倒计时从头算,不紧跟着又走位
                # (刚转完向立刻两段走位会显得很怪;且正在打怪就不是挂机闲逛)
                self._last_walk = now
                # 作废检测节拍,让下一拍立刻来。攻击区是按转向「前」的朝向算的
                # (见上面 :583 的 spec §5.1 注释,那个决定不变),新朝向要下一拍
                # 才生效;而转向只发生在接战分支,那一拍 _detect_attacking 常被
                # 寻怪起步宽限 撑着 True,下一拍就按 攻击间隔(0.7s)排 ——
                # 攻击区因此要等满一个攻击拍才翻过去(2026-08-08 实测端到端
                # p90=0.627s、>0.5s 占 21.5%,转向拍到下一拍间隔 p90=0.706s)。
                # 0.0 是 _reset_state 同款「从未检测过」哨兵:下一次主循环 tick
                # (10Hz)必然放行,而且那一拍是真正重新观测过的,不需要相信盲写信念。
                self._last_detect = 0.0
        else:
            # 自动寻怪:区内没怪 → 在同层(脚底高度容差内)找最近的怪,记下要朝它走的方向。
            # 只追同层:跨平台的怪走不过去,追了只会撞墙/掉台子。
            prev_seek = self._seek_dir   # 方向锁定要用上一拍的方向,先存下来再清
            self._seek_dir = None
            if cfg['寻怪开关']:
                entries = [(m.x + m.width / 2, m.y + m.height) for m in mobs]
                seek_raw = farm_logic.seek_direction(entries, body[0], anchor_hit.y,
                                                     cfg['寻怪同层容差(像素)'], prev_seek)
                if seek_raw is not None:
                    self._last_seek_seen = now
                # 寻怪去抖:这一拍漏检也按上一拍方向继续走一段(寻怪保持),别一漏检就停
                self._seek_dir = farm_logic.seek_persist(seek_raw, prev_seek, now,
                                                         self._last_seek_seen,
                                                         cfg['寻怪保持(秒)'])
                if self._seek_dir is not None:
                    # 寻怪本身就在移动=活动中,防挂机走位倒计时顺延
                    self._last_walk = now
                    # 起步即停手:_last_attack_present 可能还被 丢怪保持 撑着 True,
                    # 不作废的话 _do_attack 会一边追一边朝空气轻点攻击键
                    self._last_attack_present = False
        # 画框放在转向之后:attack_area 是按本拍转向「前」的朝向算的(决策必须如此,
        # 见上面 spec §5.1 的注释),直接画它,悬浮窗就永远比角色朝向慢一拍 ——
        # 排查时会把「节拍慢」误读成「转了但攻击区没跟上」(2026-08-09 就是这么发现的)。
        # 这里只改画什么、不改判什么:决策与决策日志用的仍是 attack_area。
        # 群体(对称)下攻击区本就等于整个接敌区,转向不参与,原样画。
        draw_area = (attack_area
                     if turn is None or cfg.get('攻击区形状') == '群体(对称)'
                     else farm_logic.facing_half_zone(zone, body[0], self._facing))
        if self._boxes_enabled():
            w, h = frame.shape[1], frame.shape[0]
            region = anchor.search_region(w, h, cfg['锚点搜索区宽(比例)'],
                                          cfg['锚点搜索区高(比例)'],
                                          cfg['锚点搜索区中心Y(比例)'])
            self._draw_debug(cfg, body=body, zone=zone, attack_area=draw_area,
                             mobs=mobs, mob_present=mob_present,
                             attack_present=self._last_attack_present,
                             aoe_ready=aoe_ready,
                             search_region=region, feet_y=anchor_hit.y, frame_w=w)
        else:
            self._clear_debug()
        if cfg.get('决策日志开关'):
            self._log_decision(source, anchor_hit, body, zone, attack_area, centres,
                               in_zone, mobs,
                               raw_present, mob_present, self._last_attack_present,
                               facing_before, turn, observed, obs_s, obs_flip)

    def _log_decision(self, source, anchor_hit, body, zone, attack_area, centres, in_zone,
                      mobs, raw_present, mob_present, attack_present, facing_before, turn,
                      observed, obs_s, obs_flip):
        """逐拍决策留痕(默认关,见配置 决策日志开关)。

        排"左右转向不攻击"时必须知道:锚点是哪条通道给的(fallback/cached 说明角色
        位置本身不可信)、区内怪的左右分布(两侧都有才可能来回换目标)、朝向有没有变、
        按键能不能送出去。少任何一项都只能靠猜。字段一行写完,方便 grep 「决策」后
        直接看序列。

        同层脚/同层心/近怪 三项见 decision_log_line 的说明:它们是 Task 6
        改同层口径之前唯一的观测手段(spec §2.3)。
        """
        left = sum(1 for x in in_zone if x < body[0])
        attack_in = [x for x, y in centres
                     if farm_logic.point_in_zone((x, y), attack_area)]
        tol = self.config.get('寻怪同层容差(像素)', 60)
        same_feet = sum(1 for m in mobs
                        if farm_logic.same_floor(m.y + m.height, anchor_hit.y, tol))
        same_center = sum(1 for m in mobs if zone[1] <= m.y + m.height / 2 <= zone[3])
        near = None
        if mobs:
            m = min(mobs, key=lambda m: abs(m.x + m.width / 2 - body[0]))
            near = (m.x + m.width / 2 - body[0],
                    (m.y + m.height) - anchor_hit.y,
                    (m.y + m.height / 2) - body[1])
        yolo_cands, yolo_dist, yolo_full = self._last_yolo_info or (None, None, None)
        self.log_debug(decision_log_line(
            source, body[0], anchor_hit.y, centres, in_zone, left,
            same_feet, same_center, near,
            raw_present, mob_present, attack_in, attack_present,
            facing_before, self._facing, turn, self._seek_dir,
            self._key_sendable(), observed, obs_s, obs_flip,
            yolo_cands=yolo_cands, yolo_dist=yolo_dist, yolo_full=yolo_full))
        if observed is not None and facing_before in ('LEFT', 'RIGHT') \
                and observed != facing_before:
            now = time.time()
            self.log_debug(divergence_log_line(
                facing_before, observed, obs_s, obs_flip,
                now - self._last_attack, now - self._last_hit,
                now - self._last_turn))

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

    def _aoe_ready(self, cfg, keys, now):
        """本拍要不要放群攻 —— 转向门(_detect_and_act)与攻击门(_do_attack)的
        唯一判据,两处必须调同一个方法。

        分头写就会出现「以为要群攻所以没转向、结果群攻没发」的两头落空拍:
        那一拍既不转向也不输出,比不做这个功能还差(spec §3.4)。

        同一 tick 内 run() 的顺序是 _detect_and_act → _do_attack,期间没有任何
        代码写 _last_zone_count / _last_zone_count_time / _last_attack / _last_hit,
        所以两次求值必然同值。改动这四个状态的写入位置前,先确认这个前提还成立。

        **群攻不另设节拍,与单体共用 攻击间隔(秒)** —— 到点了看区内怪数决定按哪个键。
        原设计给过一个独立的 群攻间隔(秒)=2.0,两条理由后来都不成立:
        「群攻耗蓝是单体数倍」被判定不是问题;「独立节拍保护群攻施法窗」站不住 ——
        单体自己就在 攻击间隔=0.7 下自断施法(实测施法时长 0.7-1.0s,见
        2026-08-08-facing-observer-design.md:66),群攻并不特殊,而且代码里根本
        没有施法窗模型(_busy_until 在那份 spec §6 被显式推迟,全库无此变量)。
        独立节拍反倒引入相位差:两个节拍互质地各走各的,群攻会落在上次单体后
        0.6s(< 攻击间隔 0.7)。共用一个节拍从构造上消掉这一整类问题。

        **计数必须是本拍现测的**(_last_zone_count_time == now)。_do_attack 每个
        10Hz 拍都跑,而计数只在检测拍写;没有这道门,怪清光后的非检测拍会拿着上一个
        检测拍的旧计数放空群攻 —— 正是 farm_logic.crowd_present 说「不加保持窗」
        要避免的那件事,逐拍求值会把它从后门放回来。转向门那次求值天然满足这道门
        (它就在写完计数的几行之后),所以这道门只对 _do_attack 起作用。

        群攻键留空 = 功能关闭(同 椅子键(可留空) 的约定);阈值在这里现读,
        GUI 里改 群攻怪数阈值 立刻生效,不用等下一个检测拍。
        """
        return bool(
            cfg['攻击模式'] == '检测'
            and keys.get('群攻键(可留空)', '')
            and self._last_zone_count_time == now
            and farm_logic.crowd_present(self._last_zone_count,
                                         cfg['群攻怪数阈值'])
            and farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)'])
            and not farm_logic.stun_suppressed(
                now, self._last_hit, cfg['硬直抑制窗(秒)']))

    def _do_attack(self, cfg, keys, now):
        """攻击:检测模式且最近一次检测拍「有向攻击区」内有怪 → 按 攻击间隔 轻点攻击键。

        2026-08-07 从长按改回轻点(df9b020 曾改成"长按连挥",这里退回)。长按只是
        每拍重复 keyDown,游戏侧收不到新的"按下"边沿——角色被怪击退打断施法后
        不会重新起手。实测(02:07-02:12 逐拍日志)最长一次按住 27 秒中间没松过键,
        期间区内一直有怪却打不出输出;且挥砍中 body_x 跳变 >80px 的拍占 19%
        (其余状态仅 5%),说明挥砍时被击退非常频繁。轻点每次都有新的按下边沿,
        被击退后下一拍就能重新起手。
        接敌区内怪数达到 群攻怪数阈值 时改按群攻键(前后双向命中),那一拍不按
        单体攻击键;判据见 _aoe_ready。
        定频模式不在这里管,由 run() 按 攻击间隔 定时轻点。
        """
        if cfg['攻击模式'] != '检测':
            return
        # 群攻优先,与单体二选一:被围时一发前后双向命中,比「转向 + 单体」划算,
        # 且不需要朝向(spec §3.9 行为矩阵)。
        # _last_attack = now 不是「顺带推进单体节拍」而是这条路径**自己的**节拍推进:
        # 群攻与单体共用同一条 攻击间隔 节拍,谁出手都由它记账(见 _aoe_ready)。
        # 漏写这一行的后果不是「单体打断群攻」,而是群攻每个 10Hz 拍连发。
        if self._aoe_ready(cfg, keys, now):
            self.send_key(keys['群攻键(可留空)'])
            self._last_attack = now
            if cfg.get('决策日志开关'):
                self.log_debug(aoe_log_line(self._last_zone_count,
                                            cfg['群攻怪数阈值']))
            return
        if (self._last_attack_present
                and farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)'])
                and not farm_logic.stun_suppressed(
                    now, self._last_hit, cfg['硬直抑制窗(秒)'])):
            # 攻击前垫步(战士可选):先朝最近怪所在侧轻点方向键再攻击。
            # 兜住 _facing 信念被击退/按键丢失破坏的盲区——区内有怪时
            # attack_turn_direction 认为"面朝侧还有目标"不转向,角色背对怪
            # 一直砍空气。垫步不信任信念,信念错则物理修正,信念对则是 no-op。
            # 键窗口不可点击时不垫步(方向键丢了 _facing 不许盲写,见 _key_sendable)。
            # 2 秒没攻击(空闲/寻怪中)不垫步:此时无朝向需求,垫步只会干扰寻怪移动。
            if (cfg.get('攻击前垫步开关')
                    and self._last_zone is not None
                    and (self._last_attack == 0.0 or now - self._last_attack < 2.0)):
                body_x = self._last_body_x if self._last_body_x is not None else CALIBRATED_SIZE[0] / 2
                side = farm_logic.attack_pre_tap_direction(
                    self._last_centres, self._last_zone, body_x)
                if side is not None and self._key_sendable():
                    key = '左移键' if side == 'left' else '右移键'
                    self.send_key(keys[key], down_time=PAD_STEP_TAP_SECONDS)
            self.send_key(keys['攻击键'])
            self._last_attack = now

    def _do_seek_move(self, cfg, keys):
        """寻怪移动:长按方向键向怪连续走(每拍重按一次、从不松开,直到
        变向/接战/无怪/开关关才松)——旧版每拍按下又松开(按 0.1s),
        刷新拍的 OCR+YOLO 阻塞期间键没按住,追怪时走走停停"一下一下";
        每拍重按还能在窗口短暂不可点击导致按键漏发时自动补上。"""
        if cfg['寻怪开关'] and self._seek_dir is not None:
            key = '左移键' if self._seek_dir == 'left' else '右移键'
            if self._seek_key is not None and self._seek_key != key:
                self.send_key_up(keys[self._seek_key])  # 换向:先松旧键
            if self._seek_key != key:
                # 换向/首次按下:重记起点,走动确认要从这一刻起算
                self._seek_start_body_x = self._last_body_x
            self.send_key_down(keys[key])
            self._seek_key = key
            # 方向键没真送进游戏时不推进朝向信念(同 _key_sendable 的说明):
            # 每拍都会重按,下一拍窗口回到前台自然补上
            if self._key_sendable():
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
        self._seek_start_body_x = None

    def _release_seek_key_light(self):
        """暂停回调专用轻量松键:只发 interaction.send_key_up,不走 send_key_up
        的 reset_scene/check_enabled 链。

        背景(F9 暂停 → GUI 未响应,2026-08-10):communicate.executor_paused 是
        DirectConnection,`_on_executor_paused` 跑在 GUI 主线程。而 send_key_up →
        reset_scene → check_enabled(check_pause=True) 在 paused=True 时调
        executor.sleep(1)——sleep 循环在 GUI 线程跑满 1 秒,期间还反复 WGC 取帧,
        窗口表现就是"切回 GUI 未响应"。暂停回调只需要"把按着的方向键抬起来",
        不需要 reset_scene/check_enabled/节流,直接用 interaction 原语发 keyUp。"""
        if self._seek_key is None:
            return
        try:
            keys = self.get_global_config('游戏按键')
            interaction = self.executor.interaction
            if interaction is not None:
                interaction.send_key_up(keys[self._seek_key])
        except Exception as e:
            self.log_error(f'暂停松键失败: {e!r}')
        self._seek_key = None
        self._seek_start_body_x = None

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

    def _release_attack_key_light(self):
        """暂停回调专用轻量松键,见 _release_seek_key_light 的线程/阻塞说明。"""
        if not self._attack_held:
            return
        try:
            keys = self.get_global_config('游戏按键')
            interaction = self.executor.interaction
            if interaction is not None:
                interaction.send_key_up(keys['攻击键'])
        except Exception as e:
            self.log_error(f'暂停松攻击键失败: {e!r}')
        self._attack_held = False

    def _release_held_keys(self):
        """松开全部长按键(寻怪方向键 + 攻击键)。"""
        self._release_seek_key()
        self._release_attack_key()

    def _release_held_keys_light(self):
        """暂停回调专用:全部长按键用轻量路径松开(不在 GUI 线程跑阻塞链)。"""
        self._release_seek_key_light()
        self._release_attack_key_light()

    def _on_executor_paused(self, paused):
        """F9 全局暂停时松开所有长按键——executor 暂停后 run() 不再被调用,
        不在这松键角色会一直走下去/打下去;恢复(False)不做事,下一拍会自动重新按下。

        必须用轻量松键路径:本回调经 DirectConnection 在 GUI 主线程执行,
        send_key_up → reset_scene → check_enabled 在 paused=True 时会触发
        executor.sleep(1) 阻塞 GUI 线程约 1 秒(期间还反复 WGC 取帧),
        表现为"切回 GUI 未响应"(2026-08-10 实测修复)。"""
        if paused:
            self._release_held_keys_light()

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
            # 分辨率不符:只提醒、不硬停(2026-08-10 用户口径,提醒而非硬性条件)。
            # 窗口切换/最小化瞬间也会拿到异常尺寸帧,先攒 10 帧确认防误报;
            # 整个任务只提醒一次(_size_warned 置位后不再发),提醒后不 return、
            # 照常处理当前帧(非校准分辨率下 ROI 会整体偏位,由用户自行权衡)。
            self._bad_size_frames += 1
            if not self._size_warned and self._bad_size_frames >= 10:
                self._size_warned = True
                self.log_warning(f'分辨率 {w}x{h} 非校准值 {CALIBRATED_SIZE[0]}x{CALIBRATED_SIZE[1]},ROI 会偏位——仅提醒一次,继续挂机', notify=True)
        else:
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

        # 1.5 受击检测(检测模式):HP 下降或锚点突变 → 被怪打 → 朝向信念失效。
        # 置 None + 重置转向冷却,下一检测拍 attack_turn_direction(None,...) 按最近怪
        # 定向补转向(farm_logic.py 未知朝向 fallback:朝最近怪定向)。0.0 哨兵天然放行
        # 冷却(turn_allowed:now-0 >= cooldown 恒真)——冷却是压"原地左右扭"的,
        # 不该压真正的击退纠正。对"击退翻不翻朝向"两种机制同时正确:
        # 翻了你补 tap 是纠错;没翻,朝怪 tap 50ms 是 no-op(已面朝该侧按方向键零代价)。
        if cfg['攻击模式'] == '检测' and farm_logic.knockback_debounced(
                farm_logic.knockback_detected(hp, self._prev_hp), now,
                self._last_hit, cfg['受击防抖(秒)']):
            if cfg.get('决策日志开关'):
                # 受击本身不写日志的话,「这次挂机到底被打了几次、每次朝向作废前是什么」
                # 全靠猜——决策行里没有这两项,事后无法判断本机制有没有生效。
                # prev_hp 目前必非 None(HP 是唯一接线的信号,见 farm_logic.knockback_detected);
                # 将来把位移信号也接上后可能为 None,这里先兜住。
                before = '?' if self._prev_hp is None else f'{self._prev_hp:.1%}'
                self.log_debug(f'受击 hp={before}→{hp:.1%} '
                               f'朝向={self._facing or "-"}(保留) 转向冷却重置')
            # 这里曾有 self._facing = None(作废朝向)。删掉的理由:它的唯一前提
            # 「受击可能让朝向失效」已被观测数据证伪——52 个分歧事件按「距上次受击」
            # 分桶,受击后 0.5s 内一次都没有,分布随时间单调上升(spec §2.2)。
            # 而清空的代价是确定的:facing_half_zone 在 None 时退化成整个对称区,
            # 实测 19 拍「面朝侧一只怪都没有却照常开火」(用实测朝向反判,spec §2.3)。
            # 它顺带提供的「打破目标侧锁定死锁」由朝向纠正正面接管(spec §3.3)。
            self._last_turn = 0.0
            self._last_hit = now
            self._force_rescan = True   # 击退=位置跳变:下一检测拍绕过慢扫节流立刻重扫(spec §3.5)
        self._prev_hp = hp

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
            # 检测拍三态节流:在打→攻击间隔;在追→寻怪刷新间隔;空闲→空闲刷新间隔。
            # 空闲那一档是「起步寻怪」唯一的入口 —— 旧实现把它绑在攻击间隔上,
            # 而快通道要求 _seek_dir 已经不是 None,只能刷新已有寻怪、
            # 发起不了新的(spec §3.1)
            if farm_logic.should_detect(
                    now, self._last_detect,
                    bool(self._detect_attacking), self._seek_dir is not None,
                    cfg['攻击间隔(秒)'], cfg['寻怪刷新间隔(秒)'],
                    cfg['空闲刷新间隔(秒)']):
                self._last_detect = now
                self._detect_and_act(frame, now, cfg, keys)
            # 攻击/寻怪移动:区内有怪 → 长按攻击键连续挥砍;寻怪 → 长按方向键。
            # 各自在条件不成立时松键(无怪/接战/无同层怪/开关关/切模式)
            self._do_attack(cfg, keys, now)
            self._do_seek_move(cfg, keys)
            # 在打/在追 = 忙:坐椅延迟从头算;长按的攻击/方向键已带角色起身,清坐椅标记
            if self._last_mob_present or self._seek_dir is not None:
                self._mark_busy(now)
        else:
            self._clear_debug()  # 定频模式没有锚点/攻击区,之前检测模式画过的框清掉
            # 硬直抑制同样作用于定频:受击(检测模式留下的 _last_hit)后 0.5s 内
            # 不按攻击键——硬直中按了浪费一个 攻击间隔 节拍
            if (farm_logic.should_attack(now, self._last_attack, cfg['攻击间隔(秒)'])
                    and not farm_logic.stun_suppressed(
                        now, self._last_hit, cfg['硬直抑制窗(秒)'])):
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
        elif self._last_any_mob is False:
            # 屏幕上一只怪都没有:空图/刷新间隙没收益是正常的,停滞计时暂停,
            # 免得把"没得打"误判成"无效挂机"。定频模式不跑找怪(_last_any_mob 恒为
            # None),保持旧行为照常计时。
            # 注意 2026-08-07 03:45 那次真实停机不属于此列:8 分钟 698 拍里怪=0 的
            # 拍数是 0(最少一拍也有 5 只、多数 9-11 只),满地是怪却零收益,正是该抓的
            self._last_exp_gain_time = now
        elif now - self._last_exp_gain_time > cfg['经验停滞上限(分钟)'] * 60:
            self.stop_farming('经验长时间不涨(无效挂机)')
            return
