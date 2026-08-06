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
