"""Bootstrap split: 把每个地图目录的前 10 帧复制到 train/val 目录。

用法:
    python scripts/bootstrap_split.py

逻辑:
    - 来源: dataset/raw/map1, map2, map3 中的 frame_0000.png .. frame_0009.png
    - 训练集: map1 + map2 的前 10 帧 → dataset/images/train/ + dataset/labels/train/
    - 验证集: map3 的前 10 帧 → dataset/images/val/ + dataset/labels/val/
    - 同名的 .txt 标注文件若存在则一并复制；不存在则跳过（会在后续标注后补齐）。

约束:
    - 按"地图/session"整块切分，不随机混洗。
    - 仅依赖标准库 + shutil，使用嵌入式 python 运行。
"""
import os
import shutil

RAW_DIR = 'dataset/raw'
IMAGES_TRAIN = 'dataset/images/train'
IMAGES_VAL = 'dataset/images/val'
LABELS_TRAIN = 'dataset/labels/train'
LABELS_VAL = 'dataset/labels/val'

TRAIN_MAPS = ['map1', 'map2']
VAL_MAPS = ['map3']


def ensure_dirs():
    for d in (IMAGES_TRAIN, IMAGES_VAL, LABELS_TRAIN, LABELS_VAL):
        os.makedirs(d, exist_ok=True)


def copy_map_frames(map_name, images_dst, labels_dst):
    src_dir = os.path.join(RAW_DIR, map_name)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f'Source map folder not found: {src_dir}')

    for i in range(10):
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

    print(f'Copied first 10 frames of {map_name} → {images_dst}')


def main():
    ensure_dirs()
    for m in TRAIN_MAPS:
        copy_map_frames(m, IMAGES_TRAIN, LABELS_TRAIN)
    for m in VAL_MAPS:
        copy_map_frames(m, IMAGES_VAL, LABELS_VAL)
    print('Bootstrap split complete.')


if __name__ == '__main__':
    main()
