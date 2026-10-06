"""Pure gesture logic (no camera / OS deps) so it can be unit-tested."""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

# MediaPipe hand landmark indices
WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP = 0, 5, 9, 13, 17
FINGERS = ((6, 8), (10, 12), (14, 16), (18, 20))  # (pip, tip) for index..pinky


def palm_center(lm) -> tuple[float, float]:
    pts = [lm[i] for i in (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)]
    return sum(p.x for p in pts) / len(pts), sum(p.y for p in pts) / len(pts)


def hand_size(lm) -> float:
    """Wrist -> middle-finger knuckle distance; scales thresholds with distance to camera."""
    return math.dist((lm[WRIST].x, lm[WRIST].y), (lm[MIDDLE_MCP].x, lm[MIDDLE_MCP].y))


def is_open_palm(lm) -> bool:
    """All four fingers extended (tip farther from wrist than its pip joint)."""
    w = (lm[WRIST].x, lm[WRIST].y)
    return all(
        math.dist(w, (lm[t].x, lm[t].y)) > math.dist(w, (lm[p].x, lm[p].y)) * 1.1
        for p, t in FINGERS
    )


@dataclass
class SwipeDetector:
    window_s: float = 0.6       # swipe must complete within this time
    min_travel: float = 1.5      # horizontal travel in hand-sizes
    min_speed: float = 3.5       # mean hand-sizes/second; rejects slow repositioning / return strokes
    # Right-handed outward swipes are shorter/slower; separate thresholds for rightward motion.
    # Tuned from real data: deliberate swipes dx>=1.1 & speed>=1.9, casual returns dx<=0.9 & speed<=1.6.
    right_travel: float = 1.1
    right_speed: float = 1.9
    max_slope: float = 0.8       # |dy| / |dx| limit, rejects diagonal/vertical motion
    cooldown_s: float = 0.9      # ignore motion after a trigger (also swallows the return stroke)
    _hist: deque = field(default_factory=deque)
    _blocked_until: float = 0.0
    speed: float = 0.0           # speed of the last trigger (for debugging)
    reject: str = ""            # why the last candidate motion was rejected (for debugging)
    travel: float = 0.0          # latest horizontal travel in hand-sizes (for debugging)

    def reset(self) -> None:
        self._hist.clear()

    def update(self, t: float, x: float, y: float, size: float) -> str | None:
        """Feed one palm sample. Returns 'left'/'right' (direction hand moved in the image) or None."""
        self.reject = ""
        if t < self._blocked_until or size <= 0:
            return None
        self._hist.append((t, x, y))
        while self._hist and t - self._hist[0][0] > self.window_s:
            self._hist.popleft()
        if len(self._hist) < 3:
            return None
        t0, x0, y0 = self._hist[0]
        dx, dy = (x - x0) / size, (y - y0) / size
        self.travel = dx
        speed = abs(dx) / max(t - t0, 1e-3)
        need_travel, need_speed = (self.right_travel, self.right_speed) if dx > 0 else (self.min_travel, self.min_speed)
        self.reject = ""
        if abs(dx) >= 0.6:
            self.reject = " ".join(r for r, bad in (
                (f"short(need {need_travel:.2f})", abs(dx) < need_travel),
                (f"slow({speed:.1f}<{need_speed:.1f})", speed < need_speed),
                (f"arc(dy={dy:+.2f})", abs(dy) > self.max_slope * abs(dx))) if bad)
        if abs(dx) >= need_travel and abs(dy) <= self.max_slope * abs(dx) and speed >= need_speed:
            self.speed = speed
            self._hist.clear()
            self._blocked_until = t + self.cooldown_s
            return "right" if dx > 0 else "left"
        return None


@dataclass
class ArmToggle:
    """Hold a still open palm for `hold_s` to flip armed/disarmed."""
    hold_s: float = 1.0
    max_speed: float = 0.6       # hand-sizes per second counted as "still"
    armed: bool = False
    _since: float | None = None
    _last: tuple[float, float, float] | None = None
    _latched: bool = False       # must drop the pose before toggling again

    def progress(self, t: float) -> float:
        return 0.0 if self._since is None else min(1.0, (t - self._since) / self.hold_s)

    def update(self, t: float, open_palm: bool, x: float, y: float, size: float) -> bool:
        """Returns True on the frame the state flips."""
        speed = 0.0
        if self._last and size > 0 and t > self._last[0]:
            speed = math.hypot(x - self._last[1], y - self._last[2]) / size / (t - self._last[0])
        self._last = (t, x, y)
        if not open_palm:
            self._latched = False
        if not open_palm or speed > self.max_speed or self._latched:
            self._since = None
            return False
        if self._since is None:
            self._since = t
        if t - self._since >= self.hold_s:
            self.armed = not self.armed
            self._since, self._latched = None, True
            return True
        return False

    def lost(self) -> None:
        self._since, self._last, self._latched = None, None, False
