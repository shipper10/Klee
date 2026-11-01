"""Normalized Daily Notes data, independent of genshin.py's models (so it is cacheable and testable)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class ExpeditionInfo:
    remaining_seconds: int

    @property
    def finished(self) -> bool:
        return self.remaining_seconds <= 0


@dataclass
class NotesData:
    current_resin: int
    max_resin: int
    resin_recovery_seconds: int
    current_realm_currency: int
    max_realm_currency: int
    realm_currency_recovery_seconds: int
    completed_commissions: int
    max_commissions: int
    claimed_commission_reward: bool
    remaining_resin_discounts: int
    max_resin_discounts: int
    transformer_recovery_seconds: int | None
    max_expeditions: int
    expeditions: list[ExpeditionInfo] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "NotesData":
        data = dict(data)
        data["expeditions"] = [ExpeditionInfo(**e) for e in data.get("expeditions", [])]
        return cls(**data)

    @classmethod
    def from_genshin(cls, notes: Any) -> "NotesData":
        """Convert a `genshin.models.Notes` object. Field names verified against genshin.py 1.7.31."""
        transformer = notes.remaining_transformer_recovery_time
        return cls(
            current_resin=int(notes.current_resin),
            max_resin=int(notes.max_resin),
            resin_recovery_seconds=int(notes.remaining_resin_recovery_time.total_seconds()),
            current_realm_currency=int(notes.current_realm_currency),
            max_realm_currency=int(notes.max_realm_currency),
            realm_currency_recovery_seconds=int(notes.remaining_realm_currency_recovery_time.total_seconds()),
            completed_commissions=int(notes.completed_commissions),
            max_commissions=int(notes.max_commissions),
            claimed_commission_reward=bool(notes.claimed_commission_reward),
            remaining_resin_discounts=int(notes.remaining_resin_discounts),
            max_resin_discounts=int(notes.max_resin_discounts),
            transformer_recovery_seconds=(
                int(transformer.total_seconds()) if transformer is not None else None
            ),
            max_expeditions=int(notes.max_expeditions),
            expeditions=[
                ExpeditionInfo(remaining_seconds=int(e.remaining_time.total_seconds()))
                for e in notes.expeditions
            ],
        )
