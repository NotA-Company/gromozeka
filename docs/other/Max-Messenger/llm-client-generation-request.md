Yo, dood. We need to add Max Messenger bot client as lib.max_bot using `httpx` as client
There is OpenAPI 3.0 specification:
`docs/other/Max-Messenger/swagger.json`

Your work is to:
1. Analyze swagger
2. Think, how to split implementation to several phases (as there are lots of things in API)
3. Write general implementation design document
4. Write several implementation plans (for each phase)
5. Show me those documents for review
6. Fix everything I'll say (if any)
7. Implement it step-by-step

Also:
* Do not forget to save all comments\desctription from OpenAPI file into docstrings in python code
* We'll use dataclasses (with slotted=True) for model purposes, and add api_kwargs: Dict[str, Any] for each of them with raw API responsed JSON (for debug purposes)
* use httpx as http client
* use async functions where possible
* split client to multiple files for easier understanding

If you have any questions - ask