from __future__ import annotations

import time


REQUIRED_CHECKS = {
    "eye_protection": "Laser-safe eyewear is on everyone nearby.",
    "ventilation": "Ventilation or fume extraction is running.",
    "fire_watch": "A person is watching the job with extinguishing equipment nearby.",
    "material": "The material is known and clamped flat.",
    "enclosure": "The enclosure, shield, or controlled work area is closed.",
}


class SafetyLatch:
    def __init__(self) -> None:
        self._armed_until = 0.0
        self._armed_by = "local"

    def is_armed(self) -> bool:
        return time.time() < self._armed_until

    def arm(self, checklist: dict, minutes: int = 8) -> None:
        missing = [label for key, label in REQUIRED_CHECKS.items() if not checklist.get(key)]
        if missing:
            raise RuntimeError("Safety checklist is incomplete.")
        minutes = max(1, min(15, int(minutes)))
        self._armed_until = time.time() + minutes * 60

    def disarm(self) -> None:
        self._armed_until = 0.0

    def snapshot(self) -> dict:
        remaining = max(0, int(self._armed_until - time.time()))
        return {
            "armed": self.is_armed(),
            "remaining_seconds": remaining,
            "required_checks": REQUIRED_CHECKS,
            "armed_by": self._armed_by if self.is_armed() else None,
        }
