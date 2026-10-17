import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from chat.schemas import ChatFilters
from chat.services.analytics import run_analytics_tool
from chat.utils.llm_factory import LLMClient
from middleware.models import User


class AgentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["overview", "products", "sites", "comparison", "clarify"]
    metric: Literal["revenue", "units_sold", "orders"] = "revenue"
    clarification: str | None = Field(default=None, max_length=500)


class SQLAgentError(RuntimeError):
    """The agent could not safely produce an approved analytics operation."""


def format_analytics_answer(result: dict) -> str:
    metric_names = {
        "revenue": "net revenue",
        "units_sold": "units sold",
        "orders": "orders",
        "average_order_value": "average order value",
    }
    metric = result["metric"]
    if result["operation"] == "overview":
        if result["multiple_currencies"]:
            return "Your selected sites use multiple currencies. Select one site to compare revenue."
        values = result["metrics"]
        currency = result["currency"]
        amount = f"{values['revenue']:,.2f} {currency}" if currency else f"{values['revenue']:,.2f}"
        average_amount = (
            f"{values['average_order_value']:,.2f} {currency}"
            if currency
            else f"{values['average_order_value']:,.2f}"
        )
        return (
            f"From {result['filters']['start_date']} through {result['filters']['end_date']}, "
            f"net revenue was {amount}, across {values['orders']:,} orders and "
            f"{values['units_sold']:,} units; average order value was "
            f"{average_amount}."
        )
    if result["operation"] == "comparison":
        if result.get("multiple_currencies"):
            return "Your selected sites use multiple currencies. Select one site to compare revenue."
        current = result["current"]["metrics"][metric]
        previous = result["previous"]["metrics"][metric]
        formatter = (
            (lambda value: f"{value:,.2f}")
            if metric in {"revenue", "average_order_value"}
            else (lambda value: f"{value:,}")
        )
        if result["change_percent"] is None:
            return (
                f"From {result['filters']['start_date']} through {result['filters']['end_date']}, "
                f"{metric_names[metric]} was {formatter(current)} in the selected period and "
                f"{formatter(previous)} in the previous period; a percentage change is unavailable."
            )
        direction = "up" if result["change_percent"] > 0 else "down"
        return (
            f"From {result['filters']['start_date']} through {result['filters']['end_date']}, "
            f"{metric_names[metric]} was {formatter(current)} in the selected period, "
            f"{direction} {abs(result['change_percent']):.1f}% from {formatter(previous)} "
            "in the previous period."
        )

    if result.get("multiple_currencies") and metric in {
        "revenue",
        "average_order_value",
    }:
        return "Your selected sites use multiple currencies. Select one site before ranking by revenue."

    rows = result["rows"]
    if not rows:
        return "No matching sales data was found for the selected filters."
    lead = "Products" if result["operation"] == "products" else "Sites"
    details = "; ".join(
        f"{row['name']} ({row[metric]:,.2f}"
        f"{' ' + row['currency'] if metric in {'revenue', 'average_order_value'} else ''})"
        if metric in {"revenue", "average_order_value"}
        else f"{row['name']} ({row[metric]:,})"
        for row in rows[:5]
    )
    return (
        f"Top {lead.lower()} by {metric_names[metric]} from "
        f"{result['filters']['start_date']} through {result['filters']['end_date']}: "
        f"{details}."
    )


class SQLAgent:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    async def answer(
        self,
        db: Session,
        user: User,
        question: str,
        filters: ChatFilters,
    ) -> tuple[str, dict]:
        system = (
            "You classify sales analytics questions. Return only a JSON object with fields "
            '"operation" (overview, products, sites, comparison, or clarify), '
            '"metric" (revenue, units_sold, orders, or average_order_value), and optional "clarification". '
            "Never return SQL, extra fields, or answers. Use overview for totals, products or "
            "sites for rankings/breakdowns, comparison for period comparisons, and clarify "
            "when the question is not about sales analytics. Revenue means gross revenue "
            "minus discounts. Dashboard filters are fixed and must not be changed."
        )
        prompt = json.dumps({"question": question}, ensure_ascii=True)
        raw_plan = await self.client.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        )
        try:
            plan = AgentPlan.model_validate_json(raw_plan)
        except ValidationError as error:
            raise SQLAgentError(
                "The analytics agent returned an invalid query plan. Please retry."
            ) from error
        if plan.operation == "clarify":
            return (
                plan.clarification
                or "I can answer questions about sales totals, product or site rankings, and period comparisons.",
                {"operation": "clarify", "filters": filters.model_dump(mode="json")},
            )
        result = run_analytics_tool(db, user, plan.operation, plan.metric, filters)
        return format_analytics_answer(result), result
