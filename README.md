# SCTEC Inventory Assistant

This project is part of the **SCTEC AI Agents course**. It answers stock questions in English and uses instructor **Wanderson Souza's** [stock API](https://github.com/wangsouza/api-estoque) for product data and his [course repository](https://github.com/wangsouza/agents-senai) as a reference for LangGraph, HTTP tools, and n8n.

[Download the demonstration (MP4)](evidence/inventory-demo.mp4?raw=1) · [View the recorded executions](evidence/executions.json)

## How the agent works

```mermaid
flowchart LR
    Start([START]) --> Interpret["Interpret question with the LLM"]
    Interpret -->|Lookup with one valid product code| Analyze["Call stock tool and analyze quantities"]
    Interpret -->|Explain, clarify, unsupported, or model error| End([END])
    Analyze --> End
```

The shared state carries the question, the validated code when present, and the result. The first node asks the LLM to distinguish an actual stock lookup from a conceptual question or an unsupported request. Python checks that a lookup has one unambiguous code. The conditional edge then either calls the stock node or finishes with a direct answer.

The stock node calls `lookup_product(code)` in [stock.py](inventory_agent/stock.py). That tool uses `GET /produtos/{codigo}`, checks the HTTP status, and validates the response with Pydantic. The LLM receives only the question. Python builds product answers from the validated quantities and unit returned by the official API.

| Condition | Stock level |
| --- | --- |
| Quantity equals zero | Out of stock |
| Positive quantity at or below the minimum | Low |
| Quantity above the minimum | Available |

The response includes `route`, `tool_called`, and the upstream HTTP status when available. These fields show which path actually ran. Both paths end after at most two nodes, and both HTTP clients use timeouts.

## Run locally

You need Python 3.11 or newer, Git, and an OpenAI-compatible chat model that accepts structured JSON output. The commands below use PowerShell.

### 1. Start the official stock API

Run these commands from the project folder in a separate terminal. The API has its own repository and virtual environment.

```powershell
git clone https://github.com/wangsouza/api-estoque.git api-estoque
Set-Location api-estoque
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The official API's Swagger is at [localhost:8000/docs](http://127.0.0.1:8000/docs).
If port 8000 is in use, start the stock API on another port and set `STOCK_API_URL` in the agent's `.env`. The recorded run used port 8002 for the stock API.

### 2. Start the model

For the same setup used in the demonstration, download and extract the [llama.cpp Windows CPU build](https://github.com/ggml-org/llama.cpp/releases/download/b12655/llama-b12655-bin-win-cpu-x64.zip) and download the [Qwen2.5-1.5B-Instruct Q4_K_M model file](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/blob/main/qwen2.5-1.5b-instruct-q4_k_m.gguf). In the directory containing `llama-server.exe`, run the following with the actual path to your GGUF file.

```powershell
.\llama-server.exe -m "C:\path\to\qwen2.5-1.5b-instruct-q4_k_m.gguf" --host 127.0.0.1 --port 8080 --alias qwen-inventory --ctx-size 2048
```

A hosted OpenAI-compatible provider can also be configured using `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` in `.env`. Keep API keys in that local file or in environment variables.

### 3. Start the agent

Run from this repository in a separate terminal.

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m uvicorn inventory_agent.main:app --env-file .env --host 127.0.0.1 --port 8001
```

Send a question through the [agent's Swagger UI](http://127.0.0.1:8001/docs) or PowerShell.

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/analyze `
  -ContentType application/json `
  -Body '{"question":"Is PRD-001 low on stock?"}' | ConvertTo-Json -Depth 5
```

## Run the n8n workflow

1. Open a local [n8n installation](https://docs.n8n.io/deploy/host-n8n/install-options/install-using-docker-compose/) and import [Inventory Analysis](n8n/inventory-analysis.json).
2. Check the URL in **Call Python Agent**. The default works when n8n runs on the same host. With n8n in Docker, use an address the container can reach, such as `http://host.docker.internal:8001/analyze` on Docker Desktop, and bind the agent to a reachable development interface.
3. Open **Receive Question**, click **Listen for test event**, and copy its Test URL. Send the same JSON used above to `http://127.0.0.1:5678/webhook-test/inventory-analysis`.
4. Inspect the request and response in n8n. If you publish the workflow, use its Production URL at `/webhook/inventory-analysis`.

The webhook passes the question to the Python endpoint and returns the last node's JSON. LangGraph owns the intent decision, API call, and answer.

The workflow was imported, executed, and exported with n8n 2.35.7 in Docker. The [verification run](https://github.com/renan-leme/ai-agents-SCTEC/actions/runs/45298329349) shows the actual webhook response and saved workflow execution.

## Reproduce the evaluation tests

Repeat the agent request above with each question. The [recorded executions](evidence/executions.json) include the inputs, expected and observed outcomes, and the n8n webhook execution.

| Scenario | Question | Expected result |
| --- | --- | --- |
| Existing product | Is PRD-001 low on stock? | Lookup, HTTP 200 from the stock API, quantity 5, minimum 10, low. |
| Missing product | Check the stock of PRD-999. | Lookup, HTTP 404 from the stock API, clear missing-product message. |
| Concept question | What does minimum stock mean? | Explanation and `tool_called: false`. |
| Upstream failure | Check the stock of PRD-503. | Lookup, HTTP 503 from the stock API, temporary-unavailability message. |

## Limitations

This is a single-question, single-product prototype. A product lookup needs a `PRD-XXX` code, and each request starts a fresh graph run. The tool has read-only access. The official API and the agent are intended for local course use. Intent classification depends on the configured model, and stock lookup depends on the official API being available.
