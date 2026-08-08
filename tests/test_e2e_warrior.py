"""WarriorDebugTask E2E 测试。

所有 UI 操作通过 OS 级输入事件模拟，与真实用户操作完全等价。

前置条件：
- 冒险岛客户端正在运行（窗口标题'冒险岛怀旧服'）
- 角色在游戏中（非登录/选角界面）

运行方式：
1. 终端1: .venv-warrior/Scripts/python.exe main_debug.py --e2e
   (stdout 输出: E2E_SERVER_PORT=xxxxx)
2. 终端2: $env:E2E_PORT="xxxxx"; .venv-warrior/Scripts/python.exe -m pytest tests/test_e2e_warrior.py -v
"""
import os
import time
import unittest

# 允许通过环境变量指定端口
E2E_PORT = int(os.environ.get('E2E_PORT', 0))


def _has_e2e_server():
    """检查 E2E 服务端口是否可用。"""
    if E2E_PORT <= 0:
        return False
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(('127.0.0.1', E2E_PORT))
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


@unittest.skipUnless(_has_e2e_server(), 'E2E server not running (set E2E_PORT env var)')
class TestE2EWarriorDebug(unittest.TestCase):
    """WarriorDebugTask E2E 测试。"""

    TASK_NAME = '战士调试'

    @classmethod
    def setUpClass(cls):
        from scripts._e2e_client import E2EClient
        cls.e2e = E2EClient(E2E_PORT)
        cls.evidence_dir = 'screenshots/e2e/warrior_debug'
        os.makedirs(cls.evidence_dir, exist_ok=True)
        # 备份用户配置，避免测试污染；tearDownClass 恢复
        resp = cls.e2e.get_config(cls.TASK_NAME)
        cls._config_backup = dict(resp['result'])
        # 备份 overlay 开关状态
        cls._overlay_backup = cls.e2e.find('overlay_switch')['result'].get('checked', False)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.e2e.pause_executor()
        except Exception:
            pass
        # 恢复用户配置
        try:
            for key, value in cls._config_backup.items():
                cls.e2e.set_config(cls.TASK_NAME, key, value)
        except Exception:
            pass
        # 恢复 overlay 开关状态
        try:
            cls.e2e.navigate('start')
            current = cls.e2e.find('overlay_switch')['result'].get('checked', False)
            if current != cls._overlay_backup:
                cls.e2e.click('overlay_switch')
        except Exception:
            pass
        cls.e2e.close()

    def test_01_ping(self):
        """E2E 服务健康检查。"""
        resp = self.e2e._send('ping')
        self.assertTrue(resp['ok'])

    def _ensure_checked(self, name):
        """确保开关为开启状态：查询，未开启才点击（避免 toggle 误关）。"""
        info = self.e2e.find(name)['result']
        if not info.get('checked', False):
            self.e2e.click(name)

    def test_02_overlay_toggle(self):
        """点击 overlay 开关 → 查询状态确认已开启。"""
        self.e2e.navigate('start')
        self._ensure_checked('overlay_switch')
        result = self.e2e.find('overlay_switch')
        self.assertTrue(result['result']['checked'])

    def test_03_find_widgets(self):
        """查找 StartTab 上的固定控件。"""
        self.e2e.navigate('start')
        for name in ['start_button', 'refresh_button', 'capture_button',
                      'overlay_switch', 'device_list']:
            result = self.e2e.find(name)
            self.assertTrue(result['result']['exists'], f'{name} should exist')

    def test_04_warrior_config_rw(self):
        """展开战士调试卡片 → 读写配置。"""
        self.e2e.navigate('triggers')
        self.e2e.expand_card(self.TASK_NAME)
        # 读取当前值并保持原值
        cfg = self.e2e.get_config(self.TASK_NAME)
        orig_width = cfg['result']['玩家宽']
        # 写入
        self.e2e.set_config(self.TASK_NAME, '玩家宽', orig_width + 1)
        cfg2 = self.e2e.get_config(self.TASK_NAME)
        self.assertEqual(cfg2['result']['玩家宽'], orig_width + 1)
        # 恢复
        self.e2e.set_config(self.TASK_NAME, '玩家宽', orig_width)

    def test_05_type_character_name(self):
        """在角色名输入框中键入中文 → 查询确认。"""
        self.e2e.navigate('triggers')
        self.e2e.expand_card(self.TASK_NAME)
        cfg = self.e2e.get_config(self.TASK_NAME)
        orig_name = cfg['result']['角色名']
        self.e2e.type_text('task_战士调试_角色名', '端侧大模型')
        result = self.e2e.find('task_战士调试_角色名')
        self.assertEqual(result['result']['text'], '端侧大模型')
        # 恢复原角色名
        if orig_name != '端侧大模型':
            self.e2e.type_text('task_战士调试_角色名', orig_name)

    def test_06_start_and_running(self):
        """点击调试开关 → 填角色名 → 点击 Start → 等待 Running。"""
        self.e2e.navigate('start')
        self._ensure_checked('overlay_switch')
        self.e2e.navigate('triggers')
        self.e2e.expand_card(self.TASK_NAME)
        self._ensure_checked('task_战士调试_调试开关')
        self.e2e.type_text('task_战士调试_角色名', '端侧大模型')
        self._ensure_checked('task_战士调试_enable')
        self.e2e.start_executor()
        self.e2e.wait_running(timeout=5)
        # 暂停，避免影响后续用例（start_button 是 toggle，running 时再点会暂停）
        self.e2e.pause_executor()

    def test_07_game_screenshot(self):
        """游戏窗口截图应非空且尺寸合理（WGC 抓帧）。"""
        img = self.e2e.screenshot_game(save_path=f'{self.evidence_dir}/game_frame.png')
        self.assertIsNotNone(img)
        self.assertGreater(img.width, 800)
        self.assertGreater(img.height, 600)

    def test_08_screen_screenshot(self):
        """全屏截图应包含 overlay 绘制。"""
        time.sleep(1)
        img = self.e2e.screenshot_screen(save_path=f'{self.evidence_dir}/screen_with_overlay.png')
        self.assertIsNotNone(img)
        self.assertGreater(img.width, 800)

    def test_09_full_warrior_flow(self):
        """完整流程：overlay → config → start → 截图 → pause。"""
        # 1. 确保 overlay 开启
        self.e2e.navigate('start')
        self._ensure_checked('overlay_switch')

        # 2. 配置任务
        self.e2e.navigate('triggers')
        self.e2e.expand_card(self.TASK_NAME)
        self._ensure_checked('task_战士调试_调试开关')
        self.e2e.type_text('task_战士调试_角色名', '端侧大模型')
        self._ensure_checked('task_战士调试_enable')

        # 3. 启动
        self.e2e.start_executor()
        self.e2e.wait_running(timeout=5)

        # 4. 等待检测稳定
        time.sleep(2)

        # 5. 游戏窗口截图（WGC，不含 overlay）
        game_img = self.e2e.screenshot_game(
            save_path=f'{self.evidence_dir}/full_flow_game.png')
        self.assertGreater(game_img.width, 800)

        # 6. 全屏截图（含 overlay 框线）
        screen_img = self.e2e.screenshot_screen(
            save_path=f'{self.evidence_dir}/full_flow_screen.png')
        self.assertIsNotNone(screen_img)

        # 7. 停止
        self.e2e.pause_executor()



if __name__ == '__main__':
    unittest.main()
