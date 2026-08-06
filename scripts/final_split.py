"""Final split: assemble the full human-verified dataset for final training.

用法:
    python scripts/final_split.py
    python scripts/final_split.py --train map1 map2 --val map3 --frames 50

逻辑:
    - 来源: dataset/raw/<train 地图> 与 dataset/raw/<val 地图> 中的全部帧
    - 训练集: train 地图全部 → dataset/images/train/ + dataset/labels/train/
    - 验证集: val 地图全部 → dataset/images/val/ + dataset/labels/val/
    - 同名的 .txt 标注文件若存在则复制；不存在则写入空文件（允许负样本）。

约束:
    - 按地图/session 整块切分，不随机混洗。
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
DEFAULT_FRAMES = 50


def ensure_dirs():
    for d in (IMAGES_TRAIN, IMAGES_VAL, LABELS_TRAIN, LABELS_VAL):
        os.makedirs(d, exist_ok=True)


def clear_dirs():
    for d in (IMAGES_TRAIN, IMAGES_VAL, LABELS_TRAIN, LABELS_VAL):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            path = os.path.join(d, name)
            try:
                if os.path.isfile(path) or os.path.islink(path):
                    os.remove(path)
            except OSError as e:
                print(f'WARN: could not remove {path}: {e}')


def copy_map_frames(map_name, frames, images_dst, labels_dst):
    src_dir = os.path.join(RAW_DIR, map_name)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f'Source map folder not found: {src_dir}')

    for i in range(frames):
        fname = f'frame_{i:04d}.png'
        src_img = os.path.join(src_dir, fname)
        if not os.path.exists(src_img):
            raise FileNotFoundError(f'Missing expected frame: {src_img}')

        dst_fname = f'{map_name}_{fname}'
        shutil.copy2(src_img, os.path.join(images_dst, dst_fname))

        src_txt = os.path.join(src_dir, fname.replace('.png', '.txt'))
        dst_txt = os.path.join(labels_dst, dst_fname.replace('.png', '.txt'))
        if os.path.exists(src_txt):
            shutil.copy2(src_txt, dst_txt)
        else:
            open(dst_txt, 'w', encoding='utf-8').close()

    print(f'Copied {frames} frames of {map_name} → {images_dst}')


def main():
    parser = argparse.ArgumentParser(description='Final split (全量 train/val)')
    parser.add_argument('--train', nargs='+', default=DEFAULT_TRAIN_MAPS,
                        help='训练集地图名, 默认 %(default)s')
    parser.add_argument('--val', nargs='+', default=DEFAULT_VAL_MAPS,
                        help='验证集地图名, 默认 %(default)s')
    parser.add_argument('--frames', type=int, default=DEFAULT_FRAMES,
                        help='每地图取前 N 帧, 默认 %(default)s')
    args = parser.parse_args()

    ensure_dirs()
    clear_dirs()
    for m in args.train:
        copy_map_frames(m, args.frames, IMAGES_TRAIN, LABELS_TRAIN)
    for m in args.val:
        copy_map_frames(m, args.frames, IMAGES_VAL, LABELS_VAL)
    print('Final split complete.')


if __name__ == '__main__':
    main()
