"""打怪决策纯逻辑。不依赖游戏/框架,全部可离线单测。"""

import random


def need_hp_potion(hp_percent, threshold):
    return 0 <= hp_percent < threshold


def need_mp_potion(mp_percent, threshold):
    return 0 <= mp_percent < threshold


def is_emergency(hp_percent, threshold):
    return 0 <= hp_percent < threshold


def emergency_action(return_scroll_key):
    if return_scroll_key and return_scroll_key.strip():
        return 'return_scroll'
    return 'stop'


def potion_not_working(streak, limit):
    return streak >= limit


def potion_window_elapsed(now, last_press_time, interval):
    """喝药判定窗口是否已过:距上次按下药键够久,可以对比 HP 判效果/再喝一次。"""
    return now - last_press_time >= interval


def potions_exhausted(hp, hp_threshold, hp_count, mp, mp_threshold, mp_count):
    """count 为 None 表示 OCR 未读出(未知),不判耗尽。"""
    if hp_count == 0 and need_hp_potion(hp, hp_threshold):
        return 'hp'
    if mp_count == 0 and need_mp_potion(mp, mp_threshold):
        return 'mp'
    return None


def should_attack(now, last_attack_time, interval):
    return now - last_attack_time >= interval


def should_detect(now, last_detect, attacking, seeking,
                  attack_interval, seek_interval, idle_interval):
    """检测拍节流:三种状态各有各的节奏,取当前状态对应的间隔。

    - 在打(有向攻击区里有怪)→ 攻击间隔:检测本来就是为下一刀服务的,
      没必要更快;这一段占挂机时间 41%,保持原节奏 = 负载不回归。
    - 在追 → 寻怪刷新间隔:目标死了/换近了要立刻改方向。
    - 空闲(都不是)→ 空闲刷新间隔。**这是「起步寻怪」唯一的入口。**

    旧实现把「起步」也绑在攻击间隔上,快通道的进入条件是
    `_seek_dir is not None`,于是它只能刷新一个已经存在的寻怪、
    永远发起不了新的。实测停手→起步中位 1.19s / p90 3.61s,
    而 寻怪刷新间隔 调到 0.1s 对这一步完全无效(spec §3.1)。

    「在打」优先于「在追」:攻击区里有怪就是在打,不该被寻怪间隔拉快。
    边界与 should_attack 同口径(>= 即放行)。
    """
    if attacking:
        interval = attack_interval
    elif seeking:
        interval = seek_interval
    else:
        interval = idle_interval
    return now - last_detect >= interval


def attack_zone(center, width, height):
    """以 center 为心的攻击区 (x0, y0, x1, y1)。左右对称,不分朝向。"""
    cx, cy = center
    return cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2


def facing_half_zone(zone, body_x, facing):
    """有向攻击区 = 对称接敌区 zone 的面朝侧一半 (x0, y0, x1, y1)。

    为什么要分两个区(spec §2):对称区在同时干两件事——决定「要不要转向」
    (必须看左右两侧,不看背后就不知道有没有值得转过去的怪)和决定「能不能打」
    (有向技能只有面朝侧的怪打得到)。魔法箭/近战是面朝向直线技能,
    拿对称区判「能不能打」会在「怪在背侧 + 转向被冷却挡住」时按出空技能。

    朝向未知/非法 → 原样返回整个 zone,退化成改动前行为(不制造挂死风险,
    见 spec §4.3)。y 范围任何分支下都不变——攻击区与接敌区必须严格同源。
    body_x 落在 zone 外(锚点外推/回退)时返回退化空矩形,不抛。
    """
    x0, y0, x1, y1 = zone
    if facing == 'RIGHT':
        return max(x0, body_x), y0, x1, y1
    if facing == 'LEFT':
        return x0, y0, min(x1, body_x), y1
    return zone


def point_in_zone(point, zone):
    """判断点是否在矩形区域内。边界点算在内。"""
    x, y = point
    x0, y0, x1, y1 = zone
    return x0 <= x <= x1 and y0 <= y <= y1


def mob_in_zone(mob_centers, zone):
    """怪物检测框中心落入攻击区即算可攻击。"""
    return any(point_in_zone(c, zone) for c in mob_centers)


