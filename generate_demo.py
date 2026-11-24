"""Generate a reproducible, wholly synthetic maize-lodging example."""

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFilter
from rasterio.transform import from_origin

from pipeline import convert

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT, TILE = 960, 640, 160


def make_data(folder):
    tiles = folder / 'masks'
    tiles.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(3128)
    y, x = np.mgrid[:HEIGHT, :WIDTH]
    coarse = Image.fromarray(rng.integers(0, 255, (37, 56), dtype=np.uint8))
    light = (np.asarray(coarse.resize((WIDTH, HEIGHT), Image.Resampling.BICUBIC)).astype(float) - 128) / 12
    grain = rng.normal(0, 2.8, x.shape)
    canvas = np.array([88, 97, 66], dtype=float) + (light + grain)[..., None]
    field_index = np.zeros(x.shape, dtype=np.uint8)
    fields = [
        ([(0, 0), (294, 0), (346, 245), (0, 320)], (76, 111, 58), 0.23, 5.0),
        ([(309, 0), (626, 0), (679, 174), (358, 242)], (112, 113, 73), 0.21, 4.2),
        ([(644, 0), (960, 0), (960, 112), (695, 169)], (81, 108, 64), -0.17, 5.8),
        ([(0, 340), (353, 265), (392, 437), (0, 507)], (79, 120, 62), 0.23, 5.6),
        ([(369, 262), (681, 193), (742, 376), (405, 434)], (91, 119, 63), 0.24, 4.9),
        ([(699, 188), (960, 132), (960, 337), (758, 373)], (104, 125, 63), 0.20, 5.4),
        ([(0, 528), (398, 454), (438, 640), (0, 640)], (99, 113, 66), 0.19, 4.5),
        ([(414, 451), (748, 392), (827, 640), (454, 640)], (75, 108, 60), 0.17, 5.1),
        ([(765, 388), (960, 356), (960, 640), (845, 640)], (118, 118, 77), 0.20, 4.8),
    ]
    ground = Image.new('L', (WIDTH, HEIGHT))
    roads = ImageDraw.Draw(ground)
    for route in [[(-12, 329), (960, 120)], [(-12, 520), (960, 347)], [(302, -12), (447, 650)], [(635, -12), (837, 650)]]:
        roads.line(route, fill=255, width=9)
    road_mask = np.asarray(ground) > 0
    canvas[road_mask] = np.array([143, 131, 101]) + (grain[road_mask] * 0.8 + light[road_mask])[..., None]
    for index, (vertices, tone, slope, period) in enumerate(fields, 1):
        selector = Image.new('L', (WIDTH, HEIGHT))
        ImageDraw.Draw(selector).polygon(vertices, fill=255)
        field = np.asarray(selector) > 0
        phase = (y + slope * x + .24 * np.sin(x / 74)) * 2 * np.pi / period
        rows = np.cos(phase) * 11 + np.sin(2 * phase) * 3
        contour = np.sin(x / 71 + y / 47 + index) * 3
        variation = rows + 1.3 * light + grain + contour
        canvas[field] = np.array(tone) + variation[field, None] * np.array([.85, 1.15, .68])
        field_index[field] = index

    mask = Image.new('L', (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(mask)
    for cx, cy, rx, ry, value in [
        (172, 135, 78, 46, 1), (481, 104, 67, 34, 1), (791, 77, 29, 19, 2),
        (486, 314, 98, 46, 2), (528, 317, 42, 25, 3), (645, 298, 33, 39, 1),
        (847, 258, 81, 42, 1), (851, 256, 47, 25, 2), (868, 245, 20, 15, 3),
        (169, 375, 53, 29, 2), (264, 391, 52, 23, 1), (269, 535, 62, 36, 1),
        (614, 481, 81, 52, 2), (613, 487, 46, 28, 3), (723, 571, 44, 23, 1),
        (910, 493, 34, 55, 2), (913, 507, 23, 22, 3), (116, 594, 25, 17, 1),
    ]:
        angles = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        radius = 1 + .13 * np.sin(3 * angles + cx) + .08 * np.cos(7 * angles + cy) + rng.normal(0, .035, len(angles))
        points = [(cx + rx * r * np.cos(t), cy + ry * r * np.sin(t) - .22 * rx * r * np.cos(t))
                  for t, r in zip(angles, radius)]
        draw.polygon(points, fill=value)
    # A hole and explicit salt noise make boundary and filtering checks visible.
    draw.ellipse((605, 478, 624, 490), fill=0)
    mask_array = np.asarray(mask).copy()
    mask_array[field_index == 0] = 0
    field_signal = Image.fromarray((mask_array > 0).astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(4))
    signal = np.asarray(field_signal).astype(float) / 255
    canvas += signal[..., None] * np.array([13, 4, 4])
    for _ in range(154):
        cx, cy = rng.integers((4, 4), (WIDTH - 4, HEIGHT - 4))
        side = rng.integers(1, 5)
        fragment = mask_array[cy:cy + side, cx:cx + side]
        if field_index[cy, cx] and not fragment.any():
            fragment[:] = rng.integers(1, 4)

    with rasterio.open(folder / 'reference.tif', 'w', driver='GTiff', width=WIDTH, height=HEIGHT,
                       count=3, dtype='uint8', crs='EPSG:32650', transform=from_origin(492860, 3921420, .5, .5),
                       photometric='RGB', compress='deflate') as target:
        target.write(np.moveaxis(canvas.clip(0, 255).astype(np.uint8), -1, 0))
    positions = ['filename,x,y']
    for row in range(0, HEIGHT, TILE):
        for col in range(0, WIDTH, TILE):
            name = f'mask_x{col:04d}_y{row:04d}.png'
            positions.append(f'{name},{col},{row}')
            Image.fromarray(mask_array[row:row + TILE, col:col + TILE]).save(tiles / name)
    (folder / 'tiles.csv').write_text('\n'.join(positions) + '\n', encoding='utf-8-sig')
    (folder / 'classes.csv').write_text('value,name,color\n1,轻度倒伏,#FFB35F\n2,中度倒伏,#EC6E76\n3,重度倒伏,#72D7D1\n',
                                       encoding='utf-8-sig')


def run_demo(root, destination, threshold=10, background=0):
    with ExitStack() as stack:
        files = [(p.relative_to(root).as_posix(), stack.enter_context(p.open('rb')))
                 for p in sorted(root.glob('**/*')) if p.is_file()]
        return convert(files, destination, threshold, background, demo=True)


if __name__ == '__main__':
    source = ROOT / 'demo_data'
    output = ROOT / 'demo_results'
    (source / 'masks').mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=ROOT, prefix='.demo-build-') as folder:
        work = Path(folder)
        staged_source, staged_output = work / 'data', work / 'results'
        staged_output.mkdir()
        make_data(staged_source)
        result = run_demo(staged_source, staged_output)
        for file in staged_source.rglob('*'):
            if file.is_file():
                file.replace(source / file.relative_to(staged_source))
        for file in staged_output.iterdir():
            file.replace(output / file.name)
    print(f'已生成 {result["tiles"]} 张切片及演示成果，保留 {result["kept"]} 个斑块。')
