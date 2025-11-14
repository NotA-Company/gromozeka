# API Endpoints

## /search

**Description:** Convert an address or location to a pair of geographic coordinates. (Forward Geocode)

**Endpoint:** `GET https://geocode.maps.co/search`

### Parameters

| Parameter | Description | Default / Notes |
| --- | --- | --- |
| `api_key` | Your API Key | Required.   **Security Note:** You can also send your API key via the `Authorization: Bearer YOUR_SECRET_API_KEY` HTTP Header |
| `q` | Free-form search query | Required unless structured fields used |
| `amenity` | e.g. place of interest, attraction, business name | Optional |
| `street` | House Number & Street name | Optional |
| `city` | City name | Optional |
| `county` | County / district | Optional |
| `state` | State / region | Optional |
| `country` | Country name | Optional |
| `postalcode` | Postal code | Optional |
| `addressdetails` | Include structured address (0/1) | Optional. Default: 1 |
| `extratags` | Include extra OSM tags, e.g. wikipedia link, business detils, etc. (0/1) | Optional. Default: 1 |
| `namedetails` | Include name variants (0/1) | Optional. Default: 1 |
| `limit` | Maximum number of results to return, 0-40 | Optional. Default: 10 |
| `countrycodes` | Restrict to specific country codes | Optional |
| `viewbox` | Bias search with bounding box | Optional |
| `bounded` | Restrict to viewbox (0/1) | Default: 0 |
| `dedupe` | Attempt to remove duplicate OSM results (0/1) | Default: 1 |
| `format` | Response format (`xml`, `json`, `jsonv2`, `geojson`, `geocodejson`) | Default: `json` |
| `accept-language` | Set language of returned results, e.g. `en`, `fr`, `it`, `pl`, etc. | Automatic Detection (may be inaccurate) |

### Example JSON Response

```json
    [
      {
        "place_id": 100149,
        "osm_type": "node",
        "osm_id": "107775",
        "lat": "51.5073",
        "lon": "-0.1276",
        "display_name": "London, England, United Kingdom",
        "type": "city",
        "importance": 0.96,
        "address": {
          "city": "London",
          "state": "England",
          "country": "United Kingdom",
          "country_code": "gb"
        }
      }
    ]
```

### Usage Notes

- Use `q` for simple searches, or structured parameters for precision.
- Always URL-encode special characters.
- Our endpoints return `addressdetails`, `name details`, and `extratags` by default.

## /reverse

**Description:** Convert a pair of geographic coordinates to a human-readable address. (Reverse Geocode)

**Endpoint:** `GET https://geocode.maps.co/reverse`

### Parameters

| Parameter | Description | Default / Notes |
| --- | --- | --- |
| `api_key` | Your API Key | Required.   **Security Note:** You can also send your API key via the `Authorization: Bearer YOUR_SECRET_API_KEY` HTTP Header |
| `lat` | Latitude | Required |
| `lon` | Longitude | Required |
| `addressdetails` | Include structured address fragmants in result (0/1) | Optional. Default: 1 |
| `extratags` | Include extra OSM tags (0/1) | Optional. Default: 1 |
| `namedetails` | Include name variants (0/1) | Optional. Default: 1 |
| `zoom` | Detail level (3-18) | Optional |
| `format` | Response format (`xml`, `json`, `jsonv2`, `geojson`, `geocodejson`) | Default: `json` |
| `accept-language` | Set language of returned results, e.g. `en`, `fr`, `it`, `pl`, etc. | Optional |

### Example JSON Response

```json
    {
      "place_id": 287295616,
      "osm_type": "relation",
      "osm_id": "7340078",
      "lat": "40.7033",
      "lon": "-74.0105",
      "display_name": "Manhattan, New York, United States",
      "address": {
        "city": "Manhattan",
        "state": "New York",
        "country": "United States",
        "country_code": "us"
      }
    }
```

### Usage Notes

- Reverse geocoding returns the nearest OSM object to a coordinate.
- Only one result is returned.
- For object IDs, use the `/lookup` endpoint instead.

## /lookup

**Description:** Get the details for one or more objects by OSM ID.

**Endpoint:** `GET https://geocode.maps.co/lookup`

### Parameters

| Parameter | Description | Default / Notes |
| --- | --- | --- |
| `api_key` | Your API Key | Required.   **Security Note:** You can also send your API key via the `Authorization: Bearer YOUR_SECRET_API_KEY` HTTP Header |
| `osm_ids` | Comma-separated OSM IDs with type prefix (N, W, R), e.g. R253832 | Required |
| `addressdetails` | Include structured address fragmants in result (0/1) | Optional. Default: 1 |
| `extratags` | Include extra OSM tags (0/1) | Optional. Default: 1 |
| `namedetails` | Include name variants (0/1) | Optional. Default: 1 |
| `polygon_geojson` | Output polygon shape in `geojson` format (0/1) | Optional. Default: 0 |
| `polygon_kml` | Output polygon shape in `kml` format (0/1) | Optional. Default: 0 |
| `polygon_svg` | Output polygon shape in `svg` format (0/1) | Optional. Default: 0 |
| `polygon_text` | Output polygon shape in `text` format (0/1) | Optional. Default: 0 |
| `format` | Response format (`xml`, `json`, `jsonv2`, `geojson`, `geocodejson`) | Default: `json` |
| `accept-language` | Set language of returned results, e.g. `en`, `fr`, `it`, `pl`, etc. | Optional |

### Example JSON Response

```json
    [
      {
        "place_id": 235405672,
        "osm_type": "R",
        "osm_id": 175905,
        "type": "administrative",
        "localname": "New York",
        "centroid": {"type":"Point","coordinates":[-74.006,40.7127]}
      }
    ]
```

### Usage Notes

- Use when you already know OSM object IDs.
- Multiple IDs can be requested at once (comma-separated).
- Geometry fields can be large; include only if needed.

© Copyright 2025 All Rights Reserved

[Terms & Privacy](https://geocode.maps.co/terms/)

Downloaded from https://geocode.maps.co/docs/endpoints/