"""E2E 测试客户端 — 连接 GUI 进程的 TCP 控制服务。

所有 UI 操作通过服务端的 OS 级事件模拟，与真实用户操作完全等价。

用法：
    e2e = E2EClient(port=12345)
    e2e.navigate("start")
    e2e.click("overlay_switch")
    e2e.type_text("task_自动打怪_角色名", "端侧大模型")
    img = e2e.screenshot_game("screenshots/e2e/game.png")
"""
import base64
import io
import json
import os
import socket
import time

from PIL import Image


class E2EClient:
    """E2E 测试客户端。"""

    def __init__(self, port, host='127.0.0.1'):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        self.sock.settimeout(30)
        self._buf = b''

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    # ── 底层通信 ────────────────────────────────────────

    def _send(self, cmd, **args) -> dict:
        """发送一条 JSON 指令并返回结果。"""
        msg = json.dumps({'cmd': cmd, 'args': args}, ensure_ascii=False) + '\n'
        self.sock.sendall(msg.encode('utf-8'))
        return self._recv()

    def _recv(self) -> dict:
        """接收一条 JSON 响应。"""
        while b'\n' not in self._buf:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                raise TimeoutError(f'E2E server response timeout (cmd pending > 30s)') from None
            if not data:
                raise ConnectionError('E2E server connection closed')
            self._buf += data
        line, self._buf = self._buf.split(b'\n', 1)
        return json.loads(line.decode('utf-8'))

    def _ok(self, resp):
        """检查响应是否成功，失败则抛异常。"""
        if not resp.get('ok'):
            raise RuntimeError(f"E2E command failed: {resp.get('error', 'unknown')}")
        return resp

    # ── OS 级 UI 操作 ───────────────────────────────────

    def click(self, name):
        """点击控件（模拟真实鼠标点击）。"""
        return self._ok(self._send('click', name=name))

    def type_text(self, name, text):
        """在控件中输入文字（点击获取焦点 → 清空 → 剪贴板粘贴）。"""
        return self._ok(self._send('type_text', name=name, text=text))

    def press_key(self, key):
        """按单个键（enter/escape/tab/f9 等）。"""
        return self._ok(self._send('press_key', key=key))

    def hotkey(self, *keys):
        """组合键（如 hotkey("ctrl", "a")）。"""
        return self._ok(self._send('hotkey', keys=list(keys)))

    # ── 导航 ────────────────────────────────────────────

    def navigate(self, tab):
        """切换导航 tab（start/triggers/settings/about...）。"""
        return self._ok(self._send('navigate', tab=tab))

    def expand_card(self, task_name):
        """展开 TaskCard。"""
        return self._ok(self._send('expand_card', task_name=task_name))

    # ── 任务控制（幂等：检查状态再操作，避免 toggle 误翻）───

    def start_executor(self):
        """确保 executor 运行中（已运行则 no-op）。"""
        text = self.get_status_bar_text()
        if 'Running' in text:
            return {'ok': True}
        return self._ok(self._send('start_executor'))

    def pause_executor(self):
        """确保 executor 已暂停（已暂停则 no-op）。"""
        text = self.get_status_bar_text()
        if 'Pause' in text or not text.strip():
            return {'ok': True}
        return self._ok(self._send('pause_executor'))

    # ── 配置读写 ────────────────────────────────────────

    def get_config(self, task_name, key=None):
        """读取任务配置。"""
        return self._ok(self._send('get_config', task_name=task_name, key=key))

    def set_config(self, task_name, key, value):
        """写入任务配置（自动持久化 JSON）。"""
        return self._ok(self._send('set_config', task_name=task_name, key=key, value=value))

    # ── 截图 ────────────────────────────────────────────

    def screenshot_game(self, save_path=None) -> Image.Image:
        """WGC 截取游戏窗口（不含 overlay），返回 PIL.Image。"""
        resp = self._ok(self._send('screenshot_game', path=save_path))
        b64 = resp['result']['base64_png']
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        return img

    def screenshot_screen(self, save_path=None, rect=None) -> Image.Image:
        """全屏截图（含 overlay 绘制），返回 PIL.Image。"""
        args = {'path': save_path}
        if rect:
            args['rect'] = rect
        resp = self._ok(self._send('screenshot_screen', **args))
        b64 = resp['result']['base64_png']
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        return img

    # ── 查询 ────────────────────────────────────────────

    def find(self, name) -> dict:
        """查找控件，返回 {exists, type, text, checked, visible, rect}。"""
        resp = self._send('find', name=name)
        return resp

    def get_status_bar_text(self) -> str:
        """读取状态栏文字。"""
        resp = self._ok(self._send('get_status_bar_text'))
        return resp['result']['text']

    # ── 等待（客户端轮询，不阻塞 GUI 主线程）────────────

    def _poll_status(self, keyword, timeout, poll_interval=0.3):
        """客户端轮询状态栏文字，直到包含 keyword 或超时。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.get_status_bar_text()
            if keyword in text:
                return True
            time.sleep(poll_interval)
        return False

    def wait_running(self, timeout=5):
        """等待状态栏显示 'Running'，超时抛 TimeoutError。"""
        if not self._poll_status('Running', timeout):
            raise TimeoutError(f"wait_running: not 'Running' within {timeout}s")

    def wait_paused(self, timeout=5):
        """等待状态栏显示 'Pause' 或清空，超时抛 TimeoutError。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.get_status_bar_text()
            if 'Pause' in text or not text.strip():
                return
            time.sleep(0.3)
        raise TimeoutError(f"wait_paused: not 'Pause' within {timeout}s")

    # ── 断言辅助 ────────────────────────────────────────

    def assert_widget(self, name, checked=None, text=None, visible=None):
        """断言控件状态。"""
        result = self.find(name)
        if not result.get('ok'):
            raise AssertionError(f'widget {name} not found')
        info = result['result']
        if checked is not None and info.get('checked') != checked:
            raise AssertionError(f'{name}: expected checked={checked}, got {info.get("checked")}')
        if text is not None and info.get('text') != text:
            raise AssertionError(f'{name}: expected text={text!r}, got {info.get("text")!r}')
        if visible is not None and info.get('visible') != visible:
            raise AssertionError(f'{name}: expected visible={visible}, got {info.get("visible")}')
        return info
