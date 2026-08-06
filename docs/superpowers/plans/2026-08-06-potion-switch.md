# 喝药总开关 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「喝药开关」总配置,一键关闭自动喝血/喝蓝(含保命分支的按药键),默认开启、行为不变。

**Architecture:** 在 `MapleFarmTask.run()` 里按代码库既有「走位开关」的内联门控模式:保命分支的 `send_key(血药键)` 加 `if cfg['喝药开关']:`;步骤 2(喝血)/3(喝蓝)/3.5(药水耗尽保护)整段包进 `if cfg['喝药开关']:`。不做任何 farm_logic 纯函数改动。

**Tech Stack:** Python 3.12(unittest, mock),OpenCV 帧读取,嵌入式 Python 运行(见 Global Constraints)。

## Global Constraints

- 测试/运行一律用嵌入式 Python:`"H:\ok-mxd\data\apps\ok-ww\python\python.exe"`,需前置环境变量 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`(否则中文输出乱码)
- 分辨率仅 2560x1440(任务帧尺寸守卫,与本次改动无关,不可动)
- 新增配置键只改 `DEFAULT_CONFIG`(`src/task/MapleFarmTask.py:14-41`),测试从 `make_task()` 直接取它,不需要手工同步
- `喝药开关` 默认必须是 `True`:默认行为与现状逐字节一致,现有测试不许改动一行
- 配置键命名沿用中文 +「X开关」风格(`拾取开关`、`走位开关`)
- 代码注释用中文,与文件现有风格一致

---

### Task 1: 喝药开关配置与门控

**Files:**
- Modify: `src/task/MapleFarmTask.py`(DEFAULT_CONFIG、config_description、run() 步骤 1/2/3/3.5、on_create 的 prewarm)
- Modify: `tests/test_farm_task_offline.py`(run_with_frame 加 mp 参数 + 4 个新用例)

**Interfaces:**
- Consumes: 无(不依赖其他任务;本计划只有这一个任务)
- Produces: 配置键 `'喝药开关'`(bool,默认 `True`);关闭时 run() 不按 `血药键`/`蓝药键`

- [ ] **Step 1: 给测试助手 `run_with_frame` 加 `mp` 参数**

`tests/test_farm_task_offline.py:31-46` 当前签名 `run_with_frame(task, hp=None, exp=None, now=100.0)`。改成:

```python
def run_with_frame(task, hp=None, mp=None, exp=None, now=100.0):
    """以存档帧驱动一次 run();hp/mp/exp 不为 None 时替换对应读数。
    now 可推进模拟时间(默认 100.0,与旧调用兼容)。"""
    frame_p = patch.object(MapleFarmTask, 'frame',
                           new=property(lambda self: cv2.imread(FRAME)))
    patches = [frame_p, patch('time.time', return_value=now)]
    if hp is not None:
        patches.append(patch('src.task.MapleFarmTask.bars.read_hp', return_value=hp))
    if mp is not None:
        patches.append(patch('src.task.MapleFarmTask.bars.read_mp', return_value=mp))
    if exp is not None:
        patches.append(patch('src.task.MapleFarmTask.bars.read_exp', return_value=exp))
    for p in patches:
        p.start()
    try:
        task.run()
    finally:
        for p in patches:
            p.stop()
