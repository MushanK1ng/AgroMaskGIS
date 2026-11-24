"""Package presentation layers for the Iowa ArcMap example."""

from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
from PIL import Image
import rasterio
import shapefile


def package_layers(case: Path) -> None:
    results = case / '02_预生成成果'
    package = Path(__file__).with_name('arcmap-layers.zip')
    with TemporaryDirectory(dir=package.parent) as directory:
        stage = Path(directory)
        with ZipFile(results / 'boundaries.zip') as source_zip:
            source = stage / 'boundaries.shp'
            for suffix in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
                name = source.with_suffix(suffix).name
                with source_zip.open(name) as data, (stage / name).open('wb') as target:
                    copyfileobj(data, target)
        filenames = []
        with shapefile.Reader(str(source), encoding='utf-8') as source_layer:
            for class_id, label in ((1, 'corn'), (5, 'soybeans')):
                with shapefile.Writer(str(stage / label), shapeType=source_layer.shapeType, encoding='utf-8') as target:
                    target.fields = source_layer.fields[1:]
                    for record in source_layer.iterShapeRecords():
                        if record.record['class_id'] == class_id:
                            target.shape(record.shape)
                            target.record(*record.record)
                for suffix in ('.prj', '.cpg'):
                    (stage / (label + suffix)).write_bytes(source.with_suffix(suffix).read_bytes())
                filenames.extend(label + ext for ext in ('.shp', '.shx', '.dbf', '.prj', '.cpg'))
        with rasterio.open(case / '01_导入数据' / 'reference.tif') as raster:
            aerial = Image.fromarray(np.moveaxis(raster.read(), 0, -1))
            profile = raster.profile
        profile.update(count=1, photometric='PALETTE', dtype='uint8')
        # An internal colour table keeps this display independent of ArcMap RGB defaults.
        for name, image in [('aerial_display.tif', aerial),
                            ('crop_display.tif', Image.open(results / 'overlay.png').convert('RGB'))]:
            indexed = image.quantize(colors=256, dither=Image.Dither.NONE)
            palette = indexed.getpalette()
            assert indexed.size == aerial.size
            with rasterio.open(stage / name, 'w', **profile) as target:
                target.write(np.asarray(indexed), 1)
                target.write_colormap(1, {i: tuple(palette[3*i:3*i+3]) for i in range(256)})
            filenames.append(name)
        with ZipFile(package, 'w', ZIP_DEFLATED) as out:
            for name in filenames:
                out.write(stage / name, name)


if __name__ == '__main__':
    package_layers(Path(__file__).resolve().parents[1] / '真实案例_爱荷华农田')
