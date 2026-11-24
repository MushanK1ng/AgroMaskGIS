"""Create portable GIS, Excel, and image outputs from one analysis result."""

import json
import math
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import rasterio
import shapefile
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Patch
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageColor
from shapely.geometry.polygon import orient

DOWNLOADS = {
    'boundaries.zip': 'Shapefile 边界', 'boundaries.geojson': 'GeoJSON 边界',
    'area_statistics.xlsx': 'Excel 统计表', 'area_chart.png': '面积柱状图',
    'thematic_map.png': '专题地图', 'mosaic.tif': '原始拼接 GeoTIFF',
    'filtered.tif': '筛除后 GeoTIFF', 'all_outputs.zip': '全部成果',
}
PREVIEWS = {'overlay.png', 'reference.png', 'raw.png', 'filtered.png'}


def export_boundaries(destination, crs, features, native):
    collection = {'type': 'FeatureCollection', 'features': features}
    (destination / 'boundaries.geojson').write_text(json.dumps(collection, ensure_ascii=False), encoding='utf-8')
    base = destination / 'boundaries'
    with shapefile.Writer(str(base), shapeType=shapefile.POLYGON, encoding='utf-8') as writer:
        writer.field('id', 'N', 9)
        writer.field('class_id', 'N', 5)
        writer.field('class_name', 'C', 120)
        writer.field('pixels', 'N', 12)
        writer.field('area_m2', 'F', 20, 4)
        writer.field('area_mu', 'F', 18, 6)
        for geometry, p in native:
            polygons = geometry.geoms if geometry.geom_type == 'MultiPolygon' else [geometry]
            rings = []
            for polygon in polygons:
                polygon = orient(polygon, sign=-1)
                rings.extend([list(polygon.exterior.coords), *(list(ring.coords) for ring in polygon.interiors)])
            writer.poly(rings)
            writer.record(p['id'], p['class_id'], p['class_name'], p['pixels'], p['area_m2'], p['area_mu'])
    base.with_suffix('.prj').write_text(crs.to_wkt('WKT1_ESRI'), encoding='utf-8')
    base.with_suffix('.cpg').write_text('UTF-8', encoding='ascii')
    with ZipFile(destination / 'boundaries.zip', 'w', ZIP_DEFLATED) as archive:
        for suffix in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
            part = base.with_suffix(suffix)
            archive.write(part, part.name)
            part.unlink()


def export_workbook(path, meta, features):
    workbook = Workbook()
    summary = workbook.active
    summary.title = '类别汇总'
    summary.append(['类别值', '类别', '原始像元数', '筛除前面积 (m²)', '有效面积 (m²)',
                    '有效面积 (亩)', '保留斑块', '筛除斑块', '有效面积占比'])
    for row in meta['classes']:
        summary.append([row[key] for key in ('class_id', 'name', 'raw_pixels', 'raw_m2', 'area_m2',
                                             'area_mu', 'kept', 'removed', 'share')])
    summary.append([None, '合计', sum(row['raw_pixels'] for row in meta['classes']),
                    sum(row['raw_m2'] for row in meta['classes']), meta['total_m2'], meta['total_mu'],
                    meta['kept'], meta['removed'], 1 if meta['total_m2'] else 0])
    details = workbook.create_sheet('保留斑块')
    details.append(['斑块 ID', '类别值', '类别', '像元数', '面积 (m²)', '面积 (亩)'])
    for feature in features:
        p = feature['properties']
        details.append([p[key] for key in ('id', 'class_id', 'class_name', 'pixels', 'area_m2', 'area_mu')])
    settings = workbook.create_sheet('处理参数')
    for row in [('参数', '值'), ('数据来源', '程序生成的模拟数据' if meta['demo'] else '用户上传'),
                ('参考影像', meta['reference']), ('参考坐标系', meta['crs']), ('掩膜数量', meta['tiles']),
                ('参考图宽 (像元)', meta['width']), ('参考图高 (像元)', meta['height']),
                ('过滤阈值 (m²)', meta['threshold']), ('背景值', meta['background']), ('连通性', '四邻域'),
                ('面积算法', meta['area_method']), ('亩的换算', '1 亩 = 2000/3 m²'),
                ('占比分母', '筛除后全部前景类别的有效面积')]:
        settings.append(row)

    for sheet, widths in [(summary, (12, 34, 15, 20, 20, 19, 14, 14, 18)),
                          (details, (14, 14, 34, 14, 20, 20)), (settings, (24, 72))]:
        sheet.freeze_panes = 'A2'
        if sheet is not settings:
            bottom = sheet.max_row - 1 if sheet is summary else sheet.max_row
            sheet.auto_filter.ref = f'A1:{get_column_letter(sheet.max_column)}{bottom}'
        for index, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(index)].width = width
        for idx, row in enumerate(sheet.iter_rows(), 1):
            sheet.row_dimensions[idx].height = 26 if idx == 1 else 21
            for cell in row:
                # Uploaded labels are literal text, even when they start with '='.
                if isinstance(cell.value, str):
                    cell.data_type = 's'
                if idx == 1:
                    cell.fill = PatternFill('solid', fgColor='203547')
                    cell.font = Font(name='Microsoft YaHei', color='FFFFFF', bold=True)
                else:
                    total = sheet is summary and idx == sheet.max_row
                    cell.fill = PatternFill('solid', fgColor='DFF4EE' if total else ('F0F5F7' if idx % 2 == 0 else 'FFFFFF'))
                    cell.font = Font(name='Microsoft YaHei', color='203547', bold=total)
                cell.alignment = Alignment(vertical='center')
                if idx > 1 and sheet is not settings and isinstance(cell.value, (int, float)):
                    if sheet is summary and cell.column == 9:
                        cell.number_format = '0.0%'
                    elif cell.column in ((4, 5, 6) if sheet is summary else (5, 6)):
                        cell.number_format = '#,##0.00'
                    else:
                        cell.number_format = '#,##0'
    workbook.save(path)


