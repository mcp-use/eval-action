# MCP Server Eval Action

A reusable GitHub Action that runs **LLM-as-judge evaluations** against any MCP server. Define your test cases in a YAML file, and the action will spin up your server, run an AI agent against each prompt, score the responses with an LLM judge, and optionally verify the agent called the right tools with the right arguments.

Works with any MCP server — stdio or remote — and any model available on [OpenRouter](https://openrouter.ai/models).

## How it works

```
eval_cases.yaml ──► Agent runs prompt ──► LLM judge scores response ──► Report
                         │                        │
                         │                        ├── Rubric score (GEval)
                         ▼                        └── Tool assertions (programmatic)
                    MCP Server
```

1. For each `(case × model × system_prompt)` combination, a fresh MCP agent is created
2. The agent runs the prompt against your MCP server (each case gets its own server instance)
3. [DeepEval's GEval](https://docs.confident-ai.com/metrics-g-eval) scores the agent's response against your rubric
4. If `required_tools` are defined, the action verifies the agent called the correct tools with the expected arguments
5. A case passes only if **both** the rubric score meets the threshold **and** all tool assertions pass
6. Results are output as JSON and a markdown report, ready to post as a PR comment

## Quick start

### 1. Create `evals/eval_cases.yaml` in your repo

```yaml
judge_model: openai/gpt-4o

models:
  - anthropic/claude-sonnet-4
  - openai/gpt-4o-mini

system_prompts:
  neutral: "You are a helpful assistant."

cases:
  - id: basic_query
    prompt: "What are the top items in the database?"
    rubric: |
      The response should list items from the database.
      Each item should include a name and relevant details.
    threshold: 0.7
```

### 2. Add the workflow

```yaml
name: MCP Server Evals

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  pull-requests: write
  contents: read

jobs:
  evals:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4

      # Install your MCP server's dependencies
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - uses: astral-sh/setup-uv@v5
      - run: uv pip install --system -r requirements.txt

      # Run evals
      - uses: mcp-use/eval-action@v1.4
        id: evals
        with:
          server_config: |
            {
              "command": "python",
              "args": ["-m", "my_mcp_server", "--transport", "stdio"],
              "env": {
                "API_KEY": "${{ secrets.API_KEY }}"
              }
            }
          eval_cases: evals/eval_cases.yaml
          openrouter_api_key: ${{ secrets.OPENROUTER_API_KEY }}

      # Post results as a sticky PR comment
      - uses: marocchino/sticky-pull-request-comment@v2
        if: always() && github.event_name == 'pull_request'
        with:
          header: mcp-evals
          path: ${{ steps.evals.outputs.report_md }}

      # Also show in GitHub Actions summary
      - run: cat ${{ steps.evals.outputs.report_md }} >> "$GITHUB_STEP_SUMMARY"
        if: always()

      # Upload artifacts for later inspection
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: eval-results
          path: |
            ${{ steps.evals.outputs.results_json }}
            ${{ steps.evals.outputs.report_md }}
          retention-days: 30
```

### 3. Add your OpenRouter API key

Go to **Settings → Secrets and variables → Actions** and add `OPENROUTER_API_KEY`.

That's it. Every PR will now get an eval report as a comment.

## Eval cases YAML reference

The `eval_cases.yaml` file defines everything: which models to test, which prompts to run, and how to score the results.

```yaml
# ── Judge configuration ──────────────────────────────────────────────────────
# The model that scores agent responses. Can be overridden with
# the EVAL_JUDGE_MODEL env var.
judge_model: openai/gpt-4o

# ── Models under test ────────────────────────────────────────────────────────
# Each case runs once per model. Use OpenRouter model IDs.
# Can be overridden with EVAL_MODELS env var (comma-separated).
models:
  - anthropic/claude-sonnet-4
  - openai/gpt-4o-mini

# ── System prompts ───────────────────────────────────────────────────────────
# Each case runs once per prompt. Use this to compare how the agent
# behaves with different instructions.
# The placeholder {today} is replaced with the current date (YYYY-MM-DD).
system_prompts:
  neutral: "You are a helpful assistant."
  domain: "You are a domain expert. Today is {today}. Use the available tools."

# ── Test cases ───────────────────────────────────────────────────────────────
cases:
  - id: my_test_case          # Unique identifier (used in reports and --filter)
    prompt: "Ask the agent something"
    rubric: |                  # What a good response looks like (scored by LLM judge)
      The response should contain relevant information.
      The response should be well-structured.
    required_tools:            # (Optional) Tools the agent must call
      - lookup_item
      - name: search_records
        args:
          category: "electronics"
    threshold: 0.7             # Minimum GEval score to pass (0.0 – 1.0)
```

With 3 cases × 2 models × 2 prompts, you get 12 eval runs.

### Rubrics

The rubric is a plain-text description of what a good response looks like. The LLM judge reads the agent's **final text response** and scores it against the rubric. Keep rubrics focused on observable qualities of the response:

```yaml
rubric: |
  The response should list items ranked by relevance.
  Each entry should include a name and a brief description.
  The response should not include internal database IDs.
```

The judge does **not** see tool calls — only the final response. For verifying tool usage, use `required_tools` (see below).

### Tool assertions

Tool assertions verify the agent called specific tools during execution. They are checked **programmatically** against the agent's conversation history — no LLM involved.

A case passes only if **both** the rubric score meets the threshold **and** all tool assertions pass.

#### Simple form — just check the tool was called

```yaml
required_tools:
  - resolve_category
  - search_records
```

#### With argument matching

```yaml
required_tools:
  - name: lookup_item
    args:
      query: { contains: "widget" }   # case-insensitive substring
  - name: search_records
    args:
      region: "us-east"               # exact match (case-insensitive)
```

If the tool was called multiple times (e.g., `search_records` with `region: "us-east"` and then with `region: "eu-west"`), the assertion passes as long as **at least one call** matches the expected arguments.

#### Argument matching modes

| Form | Example | Behavior |
|------|---------|----------|
| Plain string | `region: "us-east"` | Exact match, case-insensitive |
| `contains` | `query: { contains: "widget" }` | Case-insensitive substring match |
| `pattern` | `query: { pattern: "widget.*pro" }` | Regex match, case-insensitive |
| `any` | `query: "any"` | Passes if the argument key exists (any value) |

#### Combining simple and detailed forms

You can mix both forms in the same list:

```yaml
required_tools:
  - resolve_category                     # just check it was called
  - name: lookup_item
    args:
      query: { contains: "widget" }      # check name + args
  - name: search_records
    args:
      region: "us-east"
  - name: search_records
    args:
      region: "eu-west"
```

## Action inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `server_config` | Yes | — | MCP server config as JSON (see examples below) |
| `eval_cases` | Yes | — | Path to `eval_cases.yaml` |
| `openrouter_api_key` | Yes | — | OpenRouter API key for both the agent LLM and the judge |
| `filter` | No | `""` | Run only cases whose id contains this substring |
| `max_steps` | No | `30` | Maximum agent steps (tool calls) per case |
| `parallel` | No | `true` | Run cases in parallel (each gets its own server instance) |

## Action outputs

| Output | Description |
|--------|-------------|
| `results_json` | Path to `eval-results.json` — full structured results |
| `report_md` | Path to `eval-report.md` — markdown report for PR comments |
| `passed` | `"true"` if all evals passed, `"false"` otherwise |

## Server configuration

### Stdio server (subprocess)

The action starts your server as a subprocess for each eval case:

```json
{
  "command": "python",
  "args": ["-m", "my_mcp_server", "--transport", "stdio"],
  "env": {
    "DATABASE_URL": "postgres://...",
    "API_KEY": "secret"
  }
}
```

### Remote server (HTTP)

Connect to an already-running MCP server:

```json
{
  "url": "https://my-server.example.com/mcp"
}
```

## Environment variable overrides

These env vars override the corresponding YAML fields:

| Env var | Overrides | Example |
|---------|-----------|---------|
| `EVAL_JUDGE_MODEL` | `judge_model` | `openai/gpt-4o` |
| `EVAL_MODELS` | `models` | `anthropic/claude-sonnet-4,openai/gpt-4o-mini` |

## Report format

The generated markdown report includes:

**Summary table** with one row per eval run:

| Score | Case | Provider | Model | Prompt | Tools | Time | Details |
|-------|------|----------|-------|--------|-------|------|---------|
| Badge with % | Case ID | Provider logo | Model name | Prompt name | Pass/fail count | Duration | Link |

The **Tools** column only appears when at least one case has `required_tools` defined.

**Collapsible details** for each run, containing:
- The original query
- Judge score and reasoning
- Tool assertion results (if applicable) — per-tool pass/fail with expected vs actual arguments
- Full agent response

### Score badges

| Badge | Meaning |
|-------|---------|
| Green (>= 70%) | Passing |
| Orange (60–69%) | Failing (close to threshold) |
| Red (< 60%) | Failing |

## Full example

Here's a complete `eval_cases.yaml` showing all features:

```yaml
judge_model: openai/gpt-4o

models:
  - anthropic/claude-sonnet-4
  - openai/gpt-4o-mini

system_prompts:
  neutral: "You are a helpful assistant."

cases:
  # Simple case — rubric only, no tool assertions
  - id: list_popular
    prompt: "What are the most popular items right now?"
    rubric: |
      The response should list items with counts or rankings.
      The data should be current.
    threshold: 0.7

  # Case with tool assertions — simple form
  - id: category_search
    prompt: "Show me everything in the electronics category."
    rubric: |
      The response should list items from the electronics category.
      Each item should include a name and price.
    required_tools:
      - resolve_category
      - search_records
    threshold: 0.7

  # Case with tool assertions — argument matching
  - id: specific_lookup
    prompt: "Find details about the Widget Pro in the US store."
    rubric: |
      The response should contain detailed product information.
      It should mention availability and pricing.
    required_tools:
      - name: lookup_item
        args:
          query: { contains: "widget" }
      - name: search_records
        args:
          region: "us-east"
    threshold: 0.7

  # Case with multiple tool calls of the same type
  - id: cross_region_compare
    prompt: "Compare Widget Pro availability in the US and EU."
    rubric: |
      The response should compare availability across both regions.
    required_tools:
      - name: lookup_item
        args:
          query: { contains: "widget" }
      - name: search_records
        args:
          region: "us-east"
      - name: search_records
        args:
          region: "eu-west"
    threshold: 0.7
```

## Running locally

You can run the eval scripts directly without GitHub Actions:

```bash
# Install dependencies
pip install mcp_use langchain-core langchain-openai deepeval pyyaml

# Set your API key
export OPENROUTER_API_KEY="sk-or-..."

# Run all cases
python run_evals.py \
  --server-config '{"command": "python", "args": ["-m", "my_server", "--transport", "stdio"]}' \
  --eval-cases eval_cases.yaml \
  --output results.json

# Run a single case
python run_evals.py \
  --server-config '{"command": "python", "args": ["-m", "my_server", "--transport", "stdio"]}' \
  --eval-cases eval_cases.yaml \
  --filter specific_lookup \
  --output results.json

# Generate markdown report
python format_report.py results.json > report.md
```

### CLI options

```
python run_evals.py \
  --server-config JSON     # MCP server config (required)
  --eval-cases PATH        # Path to eval_cases.yaml (required)
  --output PATH            # Output JSON path (default: eval-results.json)
  --filter STRING          # Filter cases by id substring
  --max-steps N            # Max agent steps per case (default: 30)
  --parallel               # Run in parallel (default)
  --no-parallel            # Run sequentially
```

## Results JSON schema

Each entry in `eval-results.json`:

```json
{
  "case_id": "specific_lookup",
  "model": "anthropic/claude-sonnet-4",
  "prompt_name": "neutral",
  "success": true,
  "rubric_passed": true,
  "tools_passed": true,
  "input": "Find details about the Widget Pro in the US store.",
  "actual_output": "Here are the details for Widget Pro...",
  "metrics": [
    {
      "name": "Response Quality",
      "score": 0.85,
      "reason": "The response covers all requested details...",
      "success": true
    }
  ],
  "tool_calls": [
    { "name": "lookup_item", "args": { "query": "Widget Pro" } },
    { "name": "search_records", "args": { "region": "us-east", "item": "Widget Pro" } }
  ],
  "tool_assertions": {
    "passed": true,
    "checks": [
      { "tool": "lookup_item", "passed": true, "reason": "called with matching args", "expected_args": { "query": { "contains": "widget" } } },
      { "tool": "search_records", "passed": true, "reason": "called with matching args", "expected_args": { "region": "us-east" } }
    ]
  },
  "duration_s": 12.3,
  "total_duration_s": 45.0
}
```