def mob_present_debounced(raw_present, now, last_seen, grace):
    """区内有怪的去抖:真检测到 → True;检测不到但距上次见到还在 grace 内 → 仍按有怪。

    2026-08-07 逐拍日志(363 拍)实测:区内怪数为 0 的拍占 76%,进入"可攻击"状态
    28 次却中位只维持 1.07 秒、14 段不到 1 秒,攻击键被反复松开重按 31 次。
    法师一次施法约 1 秒,技能基本放不出来就被打断——这是"不攻击"的直接成因。
    YOLO 单帧 recall 0.886,且角色自己的攻击特效会遮挡目标(mob-3-3 训练时的已知
    难例),一拍漏检就退出攻击态是过度敏感。

    grace=0 → 退回旧的"一拍空立刻退出"行为。last_seen=None 表示从没见过怪。
    """
    if raw_present:
        return True
    if last_seen is None:
        return False
    return now - last_seen <= grace


def turn_allowed(now, last_turn_time, cooldown):
    """距上次转向是否够久。

    同一份日志实测:转向 17 次里 12 次是反向翻转(71%),序列 LLLLRLRLRLRLRLLRL,
    相邻反向间隔约 1.4-1.5 秒,比一次施法还短——角色在原地左右扭而打不出输出。
    冷却要长于一次施法才能打断这种交替。哨兵 0.0(从未转向)天然放行。
    """
    return now - last_turn_time >= cooldown


def anchor_expired(now, anchor_time, ttl):
    """锚点是否过期。从没拿到过锚点(None)同样算过期。"""
    return anchor_time is None or now - anchor_time > ttl


FORCED_RESCAN_MIN_INTERVAL = 0.5   # 强制慢扫自身限频:慢扫最坏 235ms,不许打满主循环


def should_rescan_anchor(now, last_scan, interval, force=False,
                         last_forced=0.0,
                         forced_min_interval=FORCED_RESCAN_MIN_INTERVAL):
    """是否应该重新扫描锚点。

    force=True 是丢锚事件通道(spec §3.5):击退/锚点超龄时绕过常规节流立刻扫,
    但距上次强制扫描必须 >= forced_min_interval——丢锚常由位置跳变引起,
    常规 2s 节流恰好卡在最需要慢扫的时刻(基线里慢扫只占 2.2%)。
    默认参数 = 旧行为,既有调用方不受影响。last_forced=0.0 哨兵(从未强制)天然放行。
    """
    if now - last_scan >= interval:
        return True
    return force and now - last_forced >= forced_min_interval


def anchor_vx_update(old_vx, dx, dt, dy,
                     max_age=2.0, max_speed=600.0, platform_dy=30.0):
    """低通学习名字牌实测水平速度(像素/秒):0.7*v + 0.3*旧值。

    三种情况不学,返回旧值:
    - dt 不在 (0, max_age] 内(相邻命中太久,位移可能含停/回退,速度不可信);
    - |dy| >= platform_dy(名字牌 y 突变 = 换平台,位移来自换层不是行走);
    - |v| > max_speed(回退/误检/窗口切换的跳变,不许污染外推速度)。
    """
    if not 0 < dt <= max_age:
        return old_vx
    if abs(dy) >= platform_dy:
        return old_vx
    v = dx / dt
    if abs(v) > max_speed:
        return old_vx
    return 0.7 * v + 0.3 * old_vx


def extrapolate_vx(learned_vx, seek_dir, cfg_speed):
    """外推速度(像素/秒):学习值与寻怪方向**同向**才用,反向/无学习值用配置速度×方向。

    击退方向几乎恒与寻怪方向相反(朝怪走、被怪打回来),学来的反向 vx 是击退残余,
    不是行走速度——直接外推会把 pred 往真人反方向推,1s 内逃出所有关联门
    (2026-08-10 19:56 日志铁证:cached 拍 x=2560 钳位而 寻怪=left)。
    学习点(anchor_vx_update)不动:残余会在下一次真实行走观测时被低通自然替换。
    """
    if seek_dir not in ('left', 'right'):
        return 0.0   # 契约外输入:不外推(调用点已保证非 None,这里防御)
    sign = 1.0 if seek_dir == 'right' else -1.0
    if learned_vx != 0.0 and learned_vx * sign > 0:
        return learned_vx
    return cfg_speed * sign


def should_pickup(now, last_pickup_time, interval, enabled):
    return enabled and now - last_pickup_time >= interval


