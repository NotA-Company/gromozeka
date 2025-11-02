# Golden Data Testing System v2 for OpenWeatherMap

This directory contains the new Golden Data Testing System v2 implementation for the OpenWeatherMap client. This system replaces the older v1 approach with a more generic and reusable framework.

## Directory Structure

```
tests/golden_data/openweathermap/
├── inputs/
│   ├── locations.json (v1 format - legacy)
│   └── locations_v2.json (v2 format - CollectorInput)
├── golden_v2/ (new directory for v2 golden data)
│   ├── getWeatherByCity/
│   ├── getWeatherByCoordinates/
│   └── getCoordinates/
├── collect_v2.py (new collector using generic system)
├── test_with_golden_v2.py (new tests using golden data)
└── README_v2.md (this file)
```

## How to Collect Golden Data Using the New System

1. **Set up your environment**:
   ```bash
   export OPENWEATHERMAP_API_KEY="your_actual_api_key"
   ```

2. **Run the collector script**:
   ```bash
   python tests/golden_data/openweathermap/collect_v2.py
   ```

3. **The collector will**:
   - Read test scenarios from `inputs/locations_v2.json`
   - Make actual API calls to OpenWeatherMap
   - Record HTTP requests and responses
   - Mask your API key in the recorded data
   - Save golden data to `golden_v2/` directory

## How to Run Tests with Golden Data

1. **Run all tests**:
   ```bash
   pytest tests/golden_data/openweathermap/test_with_golden_v2.py -v
   ```

2. **Run specific tests**:
   ```bash
   pytest tests/golden_data/openweathermap/test_with_golden_v2.py::test_get_weather_by_city_minsk -v
   ```

## Differences Between v1 and v2

| Feature | v1 System | v2 System |
|---------|-----------|-----------|
| **Generic Framework** | OpenWeatherMap-specific | Generic, reusable for any API |
| **Input Format** | Custom JSON structure | Standardized `CollectorInput` format |
| **Output Format** | Custom JSON structure | Standardized `GoldenDataScenario` format |
| **HTTP Recording** | Custom implementation | Uses `httpx` with custom transports |
| **Secret Masking** | Manual implementation | Built-in secret detection and masking |
| **Test Integration** | Custom test helpers | Standardized `GoldenDataProvider` |
| **Directory Structure** | Flat structure | Organized by method names |

## Migration Guide from v1 to v2

### 1. Input File Format

**v1 format** (`locations.json`):
```json
[
  {
    "city": "Minsk",
    "country_code": "BY",
    "description": "Capital of Belarus"
  }
]
```

**v2 format** (`locations_v2.json`):
```json
[
  {
    "description": "Minsk, BY",
    "kwargs": {
      "city": "Minsk",
      "country": "BY"
    }
  }
]
```

### 2. Collector Script

**v1 approach**:
- Custom collector script with manual HTTP recording
- Method-specific collection logic

**v2 approach**:
- Uses `collectGoldenData()` from `lib/golden_data/collector.py`
- Generic collector that dynamically imports classes and methods
- Automatic secret detection and masking

### 3. Test Files

**v1 approach**:
- Custom test helpers and fixtures
- Manual loading of golden data files

**v2 approach**:
- Uses `GoldenDataProvider` from `lib/golden_data/provider.py`
- Standardized pytest fixtures
- Automatic client creation with replay functionality

### 4. Golden Data Files

**v1 format**:
- Custom JSON structure with request/response pairs

**v2 format**:
- Standardized `GoldenDataScenario` format with metadata
- Better organization by method and test case
- Automatic filename generation

## Dynamic Class Import and Method Execution

The v2 system uses dynamic class import and method execution that conform to the generic collector pattern:

```json
{
  "description": "Get weather for Minsk, Belarus",
  "module": "lib.openweathermap.client",
  "class": "OpenWeatherMapClient",
  "init_kwargs": {
    "apiKey": "${OPENWEATHERMAP_API_KEY}",
    "cache": {
      "module": "lib.openweathermap.dict_cache",
      "class": "DictWeatherCache"
    }
  },
  "method": "getWeatherByCity",
  "kwargs": {
    "city": "Minsk",
    "country": "BY"
  }
}
```

The collector:
1. Dynamically imports the specified module and class
2. Instantiates the class with the provided init_kwargs (substituting environment variables)
3. Gets the specified method from the instance
4. Calls the method with the provided kwargs
5. Records all HTTP traffic during the method execution
6. Saves the recorded data with metadata

## API Key Handling

- The collector reads the API key from environment variable `OPENWEATHERMAP_API_KEY`
- The API key is automatically masked in all golden data files
- Tests don't need API keys since they replay recorded responses

## Backward Compatibility

- The v1 files are kept intact and continue to work
- The v2 system works alongside v1 without conflicts
- You can gradually migrate from v1 to v2 as needed

## Future Improvements

1. **Enhanced Test Coverage**: Add more test cases and edge cases
2. **Performance Testing**: Add performance benchmarks using golden data
3. **Error Case Testing**: Record and test error scenarios (404, 429, etc.)
4. **Multi-language Support**: Test with different language settings
5. **Extended Forecast Testing**: Test longer forecast periods