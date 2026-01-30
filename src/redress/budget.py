import threading
import time
from collections import deque


class Budget:
    """
    Thread-safe rolling window budget for retry attempts.

    Each consume() call records a retry token. When the number of tokens in the
    rolling time window exceeds max_retries, consume() returns False.
    """

    def __init__(self, *, max_retries: int, window_s: float) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0.")
        if window_s <= 0:
            raise ValueError("window_s must be > 0.")
        self.max_retries = max_retries
        self.window_s = window_s
        self._lock = threading.Lock()
        self._events: deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()

    def consume(self, cost: int = 1) -> bool:
        if cost < 1:
            raise ValueError("cost must be >= 1.")
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._events) + cost > self.max_retries:
                return False
            for _ in range(cost):
                self._events.append(now)
            return True

    def remaining(self) -> int:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            return max(self.max_retries - len(self._events), 0)
