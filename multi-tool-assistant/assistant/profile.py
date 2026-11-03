"""Saved user profile: used for personalised replies, default city and temperature units."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

UNIT_CHOICES = {"celsius", "fahrenheit"}


@dataclass
class UserProfile:
    name: str = "there"
    home_city: str | None = "Tokyo"  # default for a Japan-focused assistant
    units: str = "celsius"

    def __post_init__(self) -> None:
        if self.units not in UNIT_CHOICES:
            raise ValueError("units must be celsius or fahrenheit")

    def update(self, **changes) -> "UserProfile":
        known = {f.name for f in fields(self)}
        for key, value in changes.items():
            if key not in known:
                raise KeyError(f"unknown profile field: {key}")
            setattr(self, key, value)
        self.__post_init__()  # re-validate after changes
        return self

    def format_temp(self, celsius: float | None) -> str:
        if celsius is None:
            return "n/a"
        if self.units == "fahrenheit":
            return f"{celsius * 9 / 5 + 32:.0f}°F"
        return f"{celsius:.0f}°C"

    def to_prompt(self) -> str:
        parts = [f"Address the user as {self.name}.", f"Use {self.units} when giving temperatures."]
        if self.home_city:
            parts.append(f"Their home city is {self.home_city}.")
        return " ".join(parts)

    @classmethod
    def load(cls, path: str | Path) -> "UserProfile":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