def map_images(destination, preview, mosaic, filtered, classes, background):
    def rgba(array):
        # Resize class IDs first with nearest neighbour to avoid introducing labels.
        ids = np.asarray(Image.fromarray(array).resize(preview.size, Image.Resampling.NEAREST))
        lookup = np.zeros((65536, 4), dtype=np.uint8)
        for row in classes:
            lookup[row['class_id']] = (*ImageColor.getrgb(row['color']), 255)
        return lookup[ids], ids != background

    raw, _ = rgba(mosaic)
    cleaned, active = rgba(filtered)
    mask_base = Image.new('RGBA', preview.size, '#142534')
    Image.alpha_composite(mask_base, Image.fromarray(raw)).save(destination / 'raw.png')
    Image.alpha_composite(mask_base, Image.fromarray(cleaned)).save(destination / 'filtered.png')
    preview.save(destination / 'reference.png', optimize=True)
    padded = np.pad(cleaned, ((1, 1), (1, 1), (0, 0)))
    adjacent = (padded[:-2, 1:-1], padded[2:, 1:-1], padded[1:-1, :-2], padded[1:-1, 2:])
    edges = active & np.any([np.any(neighbor != cleaned, axis=2) for neighbor in adjacent], axis=0)
    cleaned[:, :, 3] = np.where(edges, 255, np.where(active, 143, 0))
    overlay = Image.alpha_composite(preview.convert('RGBA'), Image.fromarray(cleaned)).convert('RGB')
    overlay.save(destination / 'overlay.png', optimize=True)
    return overlay


def report_fonts():
    fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
    for name in ('msyh.ttc', 'simhei.ttf', 'simsun.ttc'):
        if (fonts / name).is_file():
            return FontProperties(fname=fonts / name), True
    return FontProperties(family='DejaVu Sans'), False


def export_chart(path, meta, font, chinese):
    rows = meta['classes']
    height = max(3.65, 2.2 + 0.48 * len(rows))
    figure = Figure(figsize=(9.2, height), facecolor='#f6fafb')
    FigureCanvasAgg(figure)
    figure.text(.08, 1 - .19 / height, '各类别面积 · 筛除前后' if chinese else 'Area by class · before and after filtering',
                fontsize=19, color='#183145', va='top', fontproperties=font)
    figure.text(.08, 1 - .55 / height, ('模拟数据   /   ' if meta['demo'] and chinese else 'Synthetic data   /   ' if meta['demo'] else '')
                + f'{meta["crs"][:42]}   /   {meta["threshold"]:g} m²', fontsize=10, color='#536b79',
                va='top', fontproperties=font)
    axis = figure.add_axes((.08, .47 / height, .87, 1 - 1.5 / height))
    if rows:
        positions = np.arange(len(rows))
        raw = [row['raw_m2'] for row in rows]
        axis.barh(positions + .16, raw, height=.26, color='#cfdadf')
        bars = axis.barh(positions - .16, [row['area_m2'] for row in rows], height=.26,
                         color=[row['color'] for row in rows])
        maximum = max(raw)
        axis.set_xlim(0, maximum * 1.31)
        for bar, row in zip(bars, rows):
            axis.text(row['raw_m2'] + maximum * .018, bar.get_y() + bar.get_height() / 2,
                      f'{row["area_m2"]:,.2f} m²', va='center', color='#203547', fontsize=8)
        for index, row in enumerate(rows):
            label = row['name'] if chinese else f'Class {row["class_id"]}'
            axis.text(0, index - .44, label, va='center', fontsize=9, fontproperties=font, color='#203547', parse_math=False)
        axis.set_ylim(len(rows) - .52, -.62)
        legend = [Patch(color='#cfdadf', label='筛除前' if chinese else 'Before'),
                  Patch(facecolor='none', edgecolor='#51687c', hatch='///',
                        label='筛除后（按类别着色）' if chinese else 'After (class colours)')]
        figure.legend(handles=legend, loc='upper right', bbox_to_anchor=(.95, 1 - .49 / height),
                      ncol=2, frameon=False, prop=font)
    else:
        axis.text(.5, .5, '未检测到前景像元' if chinese else 'No foreground pixels',
                  transform=axis.transAxes, ha='center', fontproperties=font)
    axis.set_facecolor('#f6fafb')
    axis.spines[['top', 'right', 'left', 'bottom']].set_visible(False)
    axis.set_yticks([])
    axis.set_axisbelow(True)
    axis.grid(axis='x', alpha=.25)
    axis.tick_params(axis='x', colors='#506676', labelsize=9, length=0)
    axis.set_xlabel('m²', color='#506676', fontsize=9, loc='right')
    figure.savefig(path, dpi=180)


