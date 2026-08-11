"""东部岩山6 双类数据切分:train 90% + val 10%(时序不重叠)。"""
import os
import shutil
import glob
import collections

raw = 'dataset/raw/dong_bu_yan_shan_6'
for sub in ['images/train', 'images/val', 'labels/train', 'labels/val']:
    d = f'dataset/{sub}'
    os.makedirs(d, exist_ok=True)
    for name in os.listdir(d):
        os.remove(os.path.join(d, name))

frames = sorted(glob.glob(raw + '/frame_*.png'))
split = int(len(frames) * 0.9)
for i, f in enumerate(frames):
    stem = os.path.basename(f).replace('.png', '')
    dst = 'train' if i < split else 'val'
    shutil.copy2(f, f'dataset/images/{dst}/dbs6_{stem}.png')
    txt = f.replace('.png', '.txt')
    shutil.copy2(txt, f'dataset/labels/{dst}/dbs6_{stem}.txt')

print('train:', len(os.listdir('dataset/images/train')),
      'val:', len(os.listdir('dataset/images/val')))
c = collections.Counter()
for t in glob.glob('dataset/labels/val/*.txt'):
    for line in open(t):
        p = line.split()
        if len(p) >= 5:
            c[p[0]] += 1
print('val 类别分布:', dict(c))
