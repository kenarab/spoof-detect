import os
import time
import math
import random
import csv

from io import BytesIO
import numpy as np
from cairosvg import svg2png
import cv2

import filetype
from filetype.match import image_matchers

import imgaug as ia
from imgaug import augmenters as iaa
from imgaug.augmentables.batches import UnnormalizedBatch

from entity import Entity
from common import defaults, mkdir
import imtool
import pipelines

BATCH_SIZE = 16

mkdir.make_dirs([defaults.AUGMENTED_IMAGES_PATH, defaults.AUGMENTED_LABELS_PATH])

logo_images = []
logo_alphas = []
logo_labels = {}

db = {}
with open(defaults.MAIN_CSV_PATH, 'r') as f:
    reader = csv.DictReader(f)
    db = {e.bco: e for e in [Entity.from_dict(d) for d in reader]}

background_images = [d for d in os.scandir(defaults.IMAGES_PATH)]

stats = {
    'failed': 0,
    'ok': 0
}

for d in os.scandir(defaults.LOGOS_DATA_PATH):
    img = None
    if not d.is_file():
        stats['failed'] += 1
        continue

    try:
        if filetype.match(d.path, matchers=image_matchers):
            img = cv2.imread(d.path, cv2.IMREAD_UNCHANGED)
        else:
            png = svg2png(url=d.path)
            img = cv2.imdecode(np.asarray(bytearray(png), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        label = db[d.name.split('.')[0]].id

        (h, w, c) = img.shape
        if c == 3:
            img = imtool.add_alpha(img)

        if img.ndim < 3:
            print(f'very bad dim: {img.ndim}')

        img = imtool.remove_white(img)
        (h, w, c) = img.shape

        assert(w > 10)
        assert(h > 10)

        stats['ok'] += 1

        (b, g, r, _) = cv2.split(img)
        alpha = img[:, :, 3]/255
        d = cv2.merge([b, g, r])

        logo_images.append(d)
        # tried id() tried __array_interface__, tried tagging, nothing works
        logo_labels.update({d.tobytes(): label})

        # XXX(xaiki): we pass alpha as a float32 heatmap,
        # because imgaug is pretty strict about what data it will process
        # and that we want the alpha layer to pass the same transformations as the orig
        logo_alphas.append(np.dstack((alpha, alpha, alpha)).astype('float32'))

    except Exception as e:
        stats['failed'] += 1
        print(f'error loading: {d.path}: {e}')

print(stats)
batches = [UnnormalizedBatch(images=logo_images[i:i+BATCH_SIZE],heatmaps=logo_alphas[i:i+BATCH_SIZE])
           for i in range(math.floor(len(logo_images)/BATCH_SIZE))]

# We use a single, very fast augmenter here to show that batches
# are only loaded once there is space again in the buffer.
pipeline = pipelines.HUGE

def create_generator(lst):
    for b in lst:
        print(f"Loading next unaugmented batch...")
        yield b

batches_generator = create_generator(batches)

with pipeline.pool(processes=-1, seed=1) as pool:
    batches_aug = pool.imap_batches(batches_generator, output_buffer_size=5)

    print(f"Requesting next augmented batch...")
    for i, batch_aug in enumerate(batches_aug):
        idx = list(range(len(batch_aug.images_aug)))
        random.shuffle(idx)
        for j, d in enumerate(background_images):
            img = imtool.remove_white(cv2.imread(d.path))
            basename = d.name.replace('.png', '') + f'.{i}.{j}'

            anotations = []
            for k in range(math.floor(len(batch_aug.images_aug)/3)):
                logo_idx = (j+k*4)%len(batch_aug.images_aug)

                orig = batch_aug.images_unaug[logo_idx]
                label = logo_labels[orig.tobytes()]
                logo = batch_aug.images_aug[logo_idx]

                # XXX(xaiki): we get alpha from heatmap, but will only use one channel
                # we could make mix_alpha into mix_mask and pass all 3 chanels
                alpha = cv2.split(batch_aug.heatmaps_aug[logo_idx])
                try:
                    img, bb, (w, h) = imtool.mix_alpha(img, logo, alpha[0], random.random(), random.random())
                    c = bb.to_centroid((h, w, 1))
                    anotations.append(c.to_anotation(label))
                except AssertionError as e:
                    print(f'couldnt process {i}, {j}: {e}')

            try:
                cv2.imwrite(f'{defaults.AUGMENTED_IMAGES_PATH}/{basename}.png', img)
                label_path = f"{defaults.AUGMENTED_LABELS_PATH}/{basename}.txt"
                with open(label_path, 'a') as f:
                    f.write('\n'.join(anotations))
            except Exception:
                print(f'couldnt write image {basename}')

        if i < len(batches)-1:
            print("Requesting next augmented batch...")

