"""Typed payloads exchanged with the Pathly ``/v1`` API."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Mapping, Optional, Sequence


def _omit_none(data: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _from_mapping(cls: type, data: Mapping[str, Any] | None) -> Any:
    if data is None:
        return None
    names = {f.name for f in fields(cls)}
    return cls(**{k: data.get(k) for k in names})


@dataclass(slots=True)
class Scenario:
    id: str
    name: str
    type: str = "http"
    url: Optional[str] = None
    enabled: Optional[bool] = None
    intervalSec: Optional[int] = None
    method: Optional[str] = None
    expectedStatus: Optional[int] = None
    maxLatencyMs: Optional[int] = None
    expectText: Optional[str] = None
    runbook: Optional[str] = None
    cron: Optional[str] = None
    lastStatus: Optional[str] = None
    regions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    folder: Optional[str] = None
    severity: Optional[str] = None
    mutedUntil: Optional[str] = None
    scenarioFingerprint: Optional[str] = None
    createdAt: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Scenario:
        return _from_mapping(cls, data)


@dataclass(slots=True)
class ScenarioInput:
    name: Optional[str] = None
    type: Optional[str] = None
    url: Optional[str] = None
    intervalSec: Optional[int] = None
    method: Optional[str] = None
    expectedStatus: Optional[int] = None
    maxLatencyMs: Optional[int] = None
    expectText: Optional[str] = None
    regions: Optional[Sequence[str]] = None
    tags: Optional[Sequence[str]] = None
    folder: Optional[str] = None
    severity: Optional[str] = None
    runbook: Optional[str] = None
    cron: Optional[str] = None
    enabled: Optional[bool] = None
    scenario: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.regions is not None:
            payload["regions"] = list(self.regions)
        if self.tags is not None:
            payload["tags"] = list(self.tags)
        return _omit_none(payload)


@dataclass(slots=True)
class MaintenanceWindow:
    id: str
    monitorId: Optional[str] = None
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    reason: Optional[str] = None
    weekday: Optional[int] = None
    startMinute: Optional[int] = None
    durationMin: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaintenanceWindow:
        return _from_mapping(cls, data)


@dataclass(slots=True)
class MaintenanceWindowInput:
    monitorId: Optional[str] = None
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    reason: Optional[str] = None
    weekday: Optional[int] = None
    startMinute: Optional[int] = None
    durationMin: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(asdict(self))


@dataclass(slots=True)
class Webhook:
    id: str
    events: list[str] = field(default_factory=list)
    enabled: Optional[bool] = None
    hasSecret: Optional[bool] = None
    urlFingerprint: Optional[str] = None
    createdAt: Optional[str] = None
    secret: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Webhook:
        return _from_mapping(cls, data)


@dataclass(slots=True)
class WebhookInput:
    url: str
    events: Optional[Sequence[str]] = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"url": self.url}
        if self.events is not None:
            payload["events"] = list(self.events)
        return payload


@dataclass(slots=True)
class SlaTarget:
    id: str
    monitorId: Optional[str] = None
    name: Optional[str] = None
    objectivePct: Optional[float] = None
    windowDays: Optional[int] = None
    excludeMaintenance: Optional[bool] = None
    warnAtBudgetRatio: Optional[float] = None
    enabled: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SlaTarget:
        obj = _from_mapping(cls, data)
        if obj.objectivePct is not None:
            obj.objectivePct = float(obj.objectivePct)
        if obj.warnAtBudgetRatio is not None:
            obj.warnAtBudgetRatio = float(obj.warnAtBudgetRatio)
        return obj


@dataclass(slots=True)
class SlaTargetInput:
    objectivePct: float
    windowDays: int
    monitorId: Optional[str] = None
    name: Optional[str] = None
    excludeMaintenance: Optional[bool] = None
    warnAtBudgetRatio: Optional[float] = None
    enabled: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return _omit_none(payload)
