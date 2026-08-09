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


def landed(row):
    """这一拍的转向键是不是**真的落地了**。

    不能只看 `转向=` 字段:`_detect_and_act:645` 无条件赋值
    `turn = attack_turn_direction(...)`,之后才用 转向冷却 / 硬直抑制窗 /
    _key_sendable 门控实际按键(:646-654),而 `_log_decision` 收的是那个
    无条件的值 —— 键被挡下、`_facing` 根本没变,日志照样写 `转向=left`。
    `scripts/analyze_facing.py:11-13` 早就记过同一个坑,判据 B 因此改用信念判定。

    `_facing` 只在转向 tap 落地、寻怪换向、走位结束时才变,所以
    「本拍写了 turn」+「信念 f0→f1 确实变了」才算一次真转向。
    2026-08-09 实测 08-08 日志:3452 条 `转向≠-` 里 926 条(26.8%)没落地;
    按字段计数会把 re_turned 从 4.7% 抬到 28.7%,直接顶到计划的回退红线。

    已知残留:先被朝向纠正翻一次、再转回原朝向的拍会出现 f0==f1 而被漏掉。
    analyze_facing 接受同一限制,不在这里另起炉灶。
    """
    return row['turn'] != '-' and row['f0'] != row['f1']


def scan(lines):
    """算统计。语义见计划文档 Task 1,五种结局互斥且必然命中其一。

    truncated = 转向拍之后剩余行数不足 MAX_LOOKAHEAD(日志到此为止),
    结局无从判断,不能当 never_settled —— 后者要求完整 40 拍窗口里都没结算。
    """
    rows = parse(lines)
    out = dict(beats=len(rows), turns=0, latencies=[], gaps=[],
               outcome=dict(settled=0, re_turned=0, corrected_back=0,
                            never_settled=0, truncated=0))
    for i, row in enumerate(rows):
        if not landed(row):
            continue
        out['turns'] += 1
        new = row['f1']
        if i + 1 < len(rows):
            out['gaps'].append(rows[i + 1]['t'] - row['t'])
        tail = len(rows) - (i + 1)   # 该转向拍之后还剩几拍
        for j in range(i + 1, min(i + 1 + MAX_LOOKAHEAD, len(rows))):
            nxt = rows[j]
            if landed(nxt):
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
            # for 走完没 break:窗口内没结算。但若日志在本拍之后不足 40 拍就
            # 到头,那是样本被截断(结局无从判断),不是「40 拍没结算」——
            # 2026-08-09 实测 08-08 那条 never_settled:1 就是末尾那拍正好是
            # 转向拍(索引 26364),被这里误判。truncated 不进百分比分母。
            if tail < MAX_LOOKAHEAD:
                out['outcome']['truncated'] += 1
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
    denom = out['turns'] - out['outcome']['truncated']
    for k in ('settled', 're_turned', 'corrected_back', 'never_settled'):
        v = out['outcome'][k]
        print(f'  {k:<16} {v:>6}  ({100 * v / denom:5.1f}%)')
    if out['outcome']['truncated']:
        print(f'  truncated({MAX_LOOKAHEAD}拍内日志到头)'
              f' {out["outcome"]["truncated"]:>6}  (不计入分母)')
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
