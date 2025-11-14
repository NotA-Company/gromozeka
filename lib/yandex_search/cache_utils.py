"""TODO: Write all docstrings"""

import lib.utils as utils
from lib.cache import JsonKeyGenerator

from .models import SearchRequest


class SearchRequestKeyGenerator(JsonKeyGenerator[SearchRequest]):
    """TODO"""

    def generateKey(self, obj: SearchRequest) -> str:
        """TODO"""

        # Create a normalized representation of the request
        # Exclude folderId from cache key as it's constant per client
        cacheData = {
            "query": obj["query"],
            "sortSpec": obj.get("sortSpec", None),
            "groupSpec": obj.get("groupSpec", None),
            "maxPassages": obj.get("maxPassages", None),
            "region": obj.get("region", None),
            "l10n": obj.get("l10n", None),
        }

        return super().generateKey(cacheData)

        # Sort and serialize to ensure consistent keys
        jsonStr = utils.jsonDumps(cacheData)
        return jsonStr