def should_feed_pet(now, last_feed_time, interval, enabled):
    """喂宠物节流:开关开着且距上次喂药够久才喂(默认 15 分钟一次)。"""
    return enabled and now - last_feed_time >= interval


def parse_buff_config(text):
    """'magic_shield=q:180,armor=w' -> [('magic_shield', 'q', 180), ('armor', 'w', None)]
    每项格式 名称=按键[:间隔秒];间隔缺省为 None(永不自动补,只手动按);
    间隔非法(非数字)整条丢弃——配置打错字不该静默变成"手动键",用户会以为自动补生效了。"""
    result = []
    for entry in (text or '').split(','):
        entry = entry.strip()
        if '=' in entry:
            name, rest = entry.split('=', 1)
            key = rest
            interval = None
            if ':' in rest:
                key, _, iv = rest.partition(':')
                try:
                    interval = int(iv.strip())
                except ValueError:
                    continue  # 坏间隔:整条跳过,不保留为手动键
            if name.strip() and key.strip():
                result.append((name.strip(), key.strip(), interval))
    return result


def due_buffs(now, buffs, last_times):
    """buffs: parse_buff_config 输出 [(name, key, interval)];last_times: {name: 上次补的时间}
    返回需要补的 [(name, key)]:interval 非 None 且 now - last_times.get(name, 0) >= interval。"""
    return [(name, key) for name, key, interval in buffs
            if interval is not None and now - last_times.get(name, 0) >= interval]


def is_dead(hp_percent, threshold=0.02):
    return hp_percent < threshold


def knockback_detected(hp, prev_hp, hp_drop=0.02,
                       prev_x=None, new_x=None, mob_xs=None, x_jump=40.0):
    """受击(被怪打)检测:HP 下降超阈值,或锚点 x 突变且方向远离最近怪。

    HP 是主信号:被打必掉血,且 bars.read_hp 每拍都在读(10Hz),1-2 帧内就能捕获;
    2% 阈值滤掉血条按列填充的读数噪声(2560 宽下 1 列 ≈0.5%)。
    位移是辅助信号(锚点更新拍才有):|dx| > x_jump 且位移方向远离最近怪
    = 被击退(怪在左人被推右,或反之)。主动寻怪是朝怪走,方向相反,天然排除。
    prev_hp=None(第一拍/重新启用)不判,避免把初始值当掉血。
    """
    if prev_hp is not None and hp < prev_hp - hp_drop:
        return True
    if prev_x is None or new_x is None or not mob_xs:
        return False
    dx = new_x - prev_x
    if abs(dx) < x_jump:
        return False
    nearest = min(mob_xs, key=lambda x: abs(x - prev_x))
    return (nearest < prev_x and dx > 0) or (nearest > prev_x and dx < 0)


def knockback_debounced(raw_hit, now, last_hit, debounce):
    """受击防抖:一次真实掉血只算一次受击,防抖窗口内重复掉血读数不算。

    游戏受击后约 1 秒无敌,1 秒内不可能有新的真实掉血——但血条是渐变
    动画,一次掉 6.6% 会被 10Hz 读数拆成 0.7 秒内多拍 ≥2% 的下降,
    每拍都触发受击(2026-08-08 日志实测 0.2s 内连报 3 次受击)。
    每次受击都会作废朝向信念 + 重置转向冷却,重复触发让冷却形同虚设,
    怪穿过时角色左右扭 + 转向 tap 被硬直吞掉 → 打空。debounce 取
    游戏无敌时长(默认 1s)不会漏真受击:1s 内再掉血必是同一次掉血的
    渐变尾巴。last_hit=None 表示从未受击,天然放行。
    """
    if not raw_hit:
        return False
    if last_hit is None:
        return True
    return now - last_hit >= debounce


def walk_confirmed(seek_dir, body_x_start, body_x_now, min_dx):
    """走动确认:角色真的沿按键方向走了 min_dx 像素以上 → 它必定面朝那边。

    这是给朝向模板采集用的**位移观测**,不是信念。用 `_facing` 去标定模板等于
    循环论证——模板正是用来检验 `_facing` 的(见 spec §3.3)。

    反向位移(按右键却往左动)一律不确认:那是撞墙、被击退、或锚点跳变,
    据此标定会把模板朝向记反,后面所有观测全错。
    seek_dir 为 None(没在寻怪)或 body_x_start 为 None(没记上起点)→ 不确认。
    """
    if seek_dir not in ('left', 'right') or body_x_start is None:
        return False
    dx = body_x_now - body_x_start
    return dx >= min_dx if seek_dir == 'right' else -dx >= min_dx


