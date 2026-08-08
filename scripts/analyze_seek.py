# -*- coding: utf-8 -*-
"""寻敌起步延迟判据 A/B/C/D/E(2026-08-08-seek-latency-design.md §5)。

判据在 spec 里事先写死,本脚本只是把它算出来,不许在这里改通过线。

判据只依赖 可打= 与 寻怪= 两个字段:有怪= 的门控作用在本次改动中被改掉了
(spec §3.2),拿它当尺子会在改动前后失真。同层脚= / 同层心= 是 Task 1 加的
观测字段,老日志没有,解析时可缺省(判据 A-E 都不用它们)。

用法:
    python scripts/analyze_seek.py [日志路径] [--since HH:MM:SS] [--until HH:MM:SS]
默认日志路径 logs/ok-script.log。基线快照见 spec §2。
"""
import re
import sys
from datetime import datetime

DEFAULT_LOG = 'logs/ok-script.log'

DEC = re.compile(
    r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) .*?'
    r'决策 src=\S+ body_x=\S+ anchor_y=\S+ 怪=(\d+) 区内=\d+\(\S+\) '
    r'(?:同层脚=(\d+) 同层心=(\d+) 近怪dx=\S+ dy脚=\S+ dy心=\S+ )?'
    r'实测有怪=\w+ 有怪=\w+ 可打区内=\d+ 可打=(\w+) '
    r'朝向=\S+→\S+ 转向=\S+ 寻怪=(\S+) ')


def parse(lines):
    """决策行 → 判据要用的字段。不认识的行直接跳过。"""
    rows = []
    for line in lines:
        m = DEC.match(line)
        if not m:
            continue
        ts, mobs, same_feet, same_center, can_atk, seek = m.groups()
        rows.append(dict(
            t=datetime.strptime(ts, '%Y-%m-%d %H:%M:%S,%f').timestamp(),
            mobs=int(mobs),
            same_feet=None if same_feet is None else int(same_feet),
            same_center=None if same_center is None else int(same_center),
            can_atk=can_atk == 'True',
            seek=seek))
    return rows


def sessionize(rows, gap=10.0, min_rows=20):
    """按大间隔切段:停任务/重启会在日志里留下长空档,跨段算时长没有意义。"""
    if not rows:
        return []
    out, cur = [], [rows[0]]
    for a, b in zip(rows, rows[1:]):
        if b['t'] - a['t'] > gap:
            out.append(cur)
            cur = []
        cur.append(b)
    out.append(cur)
    return [s for s in out if len(s) >= min_rows]


def _quantile(xs, q):
    if not xs:
        return float('nan')
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def _waits(sessions):
    """判据 A:从「可打=False 且 怪>0 且 寻怪=-」的第一拍,到「寻怪≠-」那一拍。

    可打=True 会把等待清零(在打就不该追);屏幕上没怪的拍不起算(不追是对的)。
    """
    out = []
    for s in sessions:
        start = None
        for r in s:
            if r['can_atk']:
                start = None
            elif r['seek'] != '-':
                if start is not None:
                    out.append(r['t'] - start)
                start = None
            elif r['mobs'] > 0 and start is None:
                start = r['t']
    return out


def _seek_segments(sessions):
    """判据 B:每一段连续「寻怪≠-」的时长(段内首末拍的时间差)。"""
    out = []
    for s in sessions:
        start, prev = None, None
        for r in s:
            if r['seek'] != '-' and start is None:
                start = r['t']
            elif r['seek'] == '-' and start is not None:
                out.append(prev['t'] - start)
                start = None
            prev = r
        if start is not None:
            out.append(prev['t'] - start)
    return out


def _idle_runs(sessions):
    """判据 C:每一段连续「可打=False 且 寻怪=- 且 怪>0」的时长。"""
    out = []
    for s in sessions:
        start, prev = None, None
        for r in s:
            idle = (not r['can_atk']) and r['seek'] == '-' and r['mobs'] > 0
            if idle and start is None:
                start = r['t']
            elif not idle and start is not None:
                out.append(prev['t'] - start)
                start = None
            prev = r
        if start is not None:
            out.append(prev['t'] - start)
    return [x for x in out if x > 0]


def metrics(sessions):
    rows = [r for s in sessions for r in s]
    span = sum(s[-1]['t'] - s[0]['t'] for s in sessions)
    waits = _waits(sessions)
    segs = _seek_segments(sessions)
    idle = _idle_runs(sessions)
    gaps = [b['t'] - a['t'] for s in sessions for a, b in zip(s, s[1:])]
    return dict(
        ticks=len(rows), span=span, sessions=len(sessions),
        A_n=len(waits), A_median=_quantile(waits, .5), A_p90=_quantile(waits, .9),
        B_n=len(segs), B_ratio=(sum(1 for x in segs if x >= 0.5) / len(segs)
                                if segs else float('nan')),
        C_n=len(idle), C_ratio=(sum(idle) / span if span else float('nan')),
        D_ratio=(sum(1 for r in rows if r['can_atk']) / len(rows)
                 if rows else float('nan')),
        E_median=_quantile(gaps, .5), E_p90=_quantile(gaps, .9),
        E_max=max(gaps) if gaps else float('nan'))


def main(argv):
    path = DEFAULT_LOG
    since = until = None
    args = list(argv)
    for flag, setter in (('--since', 'since'), ('--until', 'until')):
        if flag in args:
            i = args.index(flag)
            value = args[i + 1]
            if setter == 'since':
                since = value
            else:
                until = value
            del args[i:i + 2]
    if args:
        path = args[0]
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = list(f)
    if since or until:
        lines = [ln for ln in lines
                 if (not since or ln[11:19] >= since)
                 and (not until or ln[11:19] <= until)]
    m = metrics(sessionize(parse(lines)))
    print(f'{path}: {m["ticks"]} 拍 / {m["span"]:.0f}s / {m["sessions"]} 段')
    print(f'A 停手→起步寻怪  中位 {m["A_median"]:.2f}s  p90 {m["A_p90"]:.2f}s  '
          f'(n={m["A_n"]})   通过线: 中位<=0.50 且 p90<=1.50')
    print(f'B 寻怪段撑过0.5s {m["B_ratio"]:.1%}  (n={m["B_n"]})'
          f'                通过线: >=65%')
    print(f'C 连续空转累计   {m["C_ratio"]:.1%}  (n={m["C_n"]})'
          f'                通过线: <=12%')
    print(f'D 可打拍占比     {m["D_ratio"]:.1%}'
          f'                          通过线: >=41.0%')
    print(f'E 拍间隔 中位 {m["E_median"]:.3f}s  p90 {m["E_p90"]:.3f}s  '
          f'max {m["E_max"]:.3f}s   通过线: p90<=0.60 且 max<=5.0')


if __name__ == '__main__':
    main(sys.argv[1:])
