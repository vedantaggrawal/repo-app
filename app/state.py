"""Process-local runtime state.

Deliberately in-memory and per-pod: it resets on restart and is not shared
between replicas, which is exactly what makes it useful for demonstrating pod
identity and rollout behaviour on the cluster.
"""

import time


class RuntimeState:
    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self._started_wall = time.time()
        # Flipped to False by the demo endpoint to show a pod being pulled out
        # of Service endpoints without being killed.
        self.ready = True

    @property
    def uptime_seconds(self) -> float:
        return round(time.monotonic() - self._started_at, 3)

    @property
    def started_at_epoch(self) -> float:
        return self._started_wall


state = RuntimeState()
