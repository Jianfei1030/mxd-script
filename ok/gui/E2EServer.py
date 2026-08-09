"""E2E TCP 控制服务 — 在 GUI 进程内启动。

绑定 127.0.0.1:0（随机端口），启动后向 stdout 打印 E2E_SERVER_PORT=<port>。
外部测试脚本通过 TCP 连接发送 JSON 指令。
"""
import json
import logging
import socket
import threading

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class E2EServer:
    """单客户端 TCP JSON-RPC 服务。"""

    def __init__(self, main_window, app):
        from ok.gui.E2ECommandHandler import E2ECommandHandler
        self.handler = E2ECommandHandler(main_window, app)
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('127.0.0.1', 0))
        self.port = self.server.getsockname()[1]
        self.server.listen(1)
        self._running = True

        # 启动后台线程接受连接
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name='E2EServer')
        self._thread.start()

        # 打印端口供外部脚本连接
        print(f'E2E_SERVER_PORT={self.port}', flush=True)
        logger.info(f'E2E server listening on 127.0.0.1:{self.port}')

    def _accept_loop(self):
        """接受连接循环。"""
        while self._running:
            try:
                self.server.settimeout(1.0)
                try:
                    conn, addr = self.server.accept()
                except socket.timeout:
                    continue
                logger.info(f'E2E client connected from {addr}')
                self._handle_client(conn)
            except Exception as e:
                if self._running:
                    logger.error(f'E2E accept error: {e}')

    def _handle_client(self, conn):
        """处理单个客户端连接（阻塞直到断开）。"""
        buf = b''
        try:
            conn.settimeout(60)
            while self._running:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    if not line.strip():
                        continue
                    response = self._dispatch_on_main(line.decode('utf-8', errors='replace'))
                    resp_bytes = json.dumps(response, ensure_ascii=False) + '\n'
                    conn.sendall(resp_bytes.encode('utf-8'))
        except (ConnectionResetError, BrokenPipeError):
            pass
        except socket.timeout:
            logger.warning('E2E client timed out, closing connection')
        except Exception as e:
            logger.error(f'E2E client handler error: {e}')
        finally:
            conn.close()
            logger.info('E2E client disconnected')

    def _dispatch_on_main(self, raw):
        """将指令分发到主线程执行（Qt 操作必须在主线程）。

        通过 QTimer.singleShot 把执行体调度到 GUI 主线程，再用
        threading.Event 阻塞等待结果，返回后由服务线程写回 socket。
        """
        result_box = [None]
        done = threading.Event()

        def _run():
            try:
                result_box[0] = self._dispatch(raw)
            except Exception as e:
                logger.error(f'E2E command dispatch error: {e}', exc_info=True)
                result_box[0] = {'ok': False, 'error': str(e)}
            finally:
                done.set()

        QTimer.singleShot(0, _run)
        done.wait(timeout=30)
        if not done.is_set():
            return {'ok': False, 'error': 'E2E command timed out on main thread'}
        return result_box[0]

    def _dispatch(self, raw):
        """解析并执行一条 JSON 指令。"""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            return {'ok': False, 'error': f'invalid JSON: {e}'}

        cmd = msg.get('cmd')
        args = msg.get('args', {})

        try:
            return self._execute(cmd, args)
        except Exception as e:
            logger.error(f'E2E command {cmd} error: {e}', exc_info=True)
            return {'ok': False, 'error': str(e)}

    def _execute(self, cmd, args):
        """分发指令到 handler。"""
        h = self.handler

        if cmd == 'ping':
            return {'ok': True}

        elif cmd == 'find':
            _, info = h.find_widget(args['name'])
            return {'ok': info.get('exists', False), 'result': info}

        elif cmd == 'click':
            return h.os_click(args['name'])

        elif cmd == 'type_text':
            return h.os_type_text(args['name'], args['text'])

        elif cmd == 'press_key':
            return h.os_press_key(args['key'])

        elif cmd == 'hotkey':
            return h.os_hotkey(args['keys'])

        elif cmd == 'navigate':
            return h.navigate(args['tab'])

        elif cmd == 'expand_card':
            return h.expand_card(args['task_name'])

        elif cmd == 'get_config':
            return h.get_config(args['task_name'], args.get('key'))

        elif cmd == 'set_config':
            return h.set_config(args['task_name'], args['key'], args['value'])

        elif cmd == 'start_executor':
            return h.start_executor()

        elif cmd == 'pause_executor':
            return h.pause_executor()

        elif cmd == 'screenshot_game':
            return h.screenshot_game(args.get('path'))

        elif cmd == 'screenshot_screen':
            return h.screenshot_screen(args.get('path'), args.get('rect'))

        elif cmd == 'get_status_bar_text':
            return h.get_status_bar_text()

        else:
            return {'ok': False, 'error': f'unknown command: {cmd}'}

    def stop(self):
        """停止服务。"""
        self._running = False
        try:
            self.server.close()
        except Exception:
            pass