def stun_suppressed(now, last_hit, suppress_duration):
    """硬直抑制:受击后 suppress_duration 秒内不转向、不攻击。

    击退硬直动画约 0.3-0.5 秒,期间方向键 tap 会被游戏吞掉(2026-08-08
    日志实测:受击 44,465 后 0.3s 的转向 tap、45,207 后 0.5s 的转向 tap
    均未生效)。但转向代码按完键后照常盲写 _facing——键没生效、信念却
    已翻转,攻击区随后按错朝向算,怪在区内却朝反方向打空,直到下次受击
    才作废重来。抑制窗 = 硬直期间根本不按转向/攻击键,从源头掐掉
    「键被吞、信念照写」的分叉(受击防抖只解决了"重复作废",没解决
    "作废后立即补转的 tap 落在硬直里")。

    suppress_duration <= 0 → 关掉抑制,恒放行。last_hit == 0.0 哨兵
    (从未受击)→ 放行。窗口边界 now - last_hit >= suppress_duration
    不算抑制(取"至少经过这么久")。
    """
    if suppress_duration <= 0:
        return False
    if last_hit == 0.0:
        return False
    return now - last_hit < suppress_duration


def mob_feet(mob):
    """怪物脚底点 = bbox 底部中心。横版地面距离以脚底为准,不用框中心。"""
    return mob.x + mob.width / 2, mob.y + mob.height


def warrior_attack_zone(body_center, facing, attack_distance, zone_height):
    """战士近战攻击区 = 身体中心向 facing 侧的半矩形 (x, y, w, h)。
    朝左 → [cx-距离, cx];朝右 → [cx, cx+距离];未知朝向按右。"""
    cx, cy = body_center
    top = cy - zone_height / 2
    if facing == 'LEFT':
        return cx - attack_distance, top, attack_distance, zone_height
    return cx, top, attack_distance, zone_height


def mob_feet_in_zone(mob, zone):
    """怪脚底落入攻击区矩形 → 可攻击。边界像素算命中。
    (战士/近战专用:与站桩的 mob_in_zone(中心点判定) 分开,见合并说明)"""
    x, y, w, h = zone
    fx, fy = mob_feet(mob)
    return x <= fx <= x + w and y <= fy <= y + h


def facing_update(facing, move_direction):
    """移动方向 → 朝向。无历史(或未知方向)默认 RIGHT。"""
    if move_direction == 'left':
        return 'LEFT'
    if move_direction == 'right':
        return 'RIGHT'
    return facing if facing in ('LEFT', 'RIGHT') else 'RIGHT'


def patrol_direction(player_ratio, left_bound, right_bound):
    """单屏折返:比例 < 左界 → 向右走;> 右界 → 向左走;中间(含压界) → 保持(None)。"""
    if player_ratio < left_bound:
        return 'right'
    if player_ratio > right_bound:
        return 'left'
    return None


def should_approach(body_center, mob_feet_xy, attack_distance):
    """怪脚底与身体中心水平距离 > 攻击距离 → 需朝怪接近。"""
    cx, _ = body_center
    fx, _ = mob_feet_xy
    return abs(fx - cx) > attack_distance


def walk_order(facing):
    """防挂机走位两段方向顺序,返回 (first, second, resulting_facing)。

    朝向已知(LEFT/RIGHT):先向反方向走出、再朝原方向走回 → 结束时朝向不变,
    走位不会把角色的面朝方向翻反(修复 2026-08-06 实测的"走位后朝向随机"问题);
    朝向未知(None,首次走位前):随机一侧走出、反方向走回,
    resulting_facing = 走完后面朝的方向(第二段方向),由调用方采纳为基线。
    方向用 'left'/'right' 小写,与 facing_update 一致。
    """
    if facing in ('LEFT', 'RIGHT'):
        first = 'left' if facing == 'RIGHT' else 'right'
    else:
        first = random.choice(('left', 'right'))
    second = 'right' if first == 'left' else 'left'
    return first, second, ('LEFT' if second == 'left' else 'RIGHT')


