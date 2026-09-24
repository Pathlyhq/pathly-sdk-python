"""Official Python SDK for the Pathly public ``/v1`` API."""

from __future__ import annotations

from pathly._version import __version__
from pathly.client import Client, DEFAULT_BASE_URL
from pathly.errors import APIError, NotFoundError, is_not_found
from pathly.models import (
    MaintenanceWindow,
    MaintenanceWindowInput,
    Scenario,
    ScenarioInput,
    SlaTarget,
    SlaTargetInput,
    Webhook,
    WebhookInput,
)

__all__ = [
    "APIError",
    "Client",
    "DEFAULT_BASE_URL",
    "MaintenanceWindow",
    "MaintenanceWindowInput",
    "NotFoundError",
    "Scenario",
    "ScenarioInput",
    "SlaTarget",
    "SlaTargetInput",
    "Webhook",
    "WebhookInput",
    "is_not_found",
    "__version__",
]
