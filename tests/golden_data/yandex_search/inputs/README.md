# Yandex Search Golden Data Testing

This directory contains input data for the Yandex Search golden data collection system.

## Search Queries

The `search_queries.json` file contains a list of search queries to be used for collecting golden data. Each query has:

- `query`: The search query text
- `description`: A brief description of the query type

## Usage

To collect golden data:

1. Ensure you have a `.env` file with `YANDEX_SEARCH_API_KEY` and `YANDEX_SEARCH_FOLDER_ID` set
2. Run the collection script:
   ```bash
   ./venv/bin/python3 tests/golden_data/yandex_search/collect.py
   ```

The collected data will be saved to the `golden/` directory.