```

- [ ] **Step 2: 写 4 个失败测试**

在 `tests/test_farm_task_offline.py` 的 `TestFarmTaskOffline` 类末尾(紧跟 `test_first_drink_not_judged_ineffective` 之后)追加:

```python
    def test_potion_switch_off_never_drinks_hp(self):
        """关开关:HP 低于喝血阈值 → 不按血药键,也不触发无效检测停止。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False, '喝药开关': False})
        run_with_frame(task, hp=0.5)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('home', sent)
        task.stop_farming.assert_not_called()

    def test_potion_switch_off_never_drinks_mp(self):
        """关开关:MP 低于喝蓝阈值 → 不按蓝药键。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False, '喝药开关': False})
        run_with_frame(task, hp=0.9, mp=0.2)
        sent = [c.args[0] for c in task.send_key.call_args_list if c.args]
        self.assertNotIn('insert', sent)
        task.stop_farming.assert_not_called()

    def test_potion_switch_off_emergency_still_scrolls(self):
        """关开关 + HP 触保命血线:不按血药键,但回城卷与停任务照常。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False, '喝药开关': False})
        task.get_global_config = MagicMock(return_value={**KEYS, '回城卷键(可留空)': 't'})
        run_with_frame(task, hp=0.2)
        calls = task.send_key.call_args_list
        self.assertNotIn(call('home'), calls)
        self.assertIn(call('t', after_sleep=2), calls)
        task.stop_farming.assert_called_once_with('低血保命')

    def test_potion_switch_on_drinks_by_default(self):
        """默认(开关开):HP 低于阈值 → 照常喝药,行为不变。"""
        task = make_task(**{'攻击模式': '定频', '走位开关': False})
        run_with_frame(task, hp=0.5)
        self.assertIn(call('home'), task.send_key.call_args_list)
        task.stop_farming.assert_not_called()
```

- [ ] **Step 3: 跑测试确认失败(红)**

Run:

```bash
cd /h/ok-mxd/ok-mxd && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "H:\ok-mxd\data\apps\ok-ww\python\python.exe" -m unittest tests.test_farm_task_offline.TestFarmTaskOffline.test_potion_switch_off_never_drinks_hp tests.test_farm_task_offline.TestFarmTaskOffline.test_potion_switch_off_never_drinks_mp tests.test_farm_task_offline.TestFarmTaskOffline.test_potion_switch_off_emergency_still_scrolls tests.test_farm_task_offline.TestFarmTaskOffline.test_potion_switch_on_drinks_by_default -v 2>&1 | grep -vE "QFluentWidgets|ok:app path|Tips:"
```

Expected: 3 个「关开关」用例 FAIL(旧代码仍按药键),1 个「默认开」用例 PASS。若存档测试帧缺失(`screenshots/test_frames/` 被 GUI 清空),先从备份恢复:

```bash
mkdir -p "H:\ok-mxd\ok-mxd\screenshots\test_frames" && cp "H:\ok-mxd\_frames_backup\training_ground_full_2560x1440.png" "H:\ok-mxd\ok-mxd\screenshots\test_frames\training_ground_full_2560x1440.png"
```

- [ ] **Step 4: 实现(配置 + 门控)**

**4a. `src/task/MapleFarmTask.py` DEFAULT_CONFIG**(当前第 21-22 行附近,`'喝药判定间隔(秒)'` 之后):

```python
    '喝药判定间隔(秒)': 1.0,
    '喝药开关': True,
```

**4b. `config_description.update({...})`**(当前第 64-68 行附近,`'喝药判定间隔(秒)'` 条目之后):

```python
            '喝药开关': '总开关:关闭后不自动喝血/喝蓝;保命时也不按血药键(回城卷与停任务照常)',
```

**4c. `on_create` 的 prewarm 门控**(当前第 100-101 行):

```python
        if self.config.get('药水耗尽保护') and self.config.get('喝药开关'):
            potions.prewarm()
```

**4d. 保命分支**(当前第 204-205 行,`is_emergency` 判断后):

```python
        if farm_logic.is_emergency(hp, cfg['保命血线']):
            if cfg['喝药开关']:
                self.send_key(keys['血药键'])
            scroll = keys.get('回城卷键(可留空)', '')
```

**4e. 步骤 2/3/3.5 整段包进开关**(当前第 214-249 行,从「# 2. 喝血」注释到 3.5 的 if 块结束;整段缩进 +4 空格,外面包一层):

```python
        # 2-3.5. 喝血/喝蓝/药水耗尽保护。喝药开关关闭时整段跳过:
        # 不按血/蓝药键、不 OCR 快捷栏,「连续喝药无效」检测也不跑。
        if cfg['喝药开关']:
            # 2. 喝血(连续无效检测:按 1s 窗口判定——按下药键一个窗口后 HP 仍未涨过 1%
            #    才累计,超上限停任务。绝不在按下药键的同一帧判定:那一帧药效还没出来,
            #    渐进回血(战斗中常见)每 0.1s 一跳往往不足 1%,逐帧判定必误停;
            #    窗口内也只按一次药键,避免 10Hz 连按浪费药水)
            if farm_logic.need_hp_potion(hp, cfg['喝血阈值']):
                if farm_logic.potion_window_elapsed(now, self._last_hp_potion_press,
                                                    cfg['喝药判定间隔(秒)']):
                    # 上一窗口已结束,和按下药键时的 HP 对比:涨了说明药在起效,清零
                    if self._last_hp_potion_press > 0:
                        self._hp_streak = self._hp_streak + 1 if hp <= self._hp_at_press + 0.01 else 0
                    self._hp_at_press = hp
                    self.send_key(keys['血药键'])
                    self._last_hp_potion_press = now
                    if farm_logic.potion_not_working(self._hp_streak, cfg['喝药无效上限']):
                        self.stop_farming('连续喝药无效')
                        return
            else:
                # 血回到阈值上:清零,下次掉血视为"新的一轮"(只记基线,不计无效)
                self._hp_streak = 0
                self._last_hp_potion_press = 0.0

            # 3. 喝蓝
            if farm_logic.need_mp_potion(mp, cfg['喝蓝阈值']):
                self.send_key(keys['蓝药键'])

            # 3.5 药水耗尽保护(低频 OCR)
            if cfg['药水耗尽保护'] and now - self._last_potion_check >= cfg['药水检查间隔(秒)']:
                self._last_potion_check = now
                hp_count = potions.read_slot_count(frame, self._slot_of(keys['血药键']))
                mp_count = potions.read_slot_count(frame, self._slot_of(keys['蓝药键']))
                empty = farm_logic.potions_exhausted(hp, cfg['喝血阈值'], hp_count,
                                                     mp, cfg['喝蓝阈值'], mp_count)
                if empty:
                    self.stop_farming(f'{"血" if empty == "hp" else "蓝"}药耗尽')
                    return
```

注意 4e 的缩进:整段比原来多 4 格,但块内相对关系不变;`run()` 后续步骤(4. 攻击 / 4.5 走位 / 5. 拾取 / 6. 守卫 / 经验)保持原缩进不动。

- [ ] **Step 5: 跑新测试确认通过(绿)**

Run: Step 3 同一条命令。Expected: 4 个用例全 PASS。

- [ ] **Step 6: 跑全量测试确认无回归**

Run:

```bash
cd /h/ok-mxd/ok-mxd && PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "H:\ok-mxd\data\apps\ok-ww\python\python.exe" -m unittest discover tests -p "test_*.py" 2>&1 | grep -vE "QFluentWidgets|ok:app path|Tips:|task:enabled" | tail -5
```

Expected: `Ran 100 tests ... OK (skipped=4)`(96 个旧用例 + 4 个新用例;4 个 skip 为既有 live 测试,与本次无关)。

- [ ] **Step 7: 提交**

```bash
git add src/task/MapleFarmTask.py tests/test_farm_task_offline.py
git commit -m "feat: potion switch to disable auto HP/MP drinking (master toggle)

Co-Authored-By: Claude <noreply@anthropic.com>"
```
