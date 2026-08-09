# -*- coding: utf-8 -*-
"""丢锚判据 A/B/C/D/E(2026-08-09-player-anchor-yolo-fusion-design.md §5)。

判据在 spec 里事先写死,本脚本只把它算出来,不许在这里改通过线。
只依赖 决策 src= 与 可打= 两个字段:改动前后语义不变(src 只是多一个新值
yolo;丢锚定义 = src ∈ {cached, fallback} 不变),可直接对比新旧日志。

用法:
    python scripts/analyze_anchor.py [日志路径] [--since HH:MM:SS] [--until HH:MM:SS]
默认日志路径 logs/ok-script.log。基线快照(08-08 全天)见 spec §1.2。
"""
import re
import sys
from datetime import datetime

DEFAULT_LOG = 'logs/ok-script.log'
LOST = ('cached', 'fallback')

DEC = re.compile(
    r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) .*?'
    r'决策 src=(\S+) body_x=\S+ anchor_y=\S+ 怪=\d+ .*?可打=(\w+) ')


def parse(lines):
    """决策行 → dict(t, src, can_atk)。不认识的行直接跳过。"""
    rows = []
    for line in lines:
        m = DEC.match(line)
        if not m:
            continue
        ts, src, can_atk = m.groups()
        rows.append(dict(
            t=datetime.strptime(ts, '%Y-%m-%d %H:%M:%S,%f').timestamp(),
            src=src, can_atk=can_atk == 'True'))
    return rows


def sessionize(rows, gap=10.0, min_rows=20):
    """按大间隔切段:停任务/重启的长空档跨段算时长没有意义(同 analyze_seek)。"""
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


def loss_episodes(sessions):
    """连续 src∈LOST 段的时长:首个丢锚拍 → 恢复拍(首个非丢锚拍)。

    段尾仍在丢(没等到恢复拍)→ 时长未知,不计——与基线统计口径一致,
    宁可少算也不编造。
    """
    out = []
    for s in sessions:
        start = None
        for r in s:
            lost = r['src'] in LOST
            if lost and start is None:
                start = r['t']
            elif not lost and start is not None:
                out.append(r['t'] - start)
                start = None
    return [x for x in out if x > 0]


def _quantile(xs, q):
    if not xs:
        return float('nan')
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def metrics(sessions):
    rows = [r for s in sessions for r in s]
    span = sum(s[-1]['t'] - s[0]['t'] for s in sessions)
    eps = loss_episodes(sessions)
    gaps = [b['t'] - a['t'] for s in sessions for a, b in zip(s, s[1:])]
    by_src = {}
    for r in rows:
        by_src[r['src']] = by_src.get(r['src'], 0) + 1
    return dict(
        ticks=len(rows), span=span, sessions=len(sessions), by_src=by_src,
        A_lost_ratio=(sum(1 for r in rows if r['src'] in LOST) / len(rows)
                      if rows else float('nan')),
        B_n=len(eps), B_median=_quantile(eps, .5), B_p90=_quantile(eps, .9),
        C_per_hour=(sum(1 for x in eps if x >= 3.0) / (span / 3600)
                    if span else float('nan')),
        D_ratio=(sum(1 for r in rows if r['can_atk']) / len(rows)
                 if rows else float('nan')),
        E_median=_quantile(gaps, .5), E_p90=_quantile(gaps, .9))


def main(argv):
    path = DEFAULT_LOG
    since = until = None
    args = list(argv)
    for flag in ('--since', '--until'):
        if flag in args:
            i = args.index(flag)
            if flag == '--since':
                since = args[i + 1]
            else:
                until = args[i + 1]
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
    print('src 分布: ' + '  '.join(
        f'{k}={v}({v / m["ticks"]:.1%})' for k, v in
        sorted(m['by_src'].items(), key=lambda kv: -kv[1])))
    print(f'A 丢锚拍占比     {m["A_lost_ratio"]:.1%}'
          f'                          通过线: <=10%')
    print(f'B 丢锚段 p90     {m["B_p90"]:.2f}s  中位 {m["B_median"]:.2f}s'
          f'  (n={m["B_n"]})      通过线: p90<=1.0')
    print(f'C >=3s 段频次    {m["C_per_hour"]:.1f} 段/小时'
          f'                    通过线: <=6')
    print(f'D 可打拍占比     {m["D_ratio"]:.1%}'
          f'                          通过线: >=41.0%')
    print(f'E 拍间隔 中位 {m["E_median"]:.3f}s  p90 {m["E_p90"]:.3f}s'
          f'      通过线: 不高于基线(0.704/0.946)')


if __name__ == '__main__':
    main(sys.argv[1:])
