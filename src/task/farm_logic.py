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


def point_in_zone(point, zone):
    """判断点是否在矩形区域内。边界点算在内。"""
    x, y = point
    x0, y0, x1, y1 = zone
    return x0 <= x <= x1 and y0 <= y <= y1


def mob_in_zone(mob_centers, zone):
    """怪物检测框中心落入攻击区即算可攻击。"""
    return any(point_in_zone(c, zone) for c in mob_centers)


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
    'left'/'right';已经面朝怪所在侧 → 返回 None。mob_x 为最近怪的中心 x。"""
    side = 'left' if mob_x < body_x else 'right'
    need = 'LEFT' if side == 'left' else 'RIGHT'
    return side if facing != need else None


def same_floor(mob_feet_y, player_feet_y, tolerance):
    """怪脚底与角色脚底(名字牌 y)高度差在容差内 → 同一层,水平走近可达。
    容差小于平台间高度差,避免追到别的平台。"""
    return abs(mob_feet_y - player_feet_y) <= tolerance


def seek_direction(mob_entries, body_x, player_feet_y, tolerance):
    """自动寻怪要按的方向:同层怪中离身体水平距离最近的一个,
    在左 → 'left',在右 → 'right';没有同层怪 → None。
    mob_entries: [(中心x, 脚底y), ...] 全部怪。调用方保证当前攻击区内无怪
    (区内的早已被攻击分支原地处理,本函数只服务"区外寻怪")。"""
    same_floor_xs = [cx for cx, fy in mob_entries if same_floor(fy, player_feet_y, tolerance)]
    if not same_floor_xs:
        return None
    nearest = min(same_floor_xs, key=lambda cx: abs(cx - body_x))
    return 'left' if nearest < body_x else 'right'
