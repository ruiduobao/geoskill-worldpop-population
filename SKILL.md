---
name: worldpop-population
description: 'Search and download WorldPop population grid datasets (GeoTIFF) by country description: 'Search and download WorldPop population grid datasets (GeoTIFF) by country and year.  Supports population density, births, age structures, and more. No API key required.  '
---

# WorldPop Population

Search and download high-resolution population grid data from
[WorldPop](https://www.worldpop.org/). Datasets include population density (100m),
births, age structures, contraceptive use, and more. No API key required.

## Features

- Search datasets by country, year, or type
- Download population grids as GeoTIFF
- List all available countries
- JSON output for scripting

## Usage

```bash
# Search for China population data
python scripts\worldpop-population.py search --country China --year 2020

# Search by ISO code
python scripts\worldpop-population.py search --code CHN --type population

# Download a dataset by ID
python scripts\worldpop-population.py download --id 25 --output pop_chn_2020.tif

# List available countries
python scripts\worldpop-population.py list-countries
```

## Installation

```bash
pip install requests>=2.28.0 tqdm
# Or: pip install -r scripts/requirements.txt
```

## Parameters

### `search`
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--country` | No* | — | Country name (e.g., "China") |
| `--code` | No* | — | ISO 3166-1 alpha-3 code (e.g., "CHN") |
| `--year` | No | — | Filter by year (2000-2020) |
| `--type` | No | — | Dataset type filter |
| `--json` | No | false | Output as JSON |

\* At least one of `--country` or `--code` is recommended.

### `download`
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--id` | Yes | — | Dataset ID (from search results) |
| `--output` | Yes | — | Output GeoTIFF path |

### `list-countries`
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--json` | No | false | Output as JSON |

## Data Source

- **API**: [WorldPop REST API](https://www.worldpop.org/rest/data)
- **Coverage**: Global (100+ countries)
- **Resolution**: 100m or 1km depending on dataset
- **Time range**: 2000-2020
- **License**: CC BY 4.0 (most datasets)
- **CRS**: WGS84 (EPSG:4326)
- **Data type**: float32
- **Nodata value**: -99999

### Valid `--type` Values

| Type | Description |
|------|-------------|
| `population` | Population density (persons per pixel) |
| `births` | Number of births |
| `age_structures` | Age structure grids |
| `contraceptive_use` | Contraceptive use estimates |
| `poverty` | Poverty indicators |
| `urban_change` | Urban change classification |
| `gender` | Gender-related indicators |
| `disability` | Disability prevalence |

### File Size Estimates

- ~400MB per country at 100m resolution (uncompressed GeoTIFF)
- ~40MB per country at 1km resolution
- Use `--check-size` before downloading large datasets

### Example Search Output

```json
[
  {
    "id": 25,
    "title": "China Population 2020",
    "year": 2020,
    "country": "CHN",
    "resolution": "100m",
    "type": "population",
    "url": "https://www.worldpop.org/..."
  }
]
```

### Choosing Between Datasets

- **100m resolution**: Best for local/regional analysis, urban planning
- **1km resolution**: Suitable for national/regional overviews, faster processing
- **Population density**: Most commonly used; persons per pixel
- **Births**: Useful for health service planning
- **Age structures**: Demographic analysis, dependency ratios

### Citation

If you use WorldPop data in publications, please cite:

```bibtex
@article{worldpop2018,
  title = {WorldPop, open data for spatial demography},
  author = {Tatem, Andrew J. and others},
  journal = {Scientific Data},
  volume = {5},
  pages = {180004},
  year = {2018},
  doi = {10.1038/sdata.2018.4}
}
```

## Visualization

- Plot population density with log scale: `plt.imshow(np.log1p(data), cmap='hot')`
- Use `rasterio.plot.show()` for quick visualization
- Create choropleth maps by aggregating to administrative boundaries
- Overlay with `contextily` basemaps for context

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `ConnectionError` | Network issue | Check internet, retry |
| `HTTP 429` | Rate limit | Wait 60s, retry |
| `ValueError` | Invalid input | Check parameter format |
| Empty output | No data | Try different parameters |
| `ModuleNotFoundError` | Missing dep | Run pip install |
| Large file size | High resolution | Use 1km datasets or subset by bbox |
| Download timeout | Slow connection | Retry or use smaller dataset |

---

## Advanced Usage

### Batch Country Download
```bash
# Download population for multiple countries
for iso in CHN IND USA BRA; do
  python scripts\worldpop-population.py download     --iso $iso --type population --year 2020     --output pop_${iso}_2020.tif
  sleep 2
done
```

### CI/CD Integration (GitHub Actions)
```yaml
# .github/workflows/update-population.yml
name: Update Population Data
on:
  schedule:
    - cron: '0 0 1 1 *'  # Yearly
jobs:
  download:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install requests tqdm
      - run: |
          python scripts\worldpop-population.py download \
            --iso CHN --type population --year 2020 \
            --output data/china_pop2020.tif
```

### Windowed Reading for Large Files
```python
import rasterio
from rasterio.windows import Window
# Read only a subset to avoid loading 400MB into memory
with rasterio.open('pop_CHN_2020.tif') as src:
    window = Window(0, 0, 1000, 1000)  # top-left 1000x1000 pixels
    subset = src.read(1, window=window)
```

### PostgreSQL/PostGIS Raster Import
```bash
raster2pgsql -s 4326 -I -C pop_CHN_2020.tif public.worldpop | psql -d gis_db
```

### Performance Tips
- 100m files are ~400MB; use windowed reading for subset analysis
- Add `sleep 2` between downloads to respect rate limits
- Use `--type population` for total pop, `--type population_density` for per-km²
- NoData value is -99999; mask before arithmetic operations

---

## 中文说明

从 [WorldPop](https://www.worldpop.org/) 搜索和下载高分辨率人口栅格数据（GeoTIFF）。
包括人口密度（100m）、出生、年龄结构等数据集。无需 API 密钥。

### 功能

- 按国家、年份或类型搜索数据集
- 下载人口栅格为 GeoTIFF
- 列出所有可用国家
- JSON 输出支持脚本调用

### 使用方法

```bash
# 搜索中国人口数据
python scripts\worldpop-population.py search --country China --year 2020

# 按 ISO 代码搜索
python scripts\worldpop-population.py search --code CHN --type population

# 按 ID 下载数据集
python scripts\worldpop-population.py download --id 25 --output pop_chn_2020.tif

# 列出可用国家
python scripts\worldpop-population.py list-countries
```

### 数据来源

- **API**: [WorldPop REST API](https://www.worldpop.org/rest/data)
- **覆盖范围**: 全球（100+ 国家）
- **分辨率**: 100m 或 1km（取决于数据集）
- **时间范围**: 2000-2020
- **许可证**: CC BY 4.0（大多数数据集）
- **坐标系**: WGS84 (EPSG:4326)
- **数据类型**: float32
- **无数据值**: -99999

### 有效的 `--type` 值

| 类型 | 描述 |
|------|------|
| `population` | 人口密度（每像素人数） |
| `births` | 出生人数 |
| `age_structures` | 年龄结构栅格 |
| `contraceptive_use` | 避孕药具使用估计 |
| `poverty` | 贫困指标 |
| `urban_change` | 城市变化分类 |
| `gender` | 性别相关指标 |
| `disability` | 残疾患病率 |

### 文件大小估计

- 100m 分辨率：每个国家约 400MB（未压缩 GeoTIFF）
- 1km 分辨率：每个国家约 40MB
- 下载大数据集前可使用 `--check-size` 查看大小

### 搜索结果示例

```json
[
  {
    "id": 25,
    "title": "China Population 2020",
    "year": 2020,
    "country": "CHN",
    "resolution": "100m",
    "type": "population",
    "url": "https://www.worldpop.org/..."
  }
]
```

### 数据集选择指南

- **100m 分辨率**: 适合局地/区域分析、城市规划
- **1km 分辨率**: 适合国家/区域概览，处理更快
- **人口密度**: 最常用；每像素人数
- **出生人数**: 适用于卫生服务规划
- **年龄结构**: 人口统计分析、抚养比

### 引用格式

如果发表使用 WorldPop 数据，请引用:

```bibtex
@article{worldpop2018,
  title = {WorldPop, open data for spatial demography},
  author = {Tatem, Andrew J. and others},
  journal = {Scientific Data},
  volume = {5},
  pages = {180004},
  year = {2018},
  doi = {10.1038/sdata.2018.4}
}
```

### 可视化

- 使用对数比例绘制人口密度: `plt.imshow(np.log1p(data), cmap='hot')`
- 使用 `rasterio.plot.show()` 快速可视化
- 聚合到行政区划创建等值区域图
- 使用 `contextily` 底图叠加上下文

### 故障排除

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `ConnectionError` | 网络问题 | 检查网络，重试 |
| `HTTP 429` | 速率限制 | 等待 60 秒后重试 |
| `ValueError` | 无效输入 | 检查参数格式 |
| 空输出 | 无数据 | 尝试不同参数 |
| `ModuleNotFoundError` | 缺少依赖 | 运行 pip install |
| 文件过大 | 高分辨率 | 使用 1km 数据集或按边界截取 |
| 下载超时 | 网络慢 | 重试或使用更小的数据集 |
