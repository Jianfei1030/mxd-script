# 定时补BUFF设计文档

> 日期：2026-08-10
> 状态：已批准（用户确认全部设计决策）

## [S1] 问题

挂机时增益技能（BUFF）持续时间到期后不会自动补,输出/生存下降。本特性:按用户配置的每个 BUFF 独立间隔时间,到点且**攻击区内无怪**时自动按 BUFF 快捷键补上;攻击区内有怪则优先解决怪物,顺延到下一拍。

**关键约束（用户确认）**：
- **每个 BUFF 独立配置按键 + 对应的间隔时间**（用户填写按键以及对应的时间,不是全局统一间隔）
- 攻击区判定用**攻击区**（`_last_attack_present`,有向攻击区内有无怪,去抖后）——怪进了攻击距离就不补
- **补BUFF时停手**:触发的那一拍暂停攻击/寻怪,只按 BUFF 键
- 复用已预留的 `parse_buff_config`（farm_logic.py:205,`名称=按键` 逗号分隔）并扩展支持每项独立间隔

## [S2] 方案概述

```
run() 攻击块之前新增补BUFF块:
  if 补BUFF开关 开 且 _last_attack_present is False:   ← 攻击区内无怪
      due = due_buffs(now, parse_buff_config(配置), _last_buff_times)  ← 到期的BUFF列表
      if due:
          _release_seek_key(); _seek_dir = None   ← 停手:停追
          依次 send_key(每个到期BUFF的键)
          更新对应 _last_buff_times[name] = now
          return   ← 本拍只补BUFF,不执行攻击/寻怪/坐椅等
  攻击区内有怪 → 跳过补BUFF,正常攻击,下一拍攻击区空了再补
```

**到期判定（每 BUFF 独立计时）**：
- `_last_buff_times: dict[str, float]` 记录每个 BUFF 名称的上次补的时间
- BUFF 到期 = `now - _last_buff_times.get(name, 0) >= interval`（未补过则到期）
- 只按**到期的** BUFF 键,未到期的不按

## [S3] 配置项（MapleFarmTask DEFAULT_CONFIG + CONFIG_GROUPS「挂机辅助」组）

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| 补BUFF开关 | bool | false | 总开关 |
| 补BUFF列表 | str | '' | 格式 `名称=按键:间隔秒,名称=按键:间隔秒`。例:`魔法盾=q:180,狂暴=w:300`。逗号分隔多项,每项 `名称=按键:间隔秒` |

- 放任务配置（非全局按键）:BUFF 列表是「按键+时间」组合策略,一个字符串整体配置,与喂宠物/坐椅同属挂机辅助
- 解析走 `farm_logic.parse_buff_config`（扩展支持 `:间隔` 后缀,见 [S4]）

## [S4] 纯函数扩展（farm_logic.py）

### 4.1 parse_buff_config 扩展

现有（farm_logic.py:205-214）：
```python
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
```

扩展为支持每项间隔：
```python
def parse_buff_config(text):
    """'magic_shield=q:180,armor=w' -> [('magic_shield', 'q', 180), ('armor', 'w', None)]
    每项格式 名称=按键[:间隔秒];间隔缺省为 None(永不自动补,只手动按)。
    """
    result = []
    for entry in (text or '').split(','):
        entry = entry.strip()
        if '=' in entry:
            name, rest = entry.split('=', 1)
            key = rest
            interval = None
            if ':' in rest:
                key, _, iv = rest.partition(':')
                try:
                    interval = int(iv.strip())
                except ValueError:
                    interval = None
            if name.strip() and key.strip():
                result.append((name.strip(), key.strip(), interval))
    return result
```

- 返回三元组 `(name, key, interval)`,interval 为 None 表示不自动补（保留手动按键能力）
- **既有测试更新**：`tests/test_farm_logic.py::test_parse_buff_config` 断言改为三元组（旧 `('magic_shield','q')` → `('magic_shield','q',None)`）

### 4.2 新增 due_buffs

```python
def due_buffs(now, buffs, last_times):
    """buffs: parse_buff_config 输出 [(name, key, interval)];last_times: {name: 上次补的时间}
    返回需要补的 [(name, key)]:interval 非 None 且 now - last_times.get(name, 0) >= interval。
    """
    return [(name, key) for name, key, interval in buffs
            if interval is not None and now - last_times.get(name, 0) >= interval]
```

## [S5] 任务集成（MapleFarmTask）

### 5.1 实例字段（_reset_state 初始化）

- `_last_buff_times: dict[str, float] = {}`（每 BUFF 上次补的时间;重启用空 dict = 全部未补过,到点即补）

