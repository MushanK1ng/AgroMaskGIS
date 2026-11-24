"""Validate the included example through independent pixel and export checks."""

import io
import json
import math
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import rasterio
import shapefile
from openpyxl import load_workbook
from PIL import Image
from rasterio.features import rasterize
from rasterio.warp import transform_geom

ROOT = Path(__file__).resolve().parent


def verify(source, output):
    meta = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
    with rasterio.open(source / 'reference.tif') as reference, \
            rasterio.open(output / 'mosaic.tif') as original, \
            rasterio.open(output / 'filtered.tif') as cleaned:
        for raster in (original, cleaned):
            assert raster.crs == reference.crs and raster.transform == reference.transform
            assert raster.shape == reference.shape
        raw, filtered = original.read(1), cleaned.read(1)
        transform, crs = reference.transform, reference.crs
        for row in range(0, reference.height, 160):
            for col in range(0, reference.width, 160):
                with Image.open(source / 'masks' / f'mask_x{col:04d}_y{row:04d}.png') as tile:
                    assert np.array_equal(raw[row:row + 160, col:col + 160], np.asarray(tile))

    with ZipFile(output / 'boundaries.zip') as pack:
        assert set(pack.namelist()) == {'boundaries.shp', 'boundaries.shx', 'boundaries.dbf', 'boundaries.prj', 'boundaries.cpg'}
        with shapefile.Reader(shp=io.BytesIO(pack.read('boundaries.shp')), shx=io.BytesIO(pack.read('boundaries.shx')),
                              dbf=io.BytesIO(pack.read('boundaries.dbf')), encoding='utf-8') as vector:
            native = [(item.shape.__geo_interface__, item.record['class_id']) for item in vector.iterShapeRecords()]
    assert len(native) == meta['kept']
    assert np.array_equal(filtered, rasterize(native, out_shape=filtered.shape, transform=transform, dtype='uint16'))

    features = json.loads((output / 'boundaries.geojson').read_text(encoding='utf-8'))['features']
    wgs = [(transform_geom('EPSG:4326', crs, item['geometry']), item['properties']['class_id']) for item in features]
    assert np.array_equal(filtered, rasterize(wgs, out_shape=filtered.shape, transform=transform, dtype='uint16'))

    workbook = load_workbook(output / 'area_statistics.xlsx', read_only=True, data_only=True)
    try:
        rows = list(workbook['类别汇总'].values)
        for value, _, raw_pixels, raw_area, area, mu, *_ in rows[1:-1]:
            assert np.count_nonzero(raw == value) == raw_pixels
            assert raw_pixels * .25 == raw_area
            assert np.count_nonzero(filtered == value) * .25 == area
            assert math.isclose(mu, area * .0015)
        assert math.isclose(rows[-1][5], meta['total_mu'])
        assert workbook['保留斑块'].max_row - 1 == meta['kept']
    finally:
        workbook.close()
    for name in ('area_chart.png', 'thematic_map.png'):
        with Image.open(output / name) as image:
            assert image.format == 'PNG' and image.width > 1000
            image.verify()

    print('PASS: 24 tiles match the mosaic pixel for pixel.')
    print('PASS: Shapefile and GeoJSON rasterize back to the filtered mask without pixel differences.')
    print(f'PASS: Excel totals reconcile ({meta["total_m2"]:,.2f} m2; {meta["total_mu"]:.5f} mu).')


if __name__ == '__main__':
    verify(ROOT / 'demo_data', ROOT / 'demo_results')
