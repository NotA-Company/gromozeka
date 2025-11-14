# Geocode Maps API Client
We need to create client for geocode maps api. 
Downloaded and converted to Markdown API reference you can find in [Geocode-Maps-API.md](docs/other/Geocode-Maps-API.md).

Before creating client you need to analyze lib.opemweathermap and lib.yandex_search for different implementation things.

We need to:
1. use httpx as http client
2. use lib.cache for cache (or caches)
3. use lib.rate_limiter for rate limiter (default queue is `geocode-maps`)
4. use `Authorization: Bearer YOUR_SECRET_API_KEY` HTTP Header for authentication
5. use `jsonv2` as output format.
6. You can see example of `/search` response in [search-Angarsk-jsonv2.json](docs/other/search-Angarsk-jsonv2.json)
7. You can see example of `/reverse` response in [reverse-Angarsk-jsonv2.json](docs/other/reverse-Angarsk-jsonv2.json)
8. You can see example of `/lookup` response in [lookup-Angarsk-jsonv2.json](docs/other/lookup-Angarsk-jsonv2.json)
9. Use method `_makeRequest` (or something like it) for making requests (to have only one point of request)
10. add ability to set `accept-language` globaly per instance