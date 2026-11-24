"""Restore class masks to the reference pixel grid and export GIS products."""

import csv
import io
import json
import math
import re
from collections import Counter
from pathlib import PurePosixPath

import numpy as np
import rasterio
from PIL import Image
from pyproj import CRS, Transformer
from rasterio.features import rasterize, shapes
from shapely import make_valid
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import transform as project_geometry

from products import write_products

PALETTE = ('#ffb35f', '#ec6e76', '#72d7d1', '#a99aee', '#e3dc7c', '#64a8ff',
           '#c8dc91', '#f79aca', '#b0a18e', '#9cd4ff', '#fb876d', '#f3ccae')
MASK_EXTENSIONS = {'.png', '.bmp', '.tif', '.tiff'}
TILE_PATTERN = re.compile(r'(?:^|[_-])x(\d+)[_-]y(\d+)(?:$|[_-])', re.I)
MAX_PIXELS = 20_000_000
SQUARE_METRES_PER_MU = 2000 / 3


def file_name(path):
    return PurePosixPath(path.replace('\\', '/')).name


def read_table(stream):
    try:
        content = stream.read(1_000_001)
        if len(content) > 1_000_000:
            raise ValueError('CSV 配置不能超过 1 MB。')
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        return set(reader.fieldnames or ()), list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError('CSV 配置请使用 UTF-8 编码。') from exc


def collect_inputs(files):
    entries = [(path, file_name(path), stream) for path, stream in files]
    optional = {}
    for _, name, stream in entries:
        if name.lower() in {'tiles.csv', 'classes.csv'}:
            if name.lower() in optional:
                raise ValueError(f'发现多份 {name}，请各保留一份。')
            optional[name.lower()] = stream

    tiffs = [entry for entry in entries if PurePosixPath(entry[1]).suffix.lower() in {'.tif', '.tiff'}]
    designated = [entry for entry in tiffs if PurePosixPath(entry[1]).stem.lower() == 'reference']
    candidates = designated or tiffs
    if len(candidates) != 1:
        raise ValueError('请选择包含一张参考 GeoTIFF 的文件夹。若有多张 TIFF，将参考图命名为 reference.tif。')
    reference = candidates[0]
    masks = {}
    for entry in entries:
        _, name, stream = entry
        if entry is reference or PurePosixPath(name).suffix.lower() not in MASK_EXTENSIONS:
            continue
        if name in masks:
            raise ValueError(f'掩膜文件名重复：{name}')
        masks[name] = stream
    if not masks:
        raise ValueError('没有找到掩膜。请在参考图之外放入 PNG、BMP 或单波段 TIFF 掩膜。')
    return reference[1:], masks, optional


def read_positions(stream, masks):
    columns, rows = read_table(stream)
    if not {'filename', 'x', 'y'} <= columns:
        raise ValueError('tiles.csv 必须包含 filename、x、y 三列。')
    positions = {}
    for record in rows:
        name = file_name((record['filename'] or '').strip())
        try:
            x, y = int(record['x']), int(record['y'])
        except (TypeError, ValueError) as exc:
            raise ValueError(f'tiles.csv 中的像素偏移必须为整数：{name}') from exc
        if name in positions or name not in masks or min(x, y) < 0:
            raise ValueError(f'tiles.csv 含有重复、未知文件或负偏移：{name}')
        positions[name] = (x, y)
    if set(positions) != set(masks):
        raise ValueError('tiles.csv 必须覆盖文件夹中的所有掩膜。')
    return positions


def read_classes(stream):
    if stream is None:
        return {}
    columns, rows = read_table(stream)
    if not {'value', 'name'} <= columns:
        raise ValueError('classes.csv 必须包含 value、name 两列，color 可选。')
    labels = {}
    for record in rows:
        try:
            value = int(record['value'])
        except (TypeError, ValueError) as exc:
            raise ValueError('classes.csv 的 value 必须为整数。') from exc
        name = (record['name'] or '').strip()
        color = (record.get('color') or '').strip()
        if (not 0 <= value <= 65535 or not name or len(name) > 30 or value in labels
                or any(ord(char) < 32 for char in name) or (color and not re.fullmatch(r'#[0-9a-fA-F]{6}', color))):
            raise ValueError(f'classes.csv 含有无效或重复的类别：{value}')
        labels[value] = (name, color)
    return labels


