# AgroMask GIS

一个本地运行的农业遥感后处理工具。输入带坐标的 GeoTIFF 和分类掩膜切片，程序按偏移拼接掩膜，提取矢量边界，按面积筛除碎斑，并导出 Shapefile、GeoJSON、Excel 和 PNG 图件。

## Windows 快速启动

1. 安装 64 位 Python 3.11，解压整套项目。
2. 双击 `start.bat`。首次启动会创建独立环境，优先从 `wheels` 离线安装。服务启动后会自动打开浏览器。
3. 内置样例可直接运行。演示真实案例时，选择「导入我的项目」，选择 `真实案例_爱荷华农田/01_导入数据`，背景值填 `0`，筛除阈值填 `9000` 平方米。

真实案例含 25 张掩膜切片。使用上述阈值会保留 27 个斑块、筛除 39 个，有效面积为 9,516,600 平方米，约 14,274.90 亩。

如要在 ArcMap 10.8 中查看，可以把 `reference.tif` 和解压后的 `boundaries.shp` 同时加载，或在已安装且获得许可的 ArcMap 环境中运行 `真实案例_爱荷华农田/open_arcmap.bat`，在本机生成演示工程。ArcMap 本身需要另行安装。

## 项目文件

| 路径 | 用途 |
| --- | --- |
| `app.py`、`pipeline.py`、`products.py` | 本地服务、GIS 处理和成果导出 |
| `static/`、`templates/` | 网页界面 |
| `demo_data/`、`demo_results/` | 内置模拟输入及预生成成果 |
| `真实案例_爱荷华农田/` | 爱荷华州真实数据、结果、来源和演示说明 |
| `arcmap_support/` | ArcMap 工程生成脚本与配套数据 |
| `wheels/` | Windows x64 Python 3.11 的离线依赖 |

## 数据来源

真实案例使用 2023 年 NAIP 自然色航拍和 USDA NASS Cropland Data Layer。导出的矢量复现了官方分类像元，适合验证空间化与面积统计流程。内置玉米倒伏样例为模拟数据。[航拍影像](https://ortho.gis.iastate.edu/) · [官方分类](https://www.nass.usda.gov/Research_and_Science/Cropland/Release/index.php)

详见 `使用与答辩说明.txt` 和真实案例目录下的 `演示说明.txt`。
