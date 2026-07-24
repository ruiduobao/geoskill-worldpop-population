# WorldPop Population

Search and download high-resolution population grid data from
[WorldPop](https://www.worldpop.org/). No API key required.

## Install

### ClawHub
```bash
clawhub install worldpop-population
```

### Manual
```bash
git clone https://github.com/ruiduobao/worldpop-population.git
cd worldpop-population
pip install requests tqdm
```

### Claude Code / skills.sh
```bash
claude skills install worldpop-population
```

## Quick Start

```bash
# Search for China population data
python scripts/worldpop-population.py search --country China --year 2020

# Download a dataset
python scripts/worldpop-population.py download --id 25 --output pop_chn_2020.tif

# List available countries
python scripts/worldpop-population.py list-countries
```

## Data Source

- **API**: [WorldPop REST API](https://www.worldpop.org/rest/data)
- **Coverage**: Global (100+ countries)
- **Resolution**: 100m or 1km
- **License**: CC BY 4.0

---

# WorldPop 人口数据下载

从 [WorldPop](https://www.worldpop.org/) 搜索和下载高分辨率人口栅格数据。无需 API 密钥。

## 安装

### ClawHub
```bash
clawhub install worldpop-population
```

### 手动安装
```bash
git clone https://github.com/ruiduobao/worldpop-population.git
cd worldpop-population
pip install requests tqdm
```

### Claude Code / skills.sh
```bash
claude skills install worldpop-population
```

## 快速开始

```bash
# 搜索中国人口数据
python scripts/worldpop-population.py search --country China --year 2020

# 下载数据集
python scripts/worldpop-population.py download --id 25 --output pop_chn_2020.tif

# 列出可用国家
python scripts/worldpop-population.py list-countries
```

## 数据来源

- **API**: [WorldPop REST API](https://www.worldpop.org/rest/data)
- **覆盖范围**: 全球（100+ 国家）
- **分辨率**: 100m 或 1km
- **许可证**: CC BY 4.0
