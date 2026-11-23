"""The LangGraph flow and the inventory rules applied to verified data."""

import re
from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from inventory_agent.llm import InterpretationError, interpret
from inventory_agent.stock import PRODUCT_CODE, Product, StockLookupError, lookup_product


class Analysis(BaseModel):
    route: Literal["lookup", "explain", "clarify", "unsupported", "model_error"]
    answer: str
    tool_called: bool = False
    stock_api_status: int | None = None
    stock_level: Literal["available", "low", "out_of_stock"] | None = None
    product: Product | None = None


class InventoryState(TypedDict):
    question: str
    code: NotRequired[str]
    result: NotRequired[Analysis]


def interpret_request(state: InventoryState) -> dict:
    """Use the LLM to decide whether the user needs product data."""
    question = state["question"]
    try:
        decision = interpret(question)
    except InterpretationError as error:
        return {"result": Analysis(route="model_error", answer=str(error))}

    if decision.intent == "unsupported":
        return {
            "result": Analysis(
                route="unsupported",
                answer="I can look up product stock or explain inventory concepts.",
            )
        }
    if decision.intent == "explain":
        answer = decision.explanation.strip()
        if answer:
            return {"result": Analysis(route="explain", answer=answer)}
        return {
            "result": Analysis(
                route="model_error", answer="The language model did not provide an explanation."
            )
        }

    # Only accept a code actually supplied by the user. Ask if it is ambiguous.
    codes = set(re.findall(r"\bPRD-[\w-]*", question.upper(), flags=re.ASCII))
    if len(codes) == 1:
        code = next(iter(codes))
        if PRODUCT_CODE.fullmatch(code):
            return {"code": code}

    return {
        "result": Analysis(
            route="clarify",
            answer="Please provide one product code in the PRD-123 format.",
        )
    }


def next_step(state: InventoryState) -> Literal["lookup", "finish"]:
    return "lookup" if state.get("code") else "finish"


def analyze_stock(state: InventoryState) -> dict:
    """Call the Python tool and apply the stock rule without asking the LLM for facts."""
    try:
        product = lookup_product(state["code"])
    except StockLookupError as error:
        return {
            "result": Analysis(
                route="lookup",
                answer=str(error),
                tool_called=True,
                stock_api_status=error.status_code,
            )
        }

    # Zero takes precedence. A positive quantity at the minimum still needs attention.
    if product.quantity == 0:
        level, label = "out_of_stock", "out of stock"
    elif product.quantity <= product.minimum:
        level, label = "low", "low"
    else:
        level, label = "available", "available"

    return {
        "result": Analysis(
            route="lookup",
            answer=(
                f"{product.name} ({product.code}) has {product.quantity} {product.unit} in stock "
                f"(minimum: {product.minimum} {product.unit}). Its stock level is {label}."
            ),
            tool_called=True,
            stock_api_status=200,
            stock_level=level,
            product=product,
        )
    }


builder = StateGraph(InventoryState)
builder.add_node("interpret_request", interpret_request)
builder.add_node("analyze_stock", analyze_stock)
builder.add_edge(START, "interpret_request")
builder.add_conditional_edges(
    "interpret_request", next_step, {"lookup": "analyze_stock", "finish": END}
)
builder.add_edge("analyze_stock", END)
inventory_graph = builder.compile()
