"""E2E 一次性检查:战士调试画框新增的两个虚线框(蓝=名字搜索区,青=寻怪同层带)。
用法: python scripts/_e2e_boxes_check.py <port>"""
import sys
import time

from _e2e_client import E2EClient

port = int(sys.argv[1])
e2e = E2EClient(port)
print('ping:', e2e._send('ping'))

# 1. 开「启用标记框」
e2e.navigate('start')
r = e2e.find('overlay_switch')
print('overlay_switch:', r.get('result', {}).get('checked'))
if not r['result'].get('checked'):
    e2e.click('overlay_switch')
    time.sleep(0.5)

# 2. 战士调试:展开卡片,确保任务启用(角色名/调试开关已在 config 文件)
e2e.navigate('triggers')
e2e.expand_card('战士调试')
r = e2e.find('task_战士调试_enable')
print('task_enable:', r.get('result', {}).get('checked'))
if not r['result'].get('checked'):
    e2e.click('task_战士调试_enable')
    time.sleep(0.3)

# 3. 启动 executor
e2e.start_executor()
e2e.wait_running(timeout=5)
time.sleep(3)

# 4. 截图留证
e2e.screenshot_game('screenshots/e2e/boxes/game_frame.png')
e2e.screenshot_screen('screenshots/e2e/boxes/screen_overlay.png')
print('screenshots saved')

# 5. 清理
e2e.pause_executor()
e2e.close()
print('DONE')