def export_map(path, meta, image, crs, font, chinese):
    labels = [row for row in meta['classes'] if row['kept']]
    legend_height = math.ceil(len(labels) / 3) * .24
    figure_height = 8 + legend_height
    figure = Figure(figsize=(11, figure_height), facecolor='#f6fafb')
    FigureCanvasAgg(figure)
    title = '田间推理结果专题图' if chinese else 'Field inference · thematic map'
    figure.text(.06, 1 - .50 / figure_height, title, fontsize=24, color='#183145', fontproperties=font)
    note = ('模拟数据   /   ' if meta['demo'] and chinese else 'Synthetic data   /   ' if meta['demo'] else '')
    figure.text(.06, 1 - .82 / figure_height, note + f'{meta["crs"][:42]}   /   {meta["width"]} × {meta["height"]} px',
                fontsize=11, color='#536b79', fontproperties=font)
    axis = figure.add_axes((.06, (.65 + legend_height) / figure_height, .88, 6.15 / figure_height))
    axis.imshow(image)
    axis.set_axis_off()
    a, b, _, d, e, _ = meta['transform']
    if crs.is_projected and not (b or d) and a > 0 and e < 0:
        axis.annotate('N', xy=(.95, .95), xytext=(.95, .82), ha='center', color='white', weight='bold',
                      xycoords='axes fraction', arrowprops={'arrowstyle': '-|>', 'color': 'white', 'lw': 1.7})
        width_m = meta['width'] * a * crs.axis_info[0].unit_conversion_factor
        order = 10 ** math.floor(math.log10(width_m * .23))
        length = max(step * order for step in (1, 2, 5) if step * order <= width_m * .23)
        axis.plot([.06, .06 + length / width_m], [.055, .055], transform=axis.transAxes, color='white', lw=3)
        axis.text(.06, .08, f'{length:g} m', color='white', transform=axis.transAxes, fontsize=9)
    handles = [Patch(color=row['color'], label=(row['name'][:17] + '…' if len(row['name']) > 18 else row['name'])
                      if chinese else f'Class {row["class_id"]}') for row in labels]
    if handles:
        map_legend = figure.legend(handles=handles, loc='lower left', bbox_to_anchor=(.055, .46 / figure_height), ncol=3,
                                   frameon=False, prop=font)
        for label in map_legend.get_texts():
            label.set_parse_math(False)
    footer = f'阈值 {meta["threshold"]:g} m²   |   保留 {meta["kept"]} 个斑块' if chinese else (
        f'Threshold {meta["threshold"]:g} m²   |   {meta["kept"]} retained patches')
    figure.text(.06, .035, footer, fontsize=10, color='#536b79', fontproperties=font)
    figure.savefig(path, dpi=180)


def write_products(destination, preview, mosaic, filtered, profile, crs, meta, features, native):
    for name, array in [('mosaic.tif', mosaic), ('filtered.tif', filtered)]:
        with rasterio.open(destination / name, 'w', **profile) as target:
            target.write(array, 1)
    export_boundaries(destination, crs, features, native)
    export_workbook(destination / 'area_statistics.xlsx', meta, features)
    overlay = map_images(destination, preview, mosaic, filtered, meta['classes'], meta['background'])
    font, chinese = report_fonts()
    export_chart(destination / 'area_chart.png', meta, font, chinese)
    export_map(destination / 'thematic_map.png', meta, overlay, crs, font, chinese)
    with ZipFile(destination / 'all_outputs.zip', 'w', ZIP_DEFLATED) as archive:
        for name in DOWNLOADS:
            if name != 'all_outputs.zip':
                archive.write(destination / name, name)
        archive.writestr('summary.json', json.dumps(meta, ensure_ascii=False, indent=2))
