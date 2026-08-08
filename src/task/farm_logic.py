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


def should_rescan_anchor(now, last_scan, interval):
    """是否应该重新扫描锚点。"""
    return now - last_scan >= interval


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


def should_pickup(now, last_pickup_time, interval, enabled):
    return enabled and now - last_pickup_time >= interval


def should_feed_pet(now, last_feed_time, interval, enabled):
    """喂宠物节流:开关开着且距上次喂药够久才喂(默认 15 分钟一次)。"""
    return enabled and now - last_feed_time >= interval


def parse_buff_config(text):
    """'magic_shield=q,armor=w' -> [('magic_shield','q'),('armor','w')]"""
    result = []
    for entry in (text or '').split(','):
        entry = entry.strip()
        if '=' in entry:
            name, key = entry.split('=', 1)
            if name.strip() and key.strip():
                result.append((name.strip(), key.strip()))
    return result


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
