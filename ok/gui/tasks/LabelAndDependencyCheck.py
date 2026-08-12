import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from qfluentwidgets import PushButton

from ok import Logger, og
from ok.gui.tasks.LabelAndWidget import LabelAndWidget
from ok.gui.util.Alert import alert_error, alert_info
from src.dependency import check_dependencies, install_missing, missing_dependencies

logger = Logger.get_logger(__name__)


class LabelAndDependencyCheck(LabelAndWidget):
    """「推理加速」依赖状态 + 一键安装(国内镜像优先,失败自动切换)。"""

    install_done = Signal(bool, str)

    def __init__(self, config_desc, config, key):
        super().__init__(og.app.tr(key), og.app.tr('推理加速所需依赖检查'))
        self._installing = False

        self.status_label = QLabel()
        self.status_label.setObjectName('contentLabel')
        self.status_label.setWordWrap(True)

        self.check_button = PushButton(og.app.tr('重新检测'))
        self.install_button = PushButton(og.app.tr('安装缺失依赖'))
        self.check_button.clicked.connect(self.refresh)
        self.install_button.clicked.connect(self._start_install)
        self.install_done.connect(self._on_install_done)

        right = QVBoxLayout()
        right.addWidget(self.status_label)
        buttons = QHBoxLayout()
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.install_button)
        right.addLayout(buttons)
        self.add_layout(right)

        self.refresh()

    def update_value(self):
        pass

    def refresh(self):
        deps = check_dependencies()
        lines = [f"{d['desc']} {'✓ 已安装' if d['installed'] else '✗ 未安装'}" for d in deps]
        self.status_label.setText('\n'.join(lines))
        self.install_button.setEnabled(bool(missing_dependencies()) and not self._installing)

    def _start_install(self):
        if self._installing:
            return
        missing = missing_dependencies()
        if not missing:
            return
        self._installing = True
        self.install_button.setEnabled(False)
        self.install_button.setText(og.app.tr('正在安装…'))
        threading.Thread(target=self._install_worker, args=(missing,), daemon=True).start()

    def _install_worker(self, missing):
        ok, detail = install_missing(missing)
        self.install_done.emit(ok, detail)

    def _on_install_done(self, ok, detail):
        self._installing = False
        self.install_button.setText(og.app.tr('安装缺失依赖'))
        self.refresh()
        if ok:
            alert_info(og.app.tr(f'依赖安装完成({detail}),重启后生效'))
        else:
            alert_error(og.app.tr(f'依赖安装失败: {detail}'))
