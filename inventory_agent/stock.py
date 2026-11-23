"""Read-only Python tool for the instructor's stock API."""

import os
import re
from typing import Annotated

import httpx
from pydantic import BaseModel, Field

PRODUCT_CODE = re.compile(r"PRD-[0-9]{3}")
StockCount = Annotated[int, Field(strict=True, ge=0)]


class Product(BaseModel):
    """The public fields the agent needs to analyze one product."""

    code: str = Field(validation_alias="codigo")
    name: str = Field(validation_alias="nome", min_length=1)
    quantity: StockCount = Field(validation_alias="quantidade_atual")
    minimum: StockCount = Field(validation_alias="estoque_minimo")
    unit: str = Field(validation_alias="unidade", min_length=1)


class StockLookupError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def lookup_product(code: str) -> Product:
    """Given a PRD-XXX code, return validated stock data or a safe lookup error."""
    if not PRODUCT_CODE.fullmatch(code):
        raise StockLookupError("Use a product code in the PRD-123 format.")

    base_url = os.getenv("STOCK_API_URL", "http://127.0.0.1:8000").rstrip("/")
    try:
        response = httpx.get(f"{base_url}/produtos/{code}", timeout=5.0)
    except httpx.TimeoutException:
        raise StockLookupError("The stock API took too long to respond.") from None
    except (httpx.RequestError, httpx.InvalidURL):
        raise StockLookupError("The stock API could not be reached.") from None

    status = response.status_code
    if status == 404:
        raise StockLookupError(f"Product {code} was not found.", status)
    if status == 422:
        raise StockLookupError("The stock API rejected the product code.", status)
    if status >= 500:
        raise StockLookupError("The stock API is temporarily unavailable.", status)
    if status != 200:
        raise StockLookupError("The stock API returned an unexpected status.", status)

    try:
        product = Product.model_validate(response.json())
        if product.code != code:
            raise ValueError("The response is for a different product.")
    except ValueError:
        # Invalid JSON and Pydantic validation errors have the same user-facing result.
        raise StockLookupError("The stock API returned invalid product data.", status) from None

    return product