def nearest_mob_x(centres, zone, body_x):
    """攻击区内离身体中心水平距离最近的怪中心 x;无怪在区内返回 None。"""
    in_zone = [x for x, y in centres if point_in_zone((x, y), zone)]
    if not in_zone:
        return None
    return min(in_zone, key=lambda x: abs(x - body_x))


def turn_direction(facing, body_x, mob_x):
    """打怪前需要的转向:怪在面朝反侧(或朝向未知)时,返回要按的方向键
    'left'/'right';已经面朝怪所在侧 → 返回 None。mob_x 为最近怪的中心 x。

    注意:站桩打怪请用 attack_turn_direction,它带目标侧锁定。本函数按单个
    目标判边,每拍换目标就会换边(见 attack_turn_direction 的实测数据)。
    """
    side = 'left' if mob_x < body_x else 'right'
    need = 'LEFT' if side == 'left' else 'RIGHT'
    return side if facing != need else None


def _on_side(x, body_x, side):
    """怪是否算在指定侧。正压在身上(x == body_x)时两侧都算:
    这种怪的左右判定纯是噪声,不该让角色翻来翻去。"""
    if x == body_x:
        return True
    return x < body_x if side == 'left' else x > body_x


def attack_turn_direction(facing, body_x, centres, zone):
    """站桩打怪时该往哪边转:面朝侧攻击区内还有怪 → None(不转,继续打)。

    取代"每拍 nearest_mob_x 重选最近怪再 turn_direction 判边"的旧规则。
    旧规则下区内左右都有怪时,最近的那只一换边就转向一次:219 帧真实录制帧
    重放实测,相邻采样的最近怪换边率 38%,角色把时间花在左右转向上打不出输出。
    且换边率与攻击区宽无关(1200→800 实测 39%→38%),缩小攻击区治不了——
    翻转来自选目标的规则本身。

    锁定规则:面朝侧还有目标就不动,只有那一侧真空了才换边。
    朝向未知(首次接战)仍按最近怪定向。
    """
    in_zone = [x for x, y in centres if point_in_zone((x, y), zone)]
    if not in_zone:
        return None
    if facing in ('LEFT', 'RIGHT'):
        keep = 'left' if facing == 'LEFT' else 'right'
        if any(_on_side(x, body_x, keep) for x in in_zone):
            return None
        other = 'right' if keep == 'left' else 'left'
        return other if any(_on_side(x, body_x, other) for x in in_zone) else None
    nearest = min(in_zone, key=lambda x: abs(x - body_x))
    return 'left' if nearest < body_x else 'right'


def nearest_mob_side(centres, zone, body_x):
    """接敌区内离身体最近的怪 (x, side);区内无怪 → (None, None)。

    攻击区方向依据(2026-08-08):有向攻击区不再读盲写的 _facing 信念——
    信念被击退/按键丢失破坏后与实际朝向脱节,攻击区画错侧 → 怪不在区内 →
    不攻击 → 也没有修正机会,死锁。改为按"区内最近怪在哪侧"画半区(观测事实),
    怪必然落进攻击区;攻击前的方向键轻点再物理修正真实朝向。
    x == body_x(怪压身上)→ 'right',避免贴脸判边噪声换边。
    """
    in_zone = [x for x, y in centres if point_in_zone((x, y), zone)]
    if not in_zone:
        return None, None
    nearest = min(in_zone, key=lambda x: abs(x - body_x))
    return nearest, ('right' if nearest >= body_x else 'left')


def attack_pre_tap_direction(centres, zone, body_x):
    """攻击前垫步方向:接敌区内最近怪在左 → 'left',在右 → 'right';无怪 → None。

    用途(「攻击前垫步」可选开关):战士的 _facing 是盲写信念,被击退/按键丢失
    破坏后与实际朝向脱节——攻击区内有怪(attack_turn_direction 判定"面朝侧还有
    目标"返回 None)时,角色会背对怪一直按攻击键砍空气,且没有修正机会。
    垫步不信任信念:每次攻击前按最近怪所在侧的方向键轻点,信念错则物理修正,
    信念对则该轻点是 no-op(已朝该侧按方向键零代价,50ms 位移可忽略)。
    复用 nearest_mob_side 的判边规则(x == body_x 压身上的怪归右,避免贴脸噪声)。
    """
    _, side = nearest_mob_side(centres, zone, body_x)
    return side


