"""HTTP entry point shared by direct callers and the n8n workflow."""

from typing import Annotated

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, StringConstraints

from inventory_agent.graph import Analysis, inventory_graph

app = FastAPI(title="SCTEC Inventory Assistant")


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]


@app.post("/analyze", response_model=Analysis, response_model_exclude_none=True)
def analyze(request: AnalysisRequest) -> Analysis:
    """Analyze a question and return the answer plus observable routing information."""
    state = inventory_graph.invoke({"question": request.question})
    return state["result"]