def stitch_masks(masks, positions, width, height):
    mosaic = np.zeros((height, width), dtype=np.uint16)
    covered = np.zeros((height, width), dtype=bool)
    for name, stream in sorted(masks.items()):
        try:
            with Image.open(stream) as image:
                tw, th = image.size
                if tw > width or th > height:
                    raise ValueError(f'掩膜尺寸超过参考图：{name}')
                if image.mode not in {'1', 'L', 'P', 'I', 'I;16', 'I;16L', 'I;16B'}:
                    raise ValueError(f'请使用灰度类别值或索引色 PNG 掩膜：{name}')
                tile = np.asarray(image)
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError(f'无法读取掩膜：{name}') from exc
        if tile.min() < 0 or tile.max() > 65535:
            raise ValueError(f'掩膜类别值须在 0 至 65535 之间：{name}')
        match = TILE_PATTERN.search(PurePosixPath(name).stem)
        if positions is not None:
            x, y = positions[name]
        elif match:
            x, y = map(int, match.groups())
        elif len(masks) == 1 and (tw, th) == (width, height):
            x, y = 0, 0
        else:
            raise ValueError(f'无法定位切片 {name}。请按 mask_x0_y0.png 命名，或提供 tiles.csv。')
        if x + tw > width or y + th > height:
            raise ValueError(f'掩膜越出参考图边界：{name}，左上角（{x}, {y}）。')
        region = np.s_[y:y + th, x:x + tw]
        overlap = covered[region]
        if np.any(overlap & (mosaic[region] != tile)):
            raise ValueError(f'切片重叠区的类别值不一致：{name}。请先统一重叠区或裁掉重叠。')
        mosaic[region] = tile
        covered[region] = True
    missing = covered.size - np.count_nonzero(covered)
    if missing:
        raise ValueError(f'切片缺失或偏移有误，有 {missing:,} 个像元未覆盖。')
    return mosaic


def reference_preview(source):
    factor = min(1, 1400 / max(source.width, source.height))
    size = (max(1, round(source.height * factor)), max(1, round(source.width * factor)))
    interpretations = [member.name for member in source.colorinterp]
    if all(band in interpretations for band in ('red', 'green', 'blue')):
        indexes = [interpretations.index(band) + 1 for band in ('red', 'green', 'blue')]
    else:
        indexes = [1, 2, 3] if source.count >= 3 else [1]
    bands = source.read(indexes, out_shape=(len(indexes), *size), masked=True,
                        resampling=rasterio.enums.Resampling.bilinear)
    rgb = []
    for band in bands:
        if band.dtype == np.uint8:
            rgb.append(band.filled(0))
            continue
        valid = band.compressed()
        valid = valid[np.isfinite(valid)]
        low, high = np.percentile(valid, [2, 98]) if valid.size else (0, 1)
        scaled = (band.astype('float64').filled(low) - low) / (high - low if high > low else 1)
        rgb.append((np.nan_to_num(scaled).clip(0, 1) * 255).astype('uint8'))
    return Image.fromarray(np.dstack(rgb if len(rgb) == 3 else rgb * 3))


def polygon_parts(geometry):
    if geometry.geom_type == 'Polygon' and not geometry.is_empty:
        yield orient(geometry, sign=1)
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from polygon_parts(part)


def vectorize(mosaic, crs, affine, background, threshold, stats):
    geographic = crs.geodetic_crs
    transform_to_wgs84 = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True).transform
    transform_to_lonlat = Transformer.from_crs(crs, geographic, always_xy=True).transform
    geod = geographic.get_geod()
    unit_factor = math.prod(axis.unit_conversion_factor for axis in crs.axis_info[:2])
    features, native, kept = [], [], []
    count = 0
    pixel_area = abs(affine.determinant) * unit_factor if crs.is_projected else None
    # Polygonize on the pixel grid first. This preserves holes and exact pixel-edge areas.
    for geom, value in shapes(mosaic, mask=mosaic != background, connectivity=4):
        count += 1
        if count > 100_000:
            raise ValueError('检测到超过 100,000 个斑块。请先减少掩膜碎斑或分区域处理。')
        value = int(value)
        pixel_geometry = shape(geom)
        polygons = list(polygon_parts(pixel_geometry if pixel_geometry.is_valid else make_valid(pixel_geometry)))
        if not polygons:
            continue
        pixels = round(sum(part.area for part in polygons))
        pixel_geometry = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
        world_geometry = project_geometry(lambda x, y: affine * (np.asarray(x), np.asarray(y)), pixel_geometry)
        world_parts = list(polygon_parts(world_geometry))
        world_geometry = world_parts[0] if len(world_parts) == 1 else MultiPolygon(world_parts)
        if crs.is_projected:
            area = pixels * pixel_area
        else:
            lonlat = project_geometry(transform_to_lonlat, world_geometry)
            area = sum(abs(geod.geometry_area_perimeter(part)[0]) for part in polygon_parts(lonlat))
        if not math.isfinite(area) or area <= 0:
            raise ValueError('无法计算至少一个斑块的面积，请检查参考图的坐标范围。')
        row = stats[value]
        row['raw_m2'] += area
        if area < threshold:
            row['removed'] += 1
            continue
        row['kept'] += 1
        row['area_m2'] += area
        properties = {'id': len(features) + 1, 'class_id': value, 'class_name': row['name'],
                      'pixels': pixels, 'area_m2': area, 'area_mu': area / SQUARE_METRES_PER_MU}
        wgs84 = project_geometry(transform_to_wgs84, world_geometry)
        if not all(math.isfinite(v) for v in wgs84.bounds):
            raise ValueError('无法将输出转换为 WGS 84，请检查参考图的坐标系与坐标范围。')
        wgs_parts = list(polygon_parts(wgs84))
        wgs84 = wgs_parts[0] if len(wgs_parts) == 1 else MultiPolygon(wgs_parts)
        features.append({'type': 'Feature', 'geometry': mapping(wgs84), 'properties': properties})
        native.append((world_geometry, properties))
        kept.append((mapping(pixel_geometry), value))
    if kept:
        filtered = rasterize(kept, out_shape=mosaic.shape, fill=background, dtype='uint16')
    else:
        filtered = np.full(mosaic.shape, background, dtype='uint16')
    return features, native, filtered


