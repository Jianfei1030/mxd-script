# src/task/config_groups.py
"""自动打怪卡片展开区配置项的 分组/搜索 纯函数(UI 展示用,不改任何任务逻辑)。"""


def group_of(key, groups):
    """key 所属的组名;未分组返回 None。groups 形如 [(组名, [键, ...]), ...]。"""
    for group, keys in groups:
        if key in keys:
            return group
    return None


def should_insert_header(prev_group, current_group):
    """渲染到 current_group 的键时,是否需要先插入该组的标题分隔条。"""
    return current_group is not None and current_group != prev_group


def matches(query, key, description):
    """宽松匹配:空/纯空白 query 全匹配;否则键名或描述包含 query(忽略大小写)。"""
    q = (query or '').strip().lower()
    if not q:
        return True
    return q in key.lower() or q in (description or '').lower()


def visible_keys(query, keys, descriptions):
    """query 下应显示的键集合(未匹配的键隐藏)。"""
    return {k for k in keys if matches(query, k, descriptions.get(k, ''))}


def visible_groups(query, groups, keys, descriptions):
    """query 下应显示的组名列表(保持 groups 顺序);组内任一键可见即可见。"""
    visible = visible_keys(query, keys, descriptions)
    return [g for g, g_keys in groups if any(k in visible for k in g_keys)]
