\
# Listing S1 — Regular-Expression Templates for Candidate Retrieval
Encoding: UTF-8. PCRE/RE2-compatible. Use *case-insensitive* (`/i`) and *multiline* flags as appropriate.
Tested with Python `re` (verbose where noted).

## 1. DOI patterns
```
# Canonical DOI (greedy-safe)
\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b

# DOI with URL prefix (strip scheme before matching)
https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)
```
Notes: Return group(1) for normalized DOI when present in URL form.

## 2. Year and year-range patterns
```
# Single year (1900–2099) — avoid matching numbers like "1000 m"
(?<!\d)(19\d{2}|20\d{2})(?!\d)

# Year ranges with dash/hyphen/en dash/em dash/Chinese dash
(19|20)\d{2}\s*(?:-|–|—|—|至|到)\s*(19|20)\d{2}
```
Examples: `2000–2020`, `1990-2018`, `2005 至 2015`.

## 3. Dates (ISO, slash, dot, Chinese)
```
# ISO YYYY-MM-DD
\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b

# YYYY/MM or YYYY.MM
\b(19|20)\d{2}[/.](0[1-9]|1[0-2])\b

# Chinese: 2000年—2020年
\b(19|20)\d{2}年(?:-|–|—|至|到)(19|20)\d{2}年\b
```

## 4. Spatial resolution / grid-size patterns
```
# Metric units
\b(\d+(?:\.\d+)?)\s?(m|km)\b

# Degree-based
\b(\d+(?:\.\d+)?)\s?(deg|degree|degrees|°)\b

# Arc-second / arc-minute
\b(\d+(?:\.\d+)?)\s?(arc-?sec(?:ond)?s?|arc-?min(?:ute)?s?)\b

# Grid cell (e.g., 1 km × 1 km)
\b(\d+(?:\.\d+)?)\s?(m|km)\s?[×x]\s?(\d+(?:\.\d+)?)\s?(m|km)\b
```

## 5. Product codes and IDs
```
# MODIS product (e.g., MOD13Q1, MCD12Q1, MYD11A1)
\b(MOD|MYD|MCD)\d{2}[A-Z]\d{1,2}\b

# VIIRS product (e.g., VNP09, VNP46A1)
\bVNP\d{2}[A-Z]?\d*\b

# Landsat path/row (pXXXrYYY)
\b[pP]\d{3}[rR]\d{3}\b

# Sentinel processing levels
\bL(1[BCD]|2[AB])\b
```

## 6. URLs and file references
```
# Generic URL
https?://[^\s)>\]]+

# Common geospatial file extensions
\b\S+\.(shp|geojson|kml|kmz|tif|tiff|vrt|nc|grib2?)\b
```

## 7. Coordinate reference and EPSG codes
```
# EPSG code
\bEPSG:\d{3,5}\b

# WGS84 / latitude-longitude literal detection (cautious)
\b(WGS\s?84|WGS-?84|EPSG:4326)\b
```

## 8. Stations and gauges (loose)
```
# Words indicating stations (to be used as keyword boosters, not strict regex)
\b(meteorological|weather|hydrological|gauging)\s+stations?\b
```

## 9. Administrative names (Chinese en dash variants handled elsewhere)
Note: Prefer gazetteer-based matching for place names. Regex here is conservative.
```
# Province/City/County tokens
\b(province|city|county|district|自治州|省|市|县|区)\b
```

## 10. Quality flags / QA bands
```
\b(QA|quality\s?flag|bitmask|cloud\s?mask)\b
```

Implementation tips:
- Apply Unicode normalization (NFKC) prior to regex.
- When scoring, convert matches to binary features for `Match_regex(f_i)` in Eq. (2).
- Use per-document min–max normalization for composite score `S(f_i)`.