def same_floor(mob_feet_y, player_feet_y, tolerance):
    """怪脚底与角色脚底(名字牌 y)高度差在容差内 → 同一层,水平走近可达。
    容差小于平台间高度差,避免追到别的平台。"""
    return abs(mob_feet_y - player_feet_y) <= tolerance


def seek_direction(mob_entries, body_x, player_feet_y, tolerance, current_dir=None):
    """自动寻怪要按的方向:同层怪中离身体水平距离最近的一个,
    在左 → 'left',在右 → 'right';没有同层怪 → None。
    mob_entries: [(中心x, 脚底y), ...] 全部怪。调用方保证当前攻击区内无怪
    (区内的早已被攻击分支原地处理,本函数只服务"区外寻怪")。

    current_dir = 上一拍的寻怪方向时带方向锁定:那一侧还有同层怪就继续追,
    不因为对侧刷出更近的怪而掉头。寻怪刷新间隔可低至 0.1s,没有锁定时
    追怪途中会被对侧目标反复拽回来,原地左右横跳且全程不攻击
    (219 帧重放实测该分支方向翻转 8/28)。None = 未在寻怪,按最近怪定向。
    """
    same_floor_xs = [cx for cx, fy in mob_entries if same_floor(fy, player_feet_y, tolerance)]
    if not same_floor_xs:
        return None
    if current_dir in ('left', 'right') and any(
            _on_side(cx, body_x, current_dir) for cx in same_floor_xs):
        return current_dir
    nearest = min(same_floor_xs, key=lambda cx: abs(cx - body_x))
    return 'left' if nearest < body_x else 'right'


def seek_persist(seek_raw, prev_seek, now, last_seen, grace):
    """寻怪去抖:同层怪这一拍没检出,但距上次检出还在 grace 内 → 继续按上一拍方向走。

    攻击侧早有 丢怪保持(mob_present_debounced),寻怪侧一直没有:2026-08-08 实测
    344 段寻怪只有 40.4% 撑过 0.5 秒,其中 105 段(30.5%)起步与取消发生在同一拍
    (持续中位 0.00s)——游戏里看就是原地抽搐。怪会跳、YOLO 框高每拍都在抖,
    一拍判失就 send_key_up,角色根本走不出去(spec §2.2 / §3.3)。

    grace <= 0 → 关掉去抖,退回「一拍判失立刻停」的旧行为。
    prev_seek=None(上一拍没在追)或 last_seen=None(从没检出过同层怪)→ 不保持。
    """
    if seek_raw is not None:
        return seek_raw
    if grace <= 0 or prev_seek is None or last_seen is None:
        return None
    return prev_seek if now - last_seen <= grace else None


PLAYER_GATE_HALF_W = 240   # YOLO 关联门半宽:与快通道搜索窗同宽(FAST_HALF_W,跨模块注释同步)
PLAYER_GATE_HALF_H = 120   # 关联门半高:比快窗的 80 放宽——击退/跳跃纵向位移大,
                           # 快窗为 OCR 成本收窄的理由对免费的 YOLO 不成立(spec §3.3)
PLAYER_BOX_TO_NAMETAG = 64  # player 框中心 → 名字牌中心的纵向距离(向下为正)。
                            # 2026-08-09 实测:403 组「相邻拍 + 角色几乎没动」的
                            # yolo↔名字牌配对,中位 64px(p10 61 / p90 67)。
                            # 与「名字牌到身体偏移(像素)」(88)是两个量——那个是
                            # 名字牌到攻击落点(肩/手高度)的标定值,这个是框中心到
                            # 名字牌的实测几何。混用会给关联门带来 64px 系统偏置。


TEMPLATE_MAX_DY = 45   # 模板分片命中允许的最大纵向位移(px),超了当误匹配丢弃。
                       # 真实纵向步长(只取 OCR 验名过的相邻拍,n=2164):p50=2 /
                       # p99=26 / p99.9=34,>40px 的只有 1 拍(0.05%)。


