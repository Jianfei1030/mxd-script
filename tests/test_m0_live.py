import time
import unittest

import numpy as np


def game_running():
    import win32gui
    found = []

    def cb(h, _):
        if (win32gui.IsWindowVisible(h)
                and win32gui.GetClassName(h) == 'UnityWndClass'
                and win32gui.GetWindowText(h) == '冒险岛怀旧服'):
            found.append(h)

    win32gui.EnumWindows(cb, None)
    return bool(found)


@unittest.skipUnless(game_running(), '游戏未运行,跳过 M0 实弹测试')
class TestM0Live(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from scripts.capture_frame import build_capture
        cls.exit_event, cls.win, cls.cap = build_capture()

    @classmethod
    def tearDownClass(cls):
        try:  # 确保不留打开的面板(某轮按键没生效时兜底还原)
            from ok.device.interaction_methods.pydirect import PyDirectInteraction
            inter = PyDirectInteraction(cls.cap, cls.win)
            inter.on_run()
            inter.send_key('esc', 0.05)
        except Exception:
            pass
        cls.exit_event.set()

    def _frame(self):
        frame = self.cap.get_frame()
        self.assertIsNotNone(frame, 'WGC 取帧失败')
        return frame

    @staticmethod
    def _diff(a, b):
        return float(np.abs(a.astype(np.int32) - b.astype(np.int32)).mean())

    def test_wgc_frame_clear(self):
        frame = self._frame()
        self.assertGreaterEqual(frame.shape[0], 768, '帧高度异常')
        self.assertGreater(float(frame.mean()), 5.0, '帧为黑图')

    def test_bar_reading_live(self):
        from src.detect import bars
        frame = self._frame()
        for name, val in [('hp', bars.read_hp(frame)), ('mp', bars.read_mp(frame)),
                          ('exp', bars.read_exp(frame))]:
            self.assertGreaterEqual(val, 0.0, name)
            self.assertLessEqual(val, 1.0, name)

    def test_quickslot_count_ocr_live(self):
        from src.detect import potions
        frame = self._frame()
        # 只验证能读出非负整数,不锁定具体数值(药水会被消耗)
        blue = potions.read_slot_count(frame, 'insert')
        red = potions.read_slot_count(frame, 'home')
        self.assertIsNotNone(blue, '蓝药数量 OCR 失败')
        self.assertIsNotNone(red, '红药数量 OCR 失败')

    def test_postmessage_response(self):
        """判据:面板开合引起**中央 ROI** 帧差显著高于同区域环境基线(3 倍且 >5.0)。
        依次尝试 'i'(道具栏)与 'esc'(系统菜单),任一响应即通过;每个键发两次(开+关还原)。
        全帧比对不可用:面板在 2560x1440 上占比小,训练场 ambient 会淹没信号(假阴性)。
        建议在空频道/安静地图跑。失败先把差异帧存 screenshots/ 供人眼复核,再下降级结论。"""
        import cv2
        from ok.device.interaction_methods.pydirect import PyDirectInteraction
        inter = PyDirectInteraction(self.cap, self.win)

        def roi(f):
            h, w = f.shape[:2]
            return f[int(0.2 * h):int(0.8 * h), int(0.25 * w):int(0.75 * w)]

        responded = False
        f2 = f3 = None
        for key in ('i', 'esc'):
            inter.on_run()  # PyDirect: 尝试把游戏窗口置前台再发真实键
            f1 = self._frame()
            time.sleep(0.8)
            f2 = self._frame()
            ambient = self._diff(roi(f1), roi(f2))   # 同区域环境动画基线
            inter.send_key(key, 0.05)
            time.sleep(0.8)
            f3 = self._frame()
            after = self._diff(roi(f2), roi(f3))
            inter.send_key(key, 0.05)                # 关闭面板,还原状态
            time.sleep(0.5)
            if after > max(3.0 * ambient, 5.0):
                responded = True
                break
        if not responded and f2 is not None:
            cv2.imwrite('screenshots/m0_fail_before.png', f2)
            cv2.imwrite('screenshots/m0_fail_after.png', f3)
        self.assertTrue(responded,
                        'i/esc 中央 ROI 均无响应,PostMessage 疑似被拦截;'
                        '差异帧已存 screenshots/m0_fail_*.png,人眼复核后再定降级')
