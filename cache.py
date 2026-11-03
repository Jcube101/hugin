import time
from collections import OrderedDict

MISSING = object()  # returned by get() for "not cached" (None can be a real cached value)


class TTLCache:
    """Small in-memory cache: entries expire after `ttl` seconds, and the least
    recently used entry is dropped once there are more than `maxsize`.

    Lives in the uvicorn process, so it empties on restart. That's fine: it only
    saves repeat calls to TMDb and OMDb.
    """

    def __init__(self, ttl: float, maxsize: int = 2000):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: OrderedDict = OrderedDict()

    def get(self, key):
        item = self._data.get(key)
        if item is None:
            return MISSING
        value, expires = item
        if time.monotonic() >= expires:
            del self._data[key]
            return MISSING
        self._data.move_to_end(key)
        return value

    def set(self, key, value):
        self._data[key] = (value, time.monotonic() + self.ttl)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self):
        self._data.clear()

    def __len__(self):
        return len(self._data)