def template_hit_plausible(hit_y, prev_y, max_dy=TEMPLATE_MAX_DY):
    """模板分片命中的纵向合理性判据(spec §3.8)—— 挡住棘轮漂移。

    模板通道把自己上一拍的输出当作下一拍的搜索中心,却既不验名(命中的
    AnchorHit.text 是空串),也没有任何合理性判据 —— 一次误匹配就会自我强化:
    匹配落在搜索窗**顶边**时,回推的锚点 y = (cy - half_h) + 0 + 模板高/2,
    即每拍恒定上移 `half_h - th/2` = 80 - 36/2 = **62px**。2026-08-09 日志逐拍
    实测正是 -62、-62、-62……一路飘到 y=19(屏幕顶)再也回不来;全天 11.6%
    的拍锚点飘在平台上方 >80px,其中 90% 由 template 持有。

    45px 的帽子挡得住 62px 的棘轮,又几乎不误伤(0.05%)。真换平台时纵向位移
    更大,那一拍让给验名的 OCR 通道去重建 —— 弱证据不该有重定义 y 的权力。
    prev_y=None(冷启动/刚复位)没有先验,不许凭空拒绝。
    """
    return prev_y is None or abs(hit_y - prev_y) <= max_dy


PLAYER_GATE_BASE_W = 110    # 位移门基础半宽:击退/起跳的瞬时冲量 + 框中心观测噪声。
                            # 实测 dt<0.15s 的关联距 max=174,p99=93 —— 110 覆盖冲量
PLAYER_GATE_BASE_H = 70     # 基础半高:相邻拍 |Δanchor_y| 实测 p50=2 / p99=62 / max=66
PLAYER_GATE_SPEED_X = 300.0  # 横向极速(px/s):关联距 p99 对 dt 线性拟合斜率 ~260,取整放宽
PLAYER_GATE_SPEED_Y = 200.0  # 纵向极速(px/s):跳跃/坠落纵向位移比走路快,但受平台层高约束


def player_gate_size(dt, half_w=PLAYER_GATE_HALF_W, half_h=PLAYER_GATE_HALF_H):
    """按「距上次锚点观测过了多久」缩放关联门 —— 位移合理性判据(spec §3.3)。

    固定 ±240/±120 的门对相邻拍宽得离谱:0.2s 里角色最多走 60px,门却容得下
    240px 外的路人。自己那拍没被检出时(YOLO 单帧漏检、被特效盖住),路人就是
    门内唯一候选,`len(gated)==1` 直接无条件接受 → 绿框跳到别人身上。
    改成 base + 极速 × dt:相邻拍收到 ~170px,久未观测再放回固定上限。

    上限保留是必须的:dt 大到几秒时角色可能已经跑到任何地方,门再放大就等于
    "谁都能认成自己",那时该交给慢扫验名(§3.7),不是靠更宽的门去猜。
    dt=None(从未观测)/负值(时钟异常)→ 退回固定上限,绝不给出比基础值更小的门。
    """
    if dt is None or dt < 0:
        return half_w, half_h
    return (min(half_w, PLAYER_GATE_BASE_W + PLAYER_GATE_SPEED_X * dt),
            min(half_h, PLAYER_GATE_BASE_H + PLAYER_GATE_SPEED_Y * dt))


def player_box_anchor(box, box_to_nametag=PLAYER_BOX_TO_NAMETAG):
    """player 框 → **名字牌坐标系**下的位置 (x, y)——跨坐标系换算的唯一事实源。

    关联门的 pred 来自 self._anchor,存的一直是名字牌位置;YOLO 框中心却在身体上,
    实测比名字牌高 PLAYER_BOX_TO_NAMETAG。不换算直接比,±half_h 的门会整体上移
    64px:2026-08-09 实测 ±120 变成「上 56px / 下 184px」,自己一跳就出门(丢锚),
    下一层平台的路人反而稳稳在门内、成为唯一候选被无条件接受(认错人)。
    伪锚点也走这里换算,yolo 拍与名字牌拍才落在同一个 y 上(否则差 88-64=24px,
    攻击区随来源翻拍上下抖)。"""
    return box.x + box.width / 2, box.y + box.height / 2 + box_to_nametag


