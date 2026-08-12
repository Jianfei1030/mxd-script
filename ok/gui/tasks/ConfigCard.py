from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton
from qfluentwidgets import FluentIcon, ExpandSettingCard, PushButton

from ok import og
from ok.gui.tasks.ConfigItemFactory import config_widget
from ok.gui.tasks.LabelAndWidget import LabelAndWidget


class ConfigContentMixin:
    def _init_config_content(self, task, config, default_config, config_description, config_type):
        self.config = config
        self.config_widgets = []
        self.config_widget_by_key = {}
        self.config_keys = []
        self.group_headers = []                 # 组标题列表(搜索过滤时显隐)
        self.group_header_by_group = {}         # 组名 → 组标题控件
        self.group_widgets = {}                 # 组名 → 该组配置项控件列表(折叠时整体显隐)
        self.group_collapsed = {}               # 组名 → 是否折叠(会话级,不持久化)
        self._last_config_group = None          # 渲染中的当前组名
        self._current_group = None              # 当前渲染键所属组(登记 widget 用,None=未分组)
        self.default_config = default_config
        self.config_description = config_description
        self.config_type = config_type
        self.sub_configs_rules = {}
        self.sub_configs_controlled_keys = {}
        self.sub_configs_dividers = {}
        self.task = task
        self.reset_config = None
        self.__initWidget()

    def reset_clicked(self):
        self.config.reset_to_default()
        self.update_config()

    def add_buttons(self):
        if self.default_config or (self.task and self.task.show_create_shortcut):
            layout = LabelAndWidget(self.tr('Operation'))
            buttons_layout = QHBoxLayout()
            buttons_layout.addStretch(1)
            layout.add_layout(buttons_layout)
            self.viewLayout.addWidget(layout)

            if self.default_config:
                self.reset_config = PushButton(FluentIcon.CANCEL, self.tr("Reset Config"))
                buttons_layout.addWidget(self.reset_config)
                self.reset_config.clicked.connect(self.reset_clicked)

            if self.task and self.task.show_create_shortcut:
                create_shortcut = PushButton(FluentIcon.LINK, self.tr("Add Start Menu Shortcut"))
                buttons_layout.addWidget(create_shortcut)
                create_shortcut.clicked.connect(self.task.create_shortcut)

    def __initWidget(self):
        # initialize layout
        self.viewLayout.setSpacing(0)
        self.viewLayout.setAlignment(Qt.AlignTop)
        self.viewLayout.setContentsMargins(6, 4, 6, 8)
        self.__maybe_add_search_box()
        self.sub_configs_rules = self.__collect_sub_configs_rules()
        self.sub_configs_controlled_keys = self.__collect_sub_configs_controlled_keys()
        if not self.config or not (self.config.has_user_config() or self.default_config or self.config_type):
            self._on_empty_config_content()
        else:
            added_keys = set()
            for key in self.__ordered_config_keys():
                if not key.startswith('_') and not self.__is_hidden_config(key) and not self.__is_sub_config_key(key):
                    self.__addConfigWithSubConfigs(key, self.config.get(key), added_keys, set())
            if self.config_type:
                for key, the_type in self.config_type.items():
                    if key not in added_keys and not key.startswith('_') and not self.__is_hidden_config(key):
                        if self.__is_button_config(the_type) and not self.__is_sub_config_key(key):
                            self.__addConfigWithSubConfigs(key, None, added_keys, set())
        self.__setup_sub_configs()
        self.add_buttons()
        self.__load_group_collapsed()
        if hasattr(self, 'search_box'):
            self.__apply_search_filter(self.search_box.text())
        self._adjust_config_content_size()

    def _on_empty_config_content(self):
        pass

    def _adjust_config_content_size(self):
        if hasattr(self, '_adjustViewSize'):
            self._adjustViewSize()

    def __addConfigWithSubConfigs(self, key: str, value, added_keys, adding_keys):
        if key in added_keys or key in adding_keys:
            return

        adding_keys.add(key)
        has_sub_configs = self.__has_renderable_sub_configs(key)
        if has_sub_configs:
            self.__add_sub_configs_divider(key, 'top')

        self.__addConfig(key, value)
        added_keys.add(key)

        for sub_config_key in self.__get_sub_config_keys(key):
            if sub_config_key.startswith('_'):
                continue

            sub_config_value = self.__get_config_value(sub_config_key)
            if not self.__can_render_config(sub_config_key, sub_config_value):
                continue

            self.__addConfigWithSubConfigs(sub_config_key, sub_config_value, added_keys, adding_keys)

        if has_sub_configs:
            self.__add_sub_configs_divider(key, 'bottom')

        adding_keys.remove(key)

    def __addConfig(self, key: str, value):
        self.__maybe_add_group_header(key)
        widget = config_widget(self.config_type, self.config_description, self.config, key, value, self.task)
        self.config_widgets.append(widget)
        self.config_widget_by_key[key] = widget
        self.config_keys.append(key)
        self.viewLayout.addWidget(widget)
        if self._current_group is not None:
            self.group_widgets[self._current_group].append(widget)

    def __config_groups(self):
        groups = getattr(self.task, 'config_groups', None) if self.task is not None else None
        return groups or []

    def __ordered_config_keys(self):
        """渲染键序:有 config_groups 时按组定义顺序(组内按组内键定义顺序),
        保证每个组只插一次标题、组内容连续;无分组任务保持原 dict 顺序。"""
        groups = self.__config_groups()
        if not groups:
            return list(self.config.keys())
        ordered = []
        for _group, group_keys in groups:
            for key in group_keys:
                if key in self.config and key not in ordered:
                    ordered.append(key)
        for key in self.config:
            if key not in ordered:
                ordered.append(key)
        return ordered

    def __maybe_add_group_header(self, key: str):
        groups = self.__config_groups()
        if not groups:
            self._current_group = None
            return
        from src.task.config_groups import group_of, should_insert_header
        group = group_of(key, groups)
        self._current_group = group
        if should_insert_header(self._last_config_group, group):
            header = QToolButton(self)
            header.setText(group)
            header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            header.setArrowType(Qt.DownArrow)
            header.setCursor(Qt.PointingHandCursor)
            header.setObjectName('configGroupHeader')
            header.setStyleSheet(
                'color: #009faa; font-weight: 600;'
                'padding: 6px 4px 2px 4px; background: transparent; border: none;')
            header.clicked.connect(lambda _checked=False, g=group: self.__toggle_group(g))
            self.viewLayout.addWidget(header)
            self.group_headers.append(header)
            self.group_header_by_group[group] = header
            self.group_widgets[group] = []
            self._last_config_group = group

    def __maybe_add_search_box(self):
        groups = self.__config_groups()
        if not groups:
            return
        from PySide6.QtWidgets import QLineEdit
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText('搜索选项')
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self.__apply_search_filter)
        self.viewLayout.addWidget(self.search_box)

    def __apply_search_filter(self, query):
        groups = self.__config_groups()
        if not groups:
            return
        from src.task.config_groups import visible_groups, visible_keys
        keys = list(self.config_widget_by_key.keys())
        descriptions = self.config_description or {}
        q = (query or '').strip()
        if not q:
            # 无搜索:恢复全部显示后再按折叠状态收起,组标题始终可见(可点击展开)
            for widget in self.config_widgets:
                widget.setVisible(True)
            for header in self.group_headers:
                header.setVisible(True)
            self.__apply_group_collapse()
            self._adjust_config_content_size()
            return
        # 有搜索:匹配优先,折叠忽略(命中即自动展开该组)
        visible = visible_keys(query, keys, descriptions)
        for key, widget in self.config_widget_by_key.items():
            widget.setVisible(key in visible)
        visible_group_names = visible_groups(query, groups, keys, descriptions)
        for group, header in self.group_header_by_group.items():
            header.setVisible(group in visible_group_names)
            header.setArrowType(Qt.DownArrow)  # 搜索中匹配组视为展开(内容已强制显示)
        self._adjust_config_content_size()

    def __toggle_group(self, group):
        """点击组标题:折叠/展开该组。折叠状态只影响无搜索时的展示,并持久化到本地。"""
        self.group_collapsed[group] = not self.group_collapsed.get(group, False)
        self.__save_group_collapsed()
        self.__update_header_arrow(group)
        self.__apply_search_filter(self.search_box.text())

    def __config_groups_state_path(self):
        """折叠状态文件路径:configs/config_groups_state.json(configs/ 被 gitignore,天然本地)。"""
        from ok.util.config import Config
        from ok.util.file import get_relative_path
        return get_relative_path(Config.config_folder, 'config_groups_state.json')

    def __load_group_collapsed(self):
        """渲染完成后读取本地折叠状态,仅覆盖已渲染的组(旧组名残留自动忽略)。"""
        groups = self.__config_groups()
        if not groups or self.task is None:
            return
        from ok.util.file import read_json_file
        data = read_json_file(self.__config_groups_state_path()) or {}
        stored = data.get(self.task.__class__.__name__) or {}
        valid_groups = {g for g, _ in groups}
        self.group_collapsed.update(
            {g: bool(v) for g, v in stored.items() if g in valid_groups})

    def __save_group_collapsed(self):
        """折叠状态变化即写回本地,按任务类名分节。"""
        groups = self.__config_groups()
        if not groups or self.task is None:
            return
        from ok.util.file import read_json_file, write_json_file
        path = self.__config_groups_state_path()
        data = read_json_file(path) or {}
        data[self.task.__class__.__name__] = dict(self.group_collapsed)
        write_json_file(path, data)

    def __update_header_arrow(self, group):
        header = self.group_header_by_group.get(group)
        if header is not None:
            header.setArrowType(Qt.RightArrow if self.group_collapsed.get(group, False) else Qt.DownArrow)

    def __apply_group_collapse(self):
        """无搜索时按折叠状态收起组内配置项(组标题保持可见)。"""
        for group, widgets in self.group_widgets.items():
            collapsed = self.group_collapsed.get(group, False)
            for widget in widgets:
                widget.setVisible(not collapsed)
            self.__update_header_arrow(group)

    def __add_sub_configs_divider(self, key, position):
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setObjectName('subConfigsDivider')
        divider.setFixedHeight(1)
        divider.setStyleSheet("color: rgba(128, 128, 128, 90); background-color: rgba(128, 128, 128, 90);")
        self.sub_configs_dividers.setdefault(key, {})[position] = divider
        self.viewLayout.addWidget(divider)

    def __is_button_config(self, the_type):
        return (
            isinstance(the_type, dict)
            and (
                the_type.get('type') in ('button', 'dependency_check')
                or ('type' not in the_type and ('buttons' in the_type or 'callback' in the_type))
            )
        )

    def __setup_sub_configs(self):
        if not self.sub_configs_rules:
            return

        for key in self.sub_configs_rules:
            widget = self.config_widget_by_key.get(key)
            combo_box = getattr(widget, 'combo_box', None)
            if combo_box is not None:
                combo_box.currentTextChanged.connect(self.__apply_sub_config_visibility)
            switch_button = getattr(widget, 'switch_button', None)
            if switch_button is not None:
                switch_button.checkedChanged.connect(self.__apply_sub_config_visibility)

        self.__apply_sub_config_visibility()

    def __collect_sub_configs_rules(self):
        rules = {}
        if not self.config_type:
            return rules

        for key, the_type in self.config_type.items():
            if not isinstance(the_type, dict):
                continue

            sub_configs = the_type.get('sub_configs')
            if not isinstance(sub_configs, dict):
                continue

            rules[key] = {
                choice: self.__normalize_sub_config_keys(config_keys)
                for choice, config_keys in sub_configs.items()
            }

        return rules

    def __collect_sub_configs_controlled_keys(self):
        return {
            key: set().union(*rule.values()) if rule else set()
            for key, rule in self.sub_configs_rules.items()
        }

    def __normalize_sub_config_keys(self, config_keys):
        if config_keys is None:
            return []
        if isinstance(config_keys, str):
            return [config_keys]
        return list(config_keys)

    def __is_sub_config_key(self, key):
        return any(key in keys for keys in self.sub_configs_controlled_keys.values())

    def __get_config_type(self, key):
        if self.config_type is None:
            return None
        return self.config_type.get(key)

    def __is_hidden_config(self, key):
        the_type = self.__get_config_type(key)
        return isinstance(the_type, dict) and the_type.get('hidden', False)

    def __get_config_value(self, key):
        if self.config is not None and key in self.config:
            return self.config.get(key)
        return None

    def __can_render_config(self, key, value):
        return value is not None or self.__is_button_config(self.__get_config_type(key))

    def __has_renderable_sub_configs(self, key):
        for sub_config_key in self.__get_sub_config_keys(key):
            if sub_config_key.startswith('_'):
                continue
            if self.__can_render_config(sub_config_key, self.__get_config_value(sub_config_key)):
                return True
        return False

    def __get_sub_config_keys(self, key):
        keys = []
        for config_keys in self.sub_configs_rules.get(key, {}).values():
            for config_key in config_keys:
                if config_key not in keys:
                    keys.append(config_key)
        return keys

    def __get_active_sub_config_keys(self, key):
        try:
            config_keys = self.sub_configs_rules.get(key, {}).get(self.config.get(key), [])
        except TypeError:
            return []
        return [
            config_key for config_key in config_keys
            if config_key in self.config_widget_by_key
        ]

    def __apply_sub_config_visibility(self, *args):
        self.__sync_sub_config_order()
        for key, widget in self.config_widget_by_key.items():
            widget.setVisible(self.__is_config_visible(key, set()))
        for key, dividers in self.sub_configs_dividers.items():
            visible = self.__is_sub_configs_group_visible(key)
            for divider in dividers.values():
                divider.setVisible(visible)
        self._adjust_config_content_size()

    def __sync_sub_config_order(self):
        for widget in self.config_widget_by_key.values():
            self.viewLayout.removeWidget(widget)
        for dividers in self.sub_configs_dividers.values():
            for divider in dividers.values():
                self.viewLayout.removeWidget(divider)

        insert_index = 0
        for key in self.config_keys:
            if self.__is_sub_config_key(key):
                continue
            insert_index = self.__insert_config_group(key, insert_index, set())

    def __insert_config_group(self, key, insert_index, inserting_keys):
        if key in inserting_keys or key not in self.config_widget_by_key:
            return insert_index

        inserting_keys.add(key)
        active_sub_config_keys = self.__get_active_sub_config_keys(key)
        has_visible_sub_configs = any(
            self.__is_config_visible(sub_config_key, set())
            for sub_config_key in active_sub_config_keys
        )

        if has_visible_sub_configs:
            insert_index = self.__insert_sub_configs_divider(key, 'top', insert_index)

        self.viewLayout.insertWidget(insert_index, self.config_widget_by_key[key])
        insert_index += 1

        for sub_config_key in active_sub_config_keys:
            insert_index = self.__insert_config_group(sub_config_key, insert_index, inserting_keys)

        if has_visible_sub_configs:
            insert_index = self.__insert_sub_configs_divider(key, 'bottom', insert_index)

        inserting_keys.remove(key)
        return insert_index

    def __insert_sub_configs_divider(self, key, position, insert_index):
        divider = self.sub_configs_dividers.get(key, {}).get(position)
        if divider is None:
            return insert_index

        self.viewLayout.insertWidget(insert_index, divider)
        return insert_index + 1

    def __is_sub_configs_group_visible(self, key):
        if not self.__is_config_visible(key, set()):
            return False
        for sub_config_key in self.__get_active_sub_config_keys(key):
            if sub_config_key in self.config_widget_by_key and self.__is_config_visible(sub_config_key, set()):
                return True
        return False

    def __is_config_visible(self, key, checking):
        if key in checking:
            return False

        checking = checking | {key}
        for parent_key, rule in self.sub_configs_rules.items():
            if key not in self.sub_configs_controlled_keys.get(parent_key, set()):
                continue

            if not self.__is_config_visible(parent_key, checking):
                return False

            try:
                visible_config_keys = rule.get(self.config.get(parent_key), [])
            except TypeError:
                visible_config_keys = []

            if key not in visible_config_keys:
                return False

        return True

    def update_config(self):
        for widget in self.config_widgets:
            widget.update_value()
        self.__apply_sub_config_visibility()


class ConfigCard(ConfigContentMixin, ExpandSettingCard):
    def __init__(self, task, name, config, description, default_config, config_description,
                 config_type, config_icon):

        self._expand_enabled = True
        super().__init__(config_icon or FluentIcon.INFO, og.app.tr(name), og.app.tr(description))
        self._init_config_content(task, config, default_config, config_description, config_type)

    def setExpand(self, isExpand: bool):
        if isExpand and not self._expand_enabled:
            return
        super().setExpand(isExpand)

    def _on_empty_config_content(self):
        self._expand_enabled = False
        self.card.expandButton.hide()
