"""dbs3 切分:train 全部 100 帧,val 后 10 帧(单地图切分法,AGENTS.md §2.0)"""
import os
import shutil

SRC = 'dataset/raw/dong_bu_yan_shan_3'
VAL = 'dataset/raw/dbs3_val'

if os.path.exists(VAL):
    shutil.rmtree(VAL)
os.makedirs(VAL)

frames = sorted(f for f in os.listdir(SRC) if f.endswith('.png'))
val_frames = frames[-10:]
for i, f in enumerate(val_frames):
    dst = f'frame_{i:04d}.png'
    shutil.copy2(os.path.join(SRC, f), os.path.join(VAL, dst))
    t = f.replace('.png', '.txt')
    if os.path.exists(os.path.join(SRC, t)):
        shutil.copy2(os.path.join(SRC, t), os.path.join(VAL, dst.replace('.png', '.txt')))
    else:
        open(os.path.join(VAL, dst.replace('.png', '.txt')), 'w').close()

print(f'train: {len(frames)} 帧 (全部 dbs3)')
print(f'val: {len(val_frames)} 帧 (后10帧, 复制到 dbs3_val)')
