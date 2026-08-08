# -*- coding: utf-8 -*-
"""朝向观测器判据 A/B/C/D(2026-08-08-facing-observer-design.md §5.4)。

判据在 spec 里事先写死,本脚本只是把它算出来,不许在这里改通过线。

解析语义(2026-08-08 评审修订,配套 tests/test_analyze_facing.py 绑定):

- 判据 A 的分母是「锚点真命中 **且已有模板**」的拍 —— 模板采集(朝向模板已采集
  行)之前的拍一律不计,否则第一次寻怪走动确认之前的几十秒全被当弃权,可用率
  被压低,仪器修得再好也判不过。
- 判据 B 的「没发方向键」不看 转向= 字段:寻怪每拍长按方向键却恒为 -(转向只
  在接战分支赋值),冷却/抑制窗挡住的转向键没落地却照样写 转向=right。
  改用信念 `朝向=f0→f1` 判定 —— _facing 只在转向 tap 落地、寻怪换向、走位结束
  时才会变,所以「两拍都 f0==f1 且拍间一致(f1_prev == f0_cur)」才构成拍对。

用法: python scripts/analyze_facing.py [起始时间 HH:MM:SS]
"""
import re
import sys

LOG = 'logs/ok-script.log'
TS = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d{3})')
CAP = re.compile(r'朝向模板已采集')
DEC = re.compile(r'决策 src=(\S+) .*?朝向=(\S+)→(\S+) 转向=\S+ 寻怪=\S+ '
                 r'可发键=\w+ 实测=(\S+) 分值=')
DIV = re.compile(r'朝向分歧 信念=(\S+) 实测=(\S+) 分值=\S+ 距上次攻击=([\d.]+)s')
FRESH = ('window', 'region', 'template')


def scan(lines, start='00:00:00'):
    """扫日志算判据统计。lines: 可迭代的行;start: HH:MM:SS 起始时间。

    起始时间只挡计数,不挡状态:模板采集在 start 之前也要让分母从那里算起。
    """
    fresh = answered = 0
    belief_known_and_answered = 0
    prev = None            # (实测, 本拍信念是否稳定 f0==f1, 本拍 f1)
    flips = pairs = 0
    divergences = []
    have_template = False
    for line in lines:
        if CAP.search(line):
            have_template = True
        m = TS.match(line)
        if not m or m.group(1)[11:] < start:
            continue
        d = DIV.search(line)
        if d:
            divergences.append(float(d.group(3)))
            continue
        d = DEC.search(line)
        if not d:
            continue
        src, f0, f1, obs = d.groups()
        if src not in FRESH:
            prev = None
            continue
        if not have_template:
            prev = None
            continue
        fresh += 1
        if obs in ('L', 'R'):
            answered += 1
            if f0 in ('LEFT', 'RIGHT'):
                belief_known_and_answered += 1
            # 拍对成立 ⇔ 上一拍与本拍信念都稳定(f0==f1)且拍间一致(f1_prev==f0):
            # _facing 只在方向键真正落地时变,所以这一条件≈「两拍之间没发方向键」
            stable = f0 == f1
            if prev is not None and prev[1] and stable and prev[2] == f0:
                pairs += 1
                if prev[0] != obs:
                    flips += 1
            prev = (obs, stable, f1)
        else:
            prev = None
    return {'fresh': fresh, 'answered': answered,
            'belief_known_and_answered': belief_known_and_answered,
            'flips': flips, 'pairs': pairs, 'divergences': divergences}


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else '00:00:00'
    with open(LOG, encoding='utf-8', errors='replace') as f:
        st = scan(f, start)
    fresh, answered = st['fresh'], st['answered']
    flips, pairs = st['flips'], st['pairs']
    divergences = st['divergences']
    belief_known_and_answered = st['belief_known_and_answered']

    print('锚点真命中 %d 拍,其中观测给出答案 %d 拍' % (fresh, answered))
    ok = []

    def chk(name, passed, got, want):
        ok.append(passed)
        print('  [%s] %-22s 实测 %-14s 通过线 %s'
              % ('通过' if passed else '不过', name, got, want))

    a = 100.0 * answered / fresh if fresh else 0.0
    chk('A 仪器可用率', a >= 50.0, '%.1f%%' % a, '>= 50%')

    b = 100.0 * flips / pairs if pairs else 0.0
    chk('B 无随机噪声', b <= 5.0, '%.1f%% (n=%d)' % (b, pairs), '<= 5%')

    c = (100.0 * len(divergences) / belief_known_and_answered
         if belief_known_and_answered else 0.0)
    print('  [--] C 分叉率(主结果)      实测 %.1f%% (%d/%d)'
          % (c, len(divergences), belief_known_and_answered))
    if c >= 10.0:
        verdict = '>= 10% → 吞键推论坐实,做动画忙窗'
    elif c < 3.0:
        verdict = '< 3% → 吞键推论证伪,动画忙窗不做,回 Phase 1'
    else:
        verdict = '3-10% 灰区 → 看判据 D 裁决'
    print('       决策线: %s' % verdict)

    # D:按「距上次攻击」分桶,施法窗 [0,1.0s) vs 其余
    if divergences:
        inside = sum(1 for x in divergences if x < 1.0)
        outside = len(divergences) - inside
        print('  [--] D 时间相关性          施法窗内 %d / 窗外 %d' % (inside, outside))
        if outside:
            print('       窗内:窗外 = %.2f (>= 2.0 → 吞键机制坐实)'
                  % (inside / outside))
        else:
            print('       全部落在施法窗内 → 吞键机制坐实')

    if not all(ok):
        print('\nA 或 B 不过 —— C/D 的数字不许解读,先修仪器')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
