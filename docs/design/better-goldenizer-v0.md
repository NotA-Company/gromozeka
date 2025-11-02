Yo dood. We've done with golden collector for openweathermap and Yandex Search, but for it we had to patch whole _makeRequest method there and I want to make some more general solution.

Can we instead somehow patch\wrap httpx get/post methods.

So you need to:
1. investigate this thing.
2. Write design proposal
3. Write thing to patch\wrap httpx methods
4. write collector, which can collect golden data for given method and given data (like: we have json file with array of dicts, where wi have `description` field (we'll use it for file name generation) and `kwargs` dict with all method arguments) and this collector will execute given function/method with kwargs from file, intercept httpx calls and write:
 * url, params, body (json), headers from request
 * resoponse (raw + status)
 * metadata (date, description, kwargs, which function were called)

Also it should mask in resulting data everything was passed as secret (just replace in resulting text).

5. Thing, which will get golden data and function/method for calling + kwargs and uses golden data on httpx methods calling
6. Add using it with openweathermap
7. Ask me to run collector to collect golden data
8. add some simple tests as usage example