### 5.2 run() 补BUFF块

位置：§4 攻击块之前（保命/喝药之后、检测拍之前）。理由:补BUFF只按键不检测,放最前保证「本拍只补BUFF」的 return 语义干净,且攻击区判定用上一拍的 `_last_attack_present` 即可（10Hz 足够及时）。

```python
# 3.6 定时补BUFF(挂机辅助):攻击区内无怪才补;有怪优先解决,顺延下一拍
if cfg['补BUFF开关'] and self._last_attack_present is False:
    due = farm_logic.due_buffs(now, farm_logic.parse_buff_config(cfg['补BUFF列表']),
                               self._last_buff_times)
    if due:
        self._release_seek_key()   # 停手:先松开寻怪长按的方向键
        self._seek_dir = None      # 停追:本拍不寻怪
        for name, key in due:
            self.send_key(key)
            self._last_buff_times[name] = now
        self.log_info(f'补BUFF: {", ".join(n for n, _ in due)}')
        return   # 本拍只补BUFF,不执行攻击/寻怪/坐椅等
```

- `_release_seek_key` 已有（自带 None 守卫,见 _detect_and_act 的用法）
- return 与死亡/保命 return 同模式:跳过本拍其余逻辑,仅一拍,无碍

### 5.3 与现有逻辑的关系

- **有怪优先**：`_last_attack_present is False` 门——攻击区有怪时补BUFF块直接跳过,攻击逻辑正常执行
- **停手**：触发时 `_release_seek_key` + `_seek_dir=None` + return,本拍不攻击不寻怪
- 定频模式：`_last_attack_present` 恒为 None（无检测拍）,`is False` 判定需注意——**定频模式不补BUFF**（同坐椅的定频例外,补BUFF需要检测拍的攻击区状态）;开关描述注明

## [S6] 文件结构与依赖

**修改**：
- `src/task/farm_logic.py` — parse_buff_config 扩展 + due_buffs 新增
- `src/task/MapleFarmTask.py` — DEFAULT_CONFIG + CONFIG_GROUPS + _reset_state + run() 补BUFF块
- `tests/test_farm_logic.py` — parse_buff_config 断言更新 + due_buffs 用例
- `tests/test_farm_task_offline.py` — 补BUFF任务用例
- `tests/test_config_groups.py` — 新键归组完整性自动覆盖

**依赖**：无新依赖

## [S7] 测试与验收

### 7.1 单元测试（离线可跑）

`tests/test_farm_logic.py`：
- parse_buff_config 扩展：`'魔法盾=q:180,狂暴=w:300'` → 三元组带间隔;无间隔项 → None;坏条目跳过;空字符串 → []
- due_buffs：到期返回、未到期不返回、interval None 不返回、从未补过（last_times 无该名）视为到期

`tests/test_farm_task_offline.py`（新增补BUFF用例）：
- 开关关 → 不补
- 到点且攻击区无怪 → 按 BUFF 键（记录 send_key 序列）+ 更新 _last_buff_times
- 攻击区有怪 → 不补,正常攻击
- 多个 BUFF 只补到期的
- 触发时停手：_seek_dir 置 None、不调用寻怪/攻击
- 补BUFF块在攻击块之前,return 语义正确

### 7.2 编译检查与全量单测

```powershell
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -m unittest tests.test_farm_logic tests.test_farm_task_offline tests.test_config_groups
$env:PYTHONUTF8=1; & "C:\Users\jianfei\AppData\Local\Programs\Python\Python312\python.exe" -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for base in ['src','scripts','tests','ok'] for p in pathlib.Path(base).rglob('*.py')]; print('OK')"`
Expected: 全绿 + OK

### 7.3 E2E（AGENTS.md §11.3）

- GUI 启动无崩溃;「自动打怪」卡片「挂机辅助」组出现「补BUFF开关/补BUFF列表」
- 实机验收：配置 `魔法盾=q:180,狂暴=w:300`,站桩等 3 分钟看是否自动补;战斗中被怪打断时优先攻击（需实机验证）,结论写入 spec 验收章节

## [S8] 全局约束（Global Constraints）

- 新配置键只改 DEFAULT_CONFIG + CONFIG_GROUPS
- 每个 BUFF 独立间隔（用户口径）;interval None 不自动补
- 攻击区内有怪优先解决,补BUFF顺延;补BUFF时停手（松寻怪键+停追+本拍 return）
- 定频模式不补BUFF（无攻击区状态）;开关描述注明
- 测试命令/编译检查同上;禁止 hard code 本地路径
