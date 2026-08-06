"""Bootstrap split: 把每个地图目录的前 N 帧复制到 train/val 目录。

用法:
    python scripts/bootstrap_split.py
    python scripts/bootstrap_split.py --train map1 map2 --val map3 --frames 10

逻辑:
    - 来源: dataset/raw/<train 地图> 与 dataset/raw/<val 地图> 的前 N 帧
    - 训练集: train 地图的前 N 帧 → dataset/images/train/ + dataset/labels/train/
    - 验证集: val 地图的前 N 帧 → dataset/images/val/ + dataset/labels/val/
    - 同名的 .txt 标注文件若存在则一并复制；不存在则跳过（会在后续标注后补齐）。

约束:
    - 按"地图/session"整块切分，不随机混洗。
    - 仅依赖标准库 + shutil。
"""
import argparse
import os
import shutil

RAW_DIR = 'dataset/raw'
IMAGES_TRAIN = 'dataset/images/train'
IMAGES_VAL = 'dataset/images/val'
LABELS_TRAIN = 'dataset/labels/train'
LABELS_VAL = 'dataset/labels/val'

DEFAULT_TRAIN_MAPS = ['map1', 'map2']
DEFAULT_VAL_MAPS = ['map3']
DEFAULT_FRAMES = 10


def ensure_dirs():
    for d in (IMAGES_TRAIN, IMAGES_VAL, LABELS_TRAIN, LABELS_VAL):
        os.makedirs(d, exist_ok=True)


def copy_map_frames(map_name, frames, images_dst, labels_dst):
    src_dir = os.path.join(RAW_DIR, map_name)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f'Source map folder not found: {src_dir}')

    for i in range(frames):
        fname = f'frame_{i:04d}.png'
        src_img = os.path.join(src_dir, fname)
        if not os.path.exists(src_img):
            raise FileNotFoundError(f'Missing expected frame: {src_img}')

        # Prefix with map name to avoid collisions when multiple maps contribute.
        dst_fname = f'{map_name}_{fname}'
        shutil.copy2(src_img, os.path.join(images_dst, dst_fname))

        src_txt = os.path.join(src_dir, fname.replace('.png', '.txt'))
        dst_txt = os.path.join(labels_dst, dst_fname.replace('.png', '.txt'))
        if os.path.exists(src_txt):
            shutil.copy2(src_txt, dst_txt)
        else:
            # Ensure a placeholder exists so the dataset loader sees the pair.
            open(dst_txt, 'w', encoding='utf-8').close()

    print(f'Copied first {frames} frames of {map_name} → {images_dst}')


def main():
    parser = argparse.ArgumentParser(description='Bootstrap split (train/val 前 N 帧)')
    parser.add_argument('--train', nargs='+', default=DEFAULT_TRAIN_MAPS,
                        help='训练集地图名, 默认 %(default)s')
    parser.add_argument('--val', nargs='+', default=DEFAULT_VAL_MAPS,
                        help='验证集地图名, 默认 %(default)s')
    parser.add_argument('--frames', type=int, default=DEFAULT_FRAMES,
                        help='每地图取前 N 帧, 默认 %(default)s')
    args = parser.parse_args()

    ensure_dirs()
    for m in args.train:
        copy_map_frames(m, args.frames, IMAGES_TRAIN, LABELS_TRAIN)
    for m in args.val:
        copy_map_frames(m, args.frames, IMAGES_VAL, LABELS_VAL)
    print('Bootstrap split complete.')


if __name__ == '__main__':
    main()
