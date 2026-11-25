import json
import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from inventory_agent.llm import GEMINI_MODEL, GEMINI_URL, InterpretationError, interpret
from inventory_agent.main import app


def gemini_response(status: int = 200, **body) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", GEMINI_URL))


class GeminiTests(unittest.TestCase):
    def test_gemini_receives_the_intent_schema_and_returns_the_json_text(self):
        result = {"intent": "lookup", "explanation": ""}
        response = gemini_response(candidates=[{
            "finishReason": "STOP",
            "content": {"parts": [
                {"thought": True, "text": "Internal reasoning"},
                {"text": json.dumps(result)},
            ]},
        }])
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}),
            patch("inventory_agent.llm.httpx.post", return_value=response) as post,
        ):
            interpreted = interpret("Is PRD-001 low on stock?")

        self.assertEqual(interpreted.model_dump(), result)
        self.assertEqual(GEMINI_MODEL, "gemini-3.8-flash")
        self.assertTrue(post.call_args.args[0].endswith("/gemini-3.8-flash:generateContent"))
        self.assertEqual(post.call_args.kwargs["headers"], {"x-goog-api-key": "test-only"})
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "Is PRD-001 low on stock?")
        config = payload["generationConfig"]
        schema = config["responseFormat"]["text"]["schema"]
        self.assertEqual(set(schema["required"]), {"intent", "explanation"})
        self.assertEqual(set(schema["properties"]["intent"]["enum"]), {"lookup", "explain", "unsupported"})

    def test_missing_key_returns_a_controlled_error_without_using_either_api(self):
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": ""}),
            patch("inventory_agent.llm.httpx.post") as post,
            patch("inventory_agent.graph.lookup_product") as lookup,
        ):
            response = TestClient(app).post("/analyze", json={"question": "Check PRD-001."})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["route"], "model_error")
        self.assertIn("GEMINI_API_KEY", response.json()["answer"])
        self.assertFalse(response.json()["tool_called"])
        post.assert_not_called()
        lookup.assert_not_called()

    def test_rejects_incomplete_or_invalid_gemini_responses(self):
        responses = [
            gemini_response(candidates=[]),
            gemini_response(candidates=[{
                "finishReason": "MAX_TOKENS",
                "content": {"parts": [{"text": '{"intent":"lookup","explanation":""}'}]},
            }]),
            gemini_response(candidates=[{
                "finishReason": "STOP",
                "content": {"parts": [{"text": '{"intent":"delete","explanation":""}'}]},
            }]),
        ]
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}):
            for response in responses:
                with (
                    self.subTest(body=response.json()),
                    patch("inventory_agent.llm.httpx.post", return_value=response),
                    self.assertRaisesRegex(InterpretationError, "valid interpretation"),
                ):
                    interpret("Check PRD-001.")

    def test_reports_rate_limits_without_exposing_gemini_error_details(self):
        response = gemini_response(429, error={"message": "internal diagnostic"})
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}),
            patch("inventory_agent.llm.httpx.post", return_value=response),
            self.assertRaisesRegex(InterpretationError, "^The Gemini API quota or rate limit was reached[.]$"),
        ):
            interpret("Check PRD-001.")
