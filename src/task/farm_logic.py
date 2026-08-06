"""打怪决策纯逻辑。不依赖游戏/框架,全部可离线单测。"""


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


def potions_exhausted(hp, hp_threshold, hp_count, mp, mp_threshold, mp_count):
    """count 为 None 表示 OCR 未读出(未知),不判耗尽。"""
    if hp_count == 0 and need_hp_potion(hp, hp_threshold):
        return 'hp'
    if mp_count == 0 and need_mp_potion(mp, mp_threshold):
        return 'mp'
    return None


def should_attack(now, last_attack_time, interval):
    return now - last_attack_time >= interval


def should_pickup(now, last_pickup_time, interval, enabled):
    return enabled and now - last_pickup_time >= interval


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


def mob_in_zone(mob, zone):
    """怪脚底落入攻击区矩形 → 可攻击。边界像素算命中。"""
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
