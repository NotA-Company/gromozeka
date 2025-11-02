# Yandex Search Golden Test Input Scenarios

This directory contains input scenarios for the Yandex Search golden tests. These scenarios define the search queries and parameters that will be used to generate golden data for testing the Yandex Search client.

## Purpose of this Directory

The input directory contains structured test scenarios that define what search queries should be executed against the Yandex Search API. These scenarios are used by the golden test framework to:

1. Execute search queries against the real Yandex Search API
2. Capture the responses as golden data
3. Use the captured data for future regression testing

## Format of scenarios.json

The scenarios are defined in a JSON file with the following structure:

```json
{
  "scenarios": [
    {
      "name": "string - Unique identifier for the scenario",
      "query": "string - The search query to execute",
      "params": {
        "lang": "string - Language for the search (optional)",
        "region": "string - Region for the search (optional)",
        // Other Yandex Search API parameters
      }
    }
  ]
}
```

## How to Add New Scenarios

1. Add a new entry to the scenarios array in `scenarios.json`
2. Ensure each scenario has a unique name
3. Define the search query and any additional parameters
4. Run the golden test collection process to generate the corresponding golden data

Example of adding a new scenario:
```json
{
  "name": "Python programming tutorial",
  "query": "python programming tutorial",
  "params": {
    "lang": "en",
    "region": "US"
  }
}
```

## Environment Variables

The following environment variables may be needed for executing the scenarios:

- `YANDEX_SEARCH_API_KEY` - API key for accessing the Yandex Search API
- `YANDEX_SEARCH_BASE_URL` - Base URL for the Yandex Search API (optional, defaults to production)

## Example Scenario Structure

```json
{
  "scenarios": [
    {
      "name": "Simple query in English",
      "query": "python programming",
      "params": {
        "lang": "en"
      }
    },
    {
      "name": "Query in Russian",
      "query": "программирование на Python",
      "params": {
        "lang": "ru"
      }
    },
    {
      "name": "Query with numbers",
      "query": "python 3.9 tutorial",
      "params": {
        "lang": "en"
      }
    },
    {
      "name": "Query with special characters",
      "query": "python programming",
      "params": {
        "lang": "en"
      }
    }
  ]
}
```

## Best Practices

1. Use descriptive names for scenarios that clearly indicate what is being tested
2. Include a variety of query types (different languages, special characters, etc.)
3. Add scenarios for edge cases and error conditions
4. Keep scenarios focused on specific functionality to make debugging easier
5. Regularly review and update scenarios to reflect changes in the API or requirements