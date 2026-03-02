#!/usr/bin/env python3
"""Generic MCP server eval runner using DeepEval.

Runs all eval cases in parallel — each case gets its own MCP server
subprocess (stdio) or connects to the same URL (http).

Usage:
    python run_evals.py \
      --server-config '{"command": "python", "args": ["-m", "my_server"]}' \
      --eval-cases eval_cases.yaml

    python run_evals.py \
      --server-config '{"url": "https://my-server.example.com/mcp"}' \
      --eval-cases eval_cases.yaml \
      --filter acquisitions
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"

import yaml
from mcp_use import MCPAgent
from mcp_use.client import MCPClient

from deepeval import evaluate
from deepeval.evaluate import DisplayConfig
from deepeval.metrics import GEval
from deepeval.models import OpenRouterModel
from deepeval.test_case import LLMTestCase, LLMTestCaseParams


def load_eval_cases(path: str) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def get_judge_model(config: dict) -> str:
    env = os.getenv("EVAL_JUDGE_MODEL")
    if env:
        return env
    return config.get("judge_model", "openai/gpt-4o-mini")


def get_models(config: dict) -> list[str]:
    env = os.getenv("EVAL_MODELS")
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    return config.get("models", ["openai/gpt-4o-mini"])


def create_judge(config: dict) -> OpenRouterModel:
    return OpenRouterModel(
        model=get_judge_model(config),
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )


def create_llm(model: str, temperature: float = 0):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        openai_api_key=os.getenv("OPENROUTER_API_KEY"),
        openai_api_base="https://openrouter.ai/api/v1",
    )


def _parse_server_config(server_config_json: str) -> dict:
    """Parse server config JSON with sensible defaults for MCP subprocess."""
    config = json.loads(server_config_json)
    if "env" not in config:
        config["env"] = {}
    config["env"].setdefault("MCP_USE_ANONYMIZED_TELEMETRY", "false")
    config["env"].setdefault("MCP_USE_DEBUG", "0")
    config["env"].setdefault("DEBUG", "0")
    config["env"].setdefault("SHOW_INSPECTOR_LOGS", "false")
    config["env"].setdefault("PRETTY_PRINT_JSONRPC", "false")
    return config


async def _run_single_eval(
    server_config: dict,
    case: dict,
    model_name: str,
    prompt_name: str,
    system_prompt: str,
    max_steps: int,
    index: int,
    total: int,
) -> tuple[LLMTestCase, dict]:
    """Run a single eval case with its own MCP client."""
    case_id = case["id"]
    print(f"[{index}/{total}] {case_id} | {model_name} | {prompt_name}", file=sys.stderr)

    client = MCPClient({"mcpServers": {"target": server_config}})
    await client.create_session("target")

    t0 = time.monotonic()
    try:
        agent = MCPAgent(
            llm=create_llm(model_name), client=client,
            max_steps=max_steps, system_prompt=system_prompt,
            memory_enabled=False,
        )
        response = await agent.run(case["prompt"]) or ""
    except Exception as e:
        print(f"  [{case_id}] ERROR: {e}", file=sys.stderr)
        response = f"[Agent error: {e}]"
    finally:
        await client.close_all_sessions()

    elapsed = time.monotonic() - t0
    print(f"  [{case_id}] {elapsed:.1f}s", file=sys.stderr)

    tc = LLMTestCase(
        input=case["prompt"],
        actual_output=response,
        additional_metadata={
            "case_id": case_id,
            "model": model_name,
            "prompt_name": prompt_name,
            "duration_s": round(elapsed, 1),
        },
    )
    return tc, case


async def run_evals(
    server_config_json: str,
    eval_cases_path: str,
    case_filter: str | None = None,
    max_steps: int = 30,
    parallel: bool = True,
) -> list[dict]:
    config = load_eval_cases(eval_cases_path)
    cases = config["cases"]
    today = datetime.now().strftime("%Y-%m-%d")
    prompts = {k: v.replace("{today}", today) for k, v in config["system_prompts"].items()}
    models = get_models(config)

    if case_filter:
        cases = [c for c in cases if case_filter in c["id"]]

    server_config = _parse_server_config(server_config_json)

    # Build list of all eval coroutines
    coros = []
    n = 0
    total = len(cases) * len(models) * len(prompts)
    for case in cases:
        for model_name in models:
            for prompt_name, system_prompt in prompts.items():
                n += 1
                coros.append(_run_single_eval(
                    server_config, case, model_name, prompt_name,
                    system_prompt, max_steps, n, total,
                ))

    if parallel:
        print(f"Running {total} evals in parallel...\n", file=sys.stderr)
        results_pairs = await asyncio.gather(*coros)
    else:
        print(f"Running {total} evals sequentially...\n", file=sys.stderr)
        results_pairs = [await c for c in coros]

    # Score each with GEval
    print(f"\nScoring {len(results_pairs)} results with DeepEval GEval...\n", file=sys.stderr)
    judge = create_judge(config)
    all_results = []

    for tc, case in results_pairs:
        metric = GEval(
            name="Response Quality",
            criteria=case["rubric"].strip(),
            evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
            threshold=case.get("threshold", 0.7),
            model=judge,
        )
        result = evaluate(
            test_cases=[tc], metrics=[metric],
            display_config=DisplayConfig(print_results=True, verbose_mode=False),
        )
        for tr in result.test_results:
            meta = tr.additional_metadata or {}
            metrics = [
                {"name": md.name, "score": md.score, "reason": md.reason, "success": md.success}
                for md in (tr.metrics_data or [])
            ]
            all_results.append({
                "case_id": meta.get("case_id", ""),
                "model": meta.get("model", ""),
                "prompt_name": meta.get("prompt_name", ""),
                "success": tr.success,
                "input": tr.input,
                "actual_output": tr.actual_output or "",
                "metrics": metrics,
                "duration_s": meta.get("duration_s", 0),
            })

    return all_results


def main():
    parser = argparse.ArgumentParser(description="Run MCP server agent evals")
    parser.add_argument("--server-config", required=True, help="MCP server config as JSON string")
    parser.add_argument("--eval-cases", required=True, help="Path to eval_cases.yaml")
    parser.add_argument("--filter", help="Filter cases by id substring")
    parser.add_argument("--output", default="eval-results.json", help="JSON output path")
    parser.add_argument("--max-steps", type=int, default=30, help="Max agent steps per case")
    parser.add_argument("--parallel", action="store_true", default=True, help="Run evals in parallel")
    parser.add_argument("--no-parallel", dest="parallel", action="store_false", help="Run evals sequentially")
    args = parser.parse_args()

    t_start = time.monotonic()
    results = asyncio.run(run_evals(
        args.server_config, args.eval_cases, args.filter, args.max_steps, args.parallel,
    ))
    total_time = time.monotonic() - t_start

    for r in results:
        r["total_duration_s"] = round(total_time, 1)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to {args.output} ({total_time:.1f}s total)", file=sys.stderr)

    if any(not r["success"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
