# -*- coding: utf-8 -*-
"""转向后攻击区跟上的延迟 —— 修复前后的同一把尺子。

攻击区是按本拍转向**之前**的朝向算的(MapleFarmTask.py:583,spec §5.1),
新朝向要下一拍才生效。所以这里量的不是"攻击区算错了",而是
"下一拍隔了多久才来"。判据与语义写死在 plans/2026-08-09-turn-zone-latency.md,
不许在本脚本里改。

用法: python scripts/analyze_turn.py [日志文件]
      默认 logs/ok-script.log(当天);日志按天轮转,查昨天要显式传文件名。
输出标签一律 ASCII:控制台是 cp936,中文会乱码。
"""
import re
import sys

LOG = 'logs/ok-script.log'
MAX_LOOKAHEAD = 40   # 40 拍还没结算就当没结算,避免一次异常拖垮整个分布

TS = re.compile(r'^\d{4}-\d\d-\d\d (\d\d):(\d\d):(\d\d),(\d{3})')
DEC = re.compile(r'决策 src=(\S+) .*?朝向=(\S+)→(\S+) 转向=(\S+) 寻怪=(\S+) '
                 r'可发键=(\w+) 实测=(\S+) 分值=')


def _seconds(m):
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60
            + int(m.group(3)) + int(m.group(4)) / 1000)


def parse(lines):
    """行 → 决策拍列表 [{t, src, f0, f1, turn}]。非决策行直接跳过。"""
    rows = []
    for line in lines:
        ts, dec = TS.match(line), DEC.search(line)
        if ts and dec:
            rows.append(dict(t=_seconds(ts), src=dec.group(1),
                             f0=dec.group(2), f1=dec.group(3), turn=dec.group(4)))
    return rows


def scan(lines):
    """算统计。语义见计划文档 Task 1,四种结局互斥且必然命中其一。"""
    rows = parse(lines)
    out = dict(beats=len(rows), turns=0, latencies=[], gaps=[],
               outcome=dict(settled=0, re_turned=0, corrected_back=0, never_settled=0))
    for i, row in enumerate(rows):
        if row['turn'] == '-':
            continue
        out['turns'] += 1
        new = row['f1']
        if i + 1 < len(rows):
            out['gaps'].append(rows[i + 1]['t'] - row['t'])
        for j in range(i + 1, min(i + 1 + MAX_LOOKAHEAD, len(rows))):
            nxt = rows[j]
            if nxt['turn'] != '-':
                out['outcome']['re_turned'] += 1
                break
            if nxt['f0'] == new and nxt['f1'] == new:
                out['outcome']['settled'] += 1
                out['latencies'].append(nxt['t'] - row['t'])
                break
            if nxt['f1'] != new:
                out['outcome']['corrected_back'] += 1
                break
        else:
            out['outcome']['never_settled'] += 1
    return out


def _q(values, p):
    return values[min(len(values) - 1, int(len(values) * p))]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else LOG
    with open(path, encoding='utf-8', errors='ignore') as f:
        out = scan(f)
    print(f'log        : {path}')
    print(f'beats      : {out["beats"]}')
    print(f'turn beats : {out["turns"]}')
    if not out['turns']:
        return
    print('\n== outcome after each turn ==')
    for k, v in out['outcome'].items():
        print(f'  {k:<16} {v:>6}  ({100 * v / out["turns"]:5.1f}%)')
    lat = sorted(out['latencies'])
    if lat:
        print('\n== latency: turn -> first beat whose zone uses the NEW facing ==')
        print(f'  n={len(lat)}  p50={_q(lat, .5):.3f}s  p75={_q(lat, .75):.3f}s  '
              f'p90={_q(lat, .9):.3f}s  p99={_q(lat, .99):.3f}s  max={lat[-1]:.3f}s')
        for thr in (0.25, 0.5, 0.8, 1.0):
            n = sum(1 for x in lat if x > thr)
            print(f'  > {thr}s : {n:>5}  ({100 * n / len(lat):5.1f}%)')
    gaps = sorted(out['gaps'])
    if gaps:
        print('\n== gap: turn beat -> the very next beat ==')
        print(f'  p50={_q(gaps, .5):.3f}s  p90={_q(gaps, .9):.3f}s  '
              f'p99={_q(gaps, .99):.3f}s  max={gaps[-1]:.3f}s')


if __name__ == '__main__':
    main()
