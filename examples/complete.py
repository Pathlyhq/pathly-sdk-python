"""Examples for the Pathly Python SDK. Requires PATHLY_API_TOKEN."""

from __future__ import annotations

from pathly import Client, MaintenanceWindowInput, ScenarioInput, SlaTargetInput, WebhookInput


def main() -> None:
    client = Client()
    client.ping()

    scenario = client.create_scenario(
        ScenarioInput(
            name="Checkout funnel",
            url="https://shop.example.com/cart",
            intervalSec=300,
            expectedStatus=200,
            expectText="Your cart",
            severity="critical",
            tags=["prod", "payment"],
            runbook="https://wiki.example.com/ops/checkout",
        )
    )

    window = client.create_maintenance_window(
        MaintenanceWindowInput(
            monitorId=scenario.id,
            weekday=7,
            startMinute=180,
            durationMin=120,
            reason="Weekly backup",
        )
    )

    webhook = client.create_webhook(
        WebhookInput(
            url="https://hooks.example.com/pathly",
            events=["run.failed", "run.recovered"],
        )
    )
    # Store webhook.secret in your vault immediately — it is shown once.

    sla = client.upsert_sla_target(
        SlaTargetInput(
            monitorId=scenario.id,
            name="Checkout — 99.9 %",
            objectivePct=99.9,
            windowDays=30,
            excludeMaintenance=True,
            warnAtBudgetRatio=0.8,
        )
    )

    print(
        {
            "scenario": scenario.id,
            "window": window.id,
            "webhook": webhook.id,
            "sla": sla.id,
        }
    )


if __name__ == "__main__":
    main()
