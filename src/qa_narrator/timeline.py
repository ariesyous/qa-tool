"""One monotonic clock, with paused intervals removed from the audio time axis."""

import threading
import time


class Timeline:
    def __init__(self, clock=time.perf_counter_ns):
        self.clock = clock
        self._lock = threading.RLock()
        self.origin = clock()
        self.intervals = [[self.origin, None]]
        self.state = "recording"

    def elapsed(self, at=None):
        at = self.clock() if at is None else at
        with self._lock:
            return (
                sum(
                    max(0, min(end or at, at) - start)
                    for start, end in self.intervals
                    if start < at
                )
                / 1e9
            )

    def transition(self, state):
        with self._lock:
            allowed = {
                "recording": {"paused", "stopped"},
                "paused": {"recording", "stopped"},
                "stopped": set(),
            }
            if state not in allowed[self.state]:
                raise ValueError(f"Cannot move from {self.state} to {state}")
            now = self.clock()
            if self.state == "recording":
                self.intervals[-1][1] = now
            if state == "recording":
                self.intervals.append([now, None])
            self.state = state
            return {"kind": state, "t": self.elapsed(now), "monotonic_ns": now - self.origin}

    def slices(self, start_ns, frames, rate):
        """Return (destination frame, source start, source end) for a captured buffer.

        Buffers crossing pause/resume boundaries are cropped at sample precision.
        Destination offsets retain startup/device gaps as silence instead of shifting speech.
        """
        end_ns = start_ns + frames / rate * 1e9
        with self._lock:
            result, accumulated = [], 0
            for start, end in self.intervals:
                stop = end if end is not None else end_ns
                left, right = max(start, start_ns), min(stop, end_ns)
                if right > left:
                    a = max(0, min(frames, round((left - start_ns) / 1e9 * rate)))
                    b = max(a, min(frames, round((right - start_ns) / 1e9 * rate)))
                    dest = round((accumulated + left - start) / 1e9 * rate)
                    if b > a:
                        result.append((dest, a, b))
                accumulated += max(0, stop - start)
            return result
