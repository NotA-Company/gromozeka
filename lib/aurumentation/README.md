# Golden Data Collector

A generic collector for recording HTTP traffic from any function/method for testing purposes.

## Overview

This package provides a generic collector that can work with any function/method by reading test scenarios from a JSON file and collecting golden data. It uses httpx transport layer patching to intercept all HTTP calls made by any httpx-based client.

## Installation

The collector is part of the golden_data package. No additional installation is required.

## Usage

### As a Module

```python
from lib.golden_data import collectGoldenData

async def testFunction(city: str, country: str, client: httpx.AsyncClient):
    # Your function implementation here
    # Use the provided client for HTTP requests
    pass

summary = await collectGoldenData(
    inputFile="path/to/scenarios.json",
    targetFunction=testFunction,
    outputDir="path/to/output",
    secrets=["secret1", "secret2"]  # Optional: secrets to mask
)
```

### As CLI

```bash
python -m lib.golden_data.cli \
    --input path/to/scenarios.json \
    --output path/to/output \
    --module your.module.path \
    --function functionName \
    --secrets secret1,secret2
```

### CLI Arguments

- `--input` or `-i`: Path to input JSON file with test scenarios (required)
- `--output` or `-o`: Output directory for golden data files (required)
- `--module` or `-m`: Python module path containing the target function (required)
- `--function` or `-f`: Function name to test (required)
- `--secrets` or `-s`: Comma-separated list of secrets to mask (optional)

## Input Format

The input JSON file should contain an array of objects with the following structure:

```json
[
  {
    "description": "Description of the test scenario",
    "kwargs": {
      "param1": "value1",
      "param2": "value2"
    }
  }
]
```

## Output Format

Each scenario generates a JSON file in the output directory with the following structure:

```json
{
  "description": "Description of the test scenario",
  "function_name": "name_of_function",
  "kwargs": {
    "param1": "value1",
    "param2": "value2"
  },
  "calls": [
    {
      "request": {
        "method": "GET",
        "url": "https://api.example.com/endpoint",
        "headers": {"header": "value"},
        "params": {"param": "value"},
        "body": "request body"
      },
      "response": {
        "status_code": 200,
        "headers": {"header": "value"},
        "content": "response content"
      },
      "timestamp": "2023-01-01T00:00:00Z"
    }
  ],
  "created_at": "2023-01-01T00:00:00Z"
}
```

## Secret Masking

Sensitive data can be automatically masked in the recorded data. Secrets can be provided explicitly or detected from environment variables with common names like `API_KEY`, `TOKEN`, etc.

## Example

```bash
python -m lib.golden_data.cli \
    --input tests/golden_data/openweathermap/inputs/locations.json \
    --output tests/golden_data/openweathermap/golden \
    --module lib.openweathermap.client \
    --function getWeatherByCity \
    --secrets $OPENWEATHERMAP_API_KEY