def convert(files, destination, threshold, background, demo=False):
    (reference_name, stream), masks, optional = collect_inputs(files)
    reference_path = destination / '_reference.tif'
    with reference_path.open('wb') as target:
        while chunk := stream.read(1024 * 1024):
            target.write(chunk)
    with rasterio.open(reference_path, driver='GTiff') as source:
        width, height, affine = source.width, source.height, source.transform
        if not source.crs or affine.is_identity or not all(map(math.isfinite, affine[:6])) or affine.determinant == 0:
            raise ValueError('参考 TIFF 须包含有效 CRS 与仿射变换。请先在 GIS 软件中完成配准或正射校正。')
        crs = CRS.from_wkt(source.crs.to_wkt())
        if not (crs.is_projected or crs.is_geographic) or crs.geodetic_crs is None:
            raise ValueError('参考图须采用投影坐标系或地理坐标系。')
        if width * height > MAX_PIXELS:
            raise ValueError(f'参考图不能超过 {MAX_PIXELS:,} 像元，请先裁剪范围。')
        preview = reference_preview(source)
        profile = {'driver': 'GTiff', 'width': width, 'height': height, 'count': 1,
                   'dtype': 'uint16', 'crs': source.crs, 'transform': affine, 'compress': 'deflate'}
    reference_path.unlink()
    positions = read_positions(optional['tiles.csv'], masks) if 'tiles.csv' in optional else None
    mosaic = stitch_masks(masks, positions, width, height)
    labels = read_classes(optional.get('classes.csv'))
    values = Counter(dict(zip(*np.unique(mosaic, return_counts=True))))
    values.pop(background, None)
    if len(values) > 24:
        raise ValueError('检测到超过 24 个前景类别。请使用离散类别掩膜，避免上传原图或概率图。')
    stats = {}
    for index, value in enumerate(sorted(map(int, values))):
        name, color = labels.get(value, (f'类别 {value}', ''))
        stats[value] = {'class_id': value, 'name': name, 'color': color or PALETTE[index % len(PALETTE)],
                        'raw_pixels': int(values[value]), 'raw_m2': 0.0, 'area_m2': 0.0, 'kept': 0, 'removed': 0}
    features, native, filtered = vectorize(mosaic, crs, affine, background, threshold, stats)
    total_area = sum(row['area_m2'] for row in stats.values())
    for row in stats.values():
        row['area_mu'] = row['area_m2'] / SQUARE_METRES_PER_MU
        row['share'] = row['area_m2'] / total_area if total_area else 0
    corners = [affine * point for point in [(0, 0), (width, 0), (width, height), (0, height)]]
    meta = {'reference': reference_name, 'width': width, 'height': height, 'tiles': len(masks),
            'crs': crs.to_string(), 'projected': crs.is_projected, 'transform': list(affine[:6]),
            'extent': [min(p[0] for p in corners), min(p[1] for p in corners),
                       max(p[0] for p in corners), max(p[1] for p in corners)],
            'threshold': threshold, 'background': background, 'demo': demo,
            'area_method': '投影平面面积（换算为平方米）' if crs.is_projected else '参考椭球测地面积',
            'classes': list(stats.values()), 'total_m2': total_area, 'total_mu': total_area / SQUARE_METRES_PER_MU,
            'kept': len(features), 'removed': sum(row['removed'] for row in stats.values())}
    write_products(destination, preview, mosaic, filtered, profile, crs, meta, features, native)
    (destination / 'summary.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    return meta
