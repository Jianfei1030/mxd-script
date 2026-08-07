"""诊断:在标定帧上跑名字牌锚点定位,输出锚点/身体中心坐标(后台运行写日志)。

路径不写死:项目根由本文件位置推导(scripts/ 的上一级),可在任意机器/任意
目录运行(铁律:禁止 hard code 本地路径)。
"""
import sys
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))
os.chdir(ROOT)

LOG = 'logs/anchor_diag.log'

def log(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')

log('start anchor diag')
try:
    import cv2
    from src.detect import anchor
    from src.detect.ocr_engine import get_ocr

    frame = cv2.imread('screenshots/calib_frame.png')
    h, w = frame.shape[:2]
    log(f'frame {w}x{h}')

    get_ocr()  # 预热 OCR
    log('OCR prewarmed')

    name = '端侧大模型'
    region = anchor.search_region(w, h, 0.30, 0.30)
    log(f'search region: {region}')
    hit = anchor.find_in_region(frame, name, region)
    if hit is None:
        log(f'nameplate NOT FOUND for "{name}"')
    else:
        log(f'nameplate FOUND: x={hit.x} y={hit.y} width={hit.width}')
        body = anchor.body_center(hit, 90)
        log(f'body_center (offset=90): ({body[0]}, {body[1]})')
        # 画诊断图:名字牌位置+身体中心
        img = frame.copy()
        cv2.circle(img, (int(hit.x), int(hit.y)), 10, (255, 0, 0), -1)
        cv2.circle(img, (int(body[0]), int(body[1])), 12, (0, 255, 0), -1)
        cv2.imwrite('screenshots/anchor_diag.png', img)
        log('saved screenshots/anchor_diag.png (blue=nameplate, green=body)')
except Exception as e:
    log(f'ERROR {e}')
log('done')