def gate_player_boxes(players, pred, half_w=PLAYER_GATE_HALF_W,
                      half_h=PLAYER_GATE_HALF_H):
    """框中心(换算到名字牌坐标系后)落在 pred 的 ±half_w/±half_h 门内的候选。

    门口径唯一事实源:select_player_box 的裁决与决策日志的 yolo候选= 都从这里拿,
    两处各写一遍迟早分叉。边界压线算门内,与 point_in_zone 口径一致。
    pred 是名字牌坐标,候选先经 player_box_anchor 换算再比(见该函数)。"""
    px, py = pred
    out = []
    for b in players:
        bx, by = player_box_anchor(b)
        if abs(bx - px) <= half_w and abs(by - py) <= half_h:
            out.append(b)
    return out


def select_player_box(players, pred, identity_fresh,
                      half_w=PLAYER_GATE_HALF_W, half_h=PLAYER_GATE_HALF_H):
    """YOLO player 框 → 「哪个是我」的关联裁决(spec §3.3)。

    YOLO 只学「什么是玩家」,身份判别在这里:pred 是外推位置(与快窗 OCR 同一个
    搜索中心),门内候选由 gate_player_boxes 给出。
    - 恰 1 个 → 接受(不看身份新鲜度:门内只有一个玩家,几乎必是自己);
    - 多个 → identity_fresh(距上次名字牌真实命中还在保鲜窗内)才取合位移最近的,
      否则返回 None——路人贴身且身份过期,宁可退到慢扫/cached,不认错人;
    - 0 个 → None,落到阶梯下一级。
    最近取欧氏距离平方:两候选横向同距但隔层时,必须选同层那个(横向距离分不开)。
    距离同样在名字牌坐标系里量(player_box_anchor 换算),否则纵向项整体偏 64px,
    "隔层那个更近"的判据会失真。
    传入已过门的列表也正确(门是幂等的,Task 7 先 gate 后 select 不改语义)。
    """
    gated = gate_player_boxes(players, pred, half_w, half_h)
    if not gated:
        return None
    if len(gated) == 1:
        return gated[0]
    if not identity_fresh:
        return None
    px, py = pred

    def _d2(b):
        bx, by = player_box_anchor(b)
        return (bx - px) ** 2 + (by - py) ** 2

    return min(gated, key=_d2)


LOST_UNIQUE_MIN_AGE = 1.0   # 丢锚超此时长(秒)才允许唯一框接管:新鲜丢失先走常规门
LOST_UNIQUE_GATE_Y = 300    # 唯一框纵向门(px):实测层高差 240-300,换层接得住、隔层挡得住


def select_lost_unique_box(players, pred_y, anchor_age,
                           min_age=LOST_UNIQUE_MIN_AGE, gate_y=LOST_UNIQUE_GATE_Y):
    """丢锚末级安全网(spec 2026-08-10 §3.4):常规门裁决失败后,
    丢锚超 min_age 且全屏**恰好 1 个** player 框且同层 → 直接接管。

    唯一性就是身份判据(单人挂机全屏 1 框几乎恒是自己,与 select_player_box
    「门内恰 1 个不看身份」同理,范围扩到全屏)。横向不看门:pred 已逃逸,
    横向先验已死;纵向先验仍活(外推只推 x),±gate_y 挡住隔层路人。
    多框拒裁:多人图宁可慢扫不认错。认错上界 = 名字牌下次可读 + 复验间隔,
    身份时间戳不由本通道刷新(yolo 级既有纪律)。
    """
    if anchor_age is None or anchor_age < min_age or len(players) != 1:
        return None
    _, by = player_box_anchor(players[0])
    if abs(by - pred_y) > gate_y:
        return None
    return players[0]


def crowd_present(mob_count, threshold):
    """接敌区内怪数达到阈值 → 该用群攻(前后双向命中,不需要朝向)。

    计数用**原始**区内怪数,不做去抖:YOLO 单帧 recall 0.886,4 只可能读成 3 只,
    但那只会晚一个检测拍放群攻;反过来加保持窗会在怪清光后仍按旧计数
    多放一发空群攻,浪费的是蓝。与 丢怪保持/寻怪保持 取舍方向不同,是因为那两处
    的失败代价是「停手/停步」,这里只是「晚一拍」(spec §3.10)。

    threshold <= 0 视为功能关闭,恒 False —— 否则 0 只怪 >= 0 会恒真,
    没绑群攻键时每拍都判成「该群攻」。边界取 >=(等于阈值算命中),与
    should_attack / turn_allowed 同口径。
    """
    return threshold > 0 and mob_count >= threshold
