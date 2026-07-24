# WorldPop Population Skill - Development Doc

## Purpose
Search and download WorldPop population grid datasets (GeoTIFF) by country/year.

## API Reference
- Base URL: `https://www.worldpop.org/rest/data`
- List datasets: GET `https://www.worldpop.org/rest/data`
- Dataset detail: GET `https://www.worldpop.org/rest/data/{id}`
- Download: GET the `files` URL from dataset detail
- No API key required

## CLI Design
```
worldpop-population search --country China --year 2020
worldpop-population search --country CN --type population
worldpop-population download --id 25 --output pop_chn_2020.tif
worldpop-population list-countries
```

### Subcommands
- `search`: search datasets
  - `--country`: country name or ISO code
  - `--year`: filter by year
  - `--type`: filter by dataset type (population, births, etc.)
  - `--json`: output as JSON
- `download`: download a dataset by ID
  - `--id`: dataset ID (from search)
  - `--output`: output file path
- `list-countries`: list available countries

## Privacy
- Only HTTP GET requests to worldpop.org
- No personal data sent

## Error Handling
- Handle network errors
- Validate country names
- Handle missing datasets gracefully
