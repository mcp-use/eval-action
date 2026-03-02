# MCP Server Eval Action

A reusable GitHub Action to run LLM-as-judge evaluations against any MCP server.

## Usage

```yaml
- uses: mcp-use/eval-action@v1
  with:
    server_config: '{"command": "python", "args": ["-m", "my_mcp_server", "--transport", "stdio"]}'
    eval_cases: "evals/eval_cases.yaml"
    openrouter_api_key: ${{ secrets.OPENROUTER_API_KEY }}
```

### Remote server

```yaml
- uses: mcp-use/eval-action@v1
  with:
    server_config: '{"url": "https://my-server.example.com/mcp"}'
    eval_cases: "evals/eval_cases.yaml"
    openrouter_api_key: ${{ secrets.OPENROUTER_API_KEY }}
```

### With environment variables for the server

```yaml
- uses: mcp-use/eval-action@v1
  with:
    server_config: |
      {
        "command": "python",
        "args": ["-m", "my_mcp_server", "--transport", "stdio"],
        "env": {
          "MONGO_PASSWORD": "${{ secrets.MONGO_PASSWORD }}",
          "USE_FAKE_DB": "false"
        }
      }
    eval_cases: "evals/eval_cases.yaml"
    openrouter_api_key: ${{ secrets.OPENROUTER_API_KEY }}
```

### Post results as PR comment

```yaml
- uses: mcp-use/eval-action@v1
  id: evals
  with:
    server_config: '{"command": "python", "args": ["-m", "my_server", "--transport", "stdio"]}'
    eval_cases: "evals/eval_cases.yaml"
    openrouter_api_key: ${{ secrets.OPENROUTER_API_KEY }}

- uses: marocchino/sticky-pull-request-comment@v2
  if: always() && github.event_name == 'pull_request'
  with:
    header: mcp-evals
    path: ${{ steps.evals.outputs.report_md }}

- run: cat ${{ steps.evals.outputs.report_md }} >> "$GITHUB_STEP_SUMMARY"
  if: always()
```

## Inputs

| Input | Required | Description |
|-------|----------|-------------|
| `server_config` | Yes | MCP server config as JSON (`{"command": ...}` or `{"url": ...}`) |
| `eval_cases` | Yes | Path to `eval_cases.yaml` |
| `openrouter_api_key` | Yes | OpenRouter API key for agent + judge LLM |
| `filter` | No | Filter cases by id substring |
| `max_steps` | No | Max agent steps per case (default: 30) |

## Outputs

| Output | Description |
|--------|-------------|
| `results_json` | Path to eval results JSON file |
| `report_md` | Path to markdown report file |
| `passed` | `true` if all evals passed, `false` otherwise |

## Eval cases YAML format

```yaml
# Model used by the LLM judge to score responses
judge_model: openai/gpt-4o-mini

# Models to evaluate the agent with (OpenRouter format)
models:
  - anthropic/claude-sonnet-4
  - openai/gpt-4o-mini

# System prompts — each case runs once per prompt
system_prompts:
  neutral: "You are a helpful assistant."
  domain: "You are a domain expert. Use the available tools."

# Eval cases
cases:
  - id: my_test_case
    prompt: "Ask the agent something"
    rubric: |
      The response should contain relevant information.
      The response should be well-structured.
    threshold: 0.7
```
