# -*- coding: utf-8 -*-
"""Build the Iowa demonstration document using the ArcMap Python runtime."""

import os

import arcpy


def main():
    folder = os.environ['AGROMASK_MAP_FOLDER'].decode('mbcs')
    installation = os.environ['AGROMASK_ARCMAP_INSTALL'].decode('mbcs')
    template = os.path.join(installation, 'Templates', 'ExportWebMapTemplates', 'A4 Landscape.mxd')
    print('Opening the ArcMap template...')
    document = arcpy.mapping.MapDocument(template)
    frame = arcpy.mapping.ListDataFrames(document)[0]
    for existing in arcpy.mapping.ListLayers(document, '', frame):
        arcpy.mapping.RemoveLayer(frame, existing)

    reference = os.path.join(folder, 'aerial_display.tif')
    print('Loading the aerial image and crop polygons...')
    raster = arcpy.mapping.Layer(reference)
    raster.name = u'2023 NAIP / 航拍底图'
    arcpy.mapping.AddLayer(frame, raster, 'BOTTOM')

    backdrop = arcpy.mapping.Layer(os.path.join(folder, 'crop_display.tif'))
    backdrop.name = u'作物配色参考（栅格）'
    backdrop.visible = False
    arcpy.mapping.AddLayer(frame, backdrop, 'TOP')
    for filename, name in [('soybeans.shp', u'大豆 / Soybeans'), ('corn.shp', u'玉米 / Corn')]:
        layer = arcpy.mapping.Layer(os.path.join(folder, filename))
        layer.name = name
        layer.transparency = 48
        arcpy.mapping.AddLayer(frame, layer, 'TOP')

    frame.name = 'Iowa Crops 2023'
    frame.spatialReference = arcpy.Describe(reference).spatialReference
    frame.extent = arcpy.Describe(reference).extent
    document.activeView = frame.name
    document.relativePaths = True
    document.title = 'Iowa Corn and Soybeans | 2023'
    target = os.path.join(folder, 'Iowa_Crops_2023_ArcMap.mxd')
    print('Saving the map and checking the data sources...')
    staged = os.path.join(folder, '_building_Iowa_Crops_2023.mxd')
    document.saveACopy(staged)
    del document

    check = arcpy.mapping.MapDocument(staged)
    layers = arcpy.mapping.ListLayers(check)
    if len(layers) != 4 or arcpy.mapping.ListBrokenDataSources(check):
        raise RuntimeError('The saved ArcMap document has missing layers.')
    for layer, expected in zip(layers[:2], ((1, 14), (5, 13))):
        if layer.definitionQuery:
            raise RuntimeError('An unexpected query was attached to a crop layer.')
        with arcpy.da.SearchCursor(layer.dataSource, ['class_id']) as rows:
            values = [row[0] for row in rows]
        if values != [expected[0]] * expected[1]:
            raise RuntimeError('The saved crop layer has an unexpected feature count.')
    renderer = arcpy.mapping.ListDataFrames(check)[0]
    arcpy.mapping.ExportToPNG(check, os.path.join(folder, 'ArcMap_map.png'), renderer, 1290, 970, 96)
    del check, layers, layer
    os.rename(staged, target)
    print('ArcMap project verified: 14 corn polygons, 13 soybean polygons, and the NAIP basemap.')


if __name__ == '__main__':
    main()
