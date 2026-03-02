#!/usr/bin/env python3
"""Convert eval results JSON to a markdown report.

Usage:
    python evals/format_report.py evals/results/eval_results.json > report.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

THRESHOLD = 0.7

# Provider logo mapping — maps OpenRouter provider prefixes to CDN logos
PROVIDER_LOGOS = {
    "anthropic": "https://cdn.mcp-use.com/claude.svg",
    "openai": "https://cdn.mcp-use.com/openai.svg",
    "google": "https://cdn.mcp-use.com/google.svg",
}


def _parse_model(model_id: str) -> tuple[str, str, str]:
    """Parse 'provider/model' into (provider, model_name, logo_url)."""
    if "/" in model_id:
        provider, model_name = model_id.split("/", 1)
    else:
        provider, model_name = "", model_id
    logo_url = PROVIDER_LOGOS.get(provider, "")
    return provider, model_name, logo_url


def _score_badge(score: float | None) -> str:
    """Render a score as a shields.io badge image."""
    if score is None:
        return "![N/A](https://img.shields.io/badge/N%2FA-grey)"

    pct = round(score * 100)
    if pct >= round(THRESHOLD * 100):
        color = "2da44e"
        label = "passing"
    elif pct >= round(THRESHOLD * 100) - 10:
        color = "d29922"
        label = "failing"
    else:
        color = "d1242f"
        label = "failing"

    return f"![{pct}%](https://img.shields.io/badge/{pct}%25-{label}-{color})"


def _provider_img(logo_url: str) -> str:
    """Render a provider logo as an inline image."""
    if not logo_url:
        return ""
    return f'<img src="{logo_url}" width="16" height="16">'


def _anchor(case_id: str, model: str, prompt: str) -> str:
    """Generate a unique anchor id for a result."""
    return f"{case_id}-{model}-{prompt}".replace("/", "-").replace(" ", "-").lower()


def generate_markdown(results: list[dict]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["success"])
    failed = total - passed

    lines = []

    # Total duration (from first result's metadata)
    total_time = results[0].get("total_duration_s", 0) if results else 0
    total_time_str = f"{total_time:.0f}s" if total_time else ""

    # Header
    lines.append("# Eval Report\n")
    summary_parts = []
    if passed == total:
        summary_parts.append(f"**All {total} evals passed**")
    else:
        summary_parts.append(f"**{passed}/{total} passed** — {failed} failed")
    if total_time_str:
        summary_parts.append(total_time_str)
    summary_parts.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append(f"> {' · '.join(summary_parts)}\n")

    # Table — compact, links to details below
    lines.append("| Score | Case | Query | Provider | Model | Prompt | Time | Details |")
    lines.append("|:-----:|:----:|:------|:--------:|:-----:|:------:|:----:|:-------:|")

    for r in results:
        judge = next((m for m in r["metrics"]), None)
        score_val = judge["score"] if judge and judge["score"] is not None else None
        badge = _score_badge(score_val)
        query = (r.get("input") or "").replace("|", "\\|")

        _, model_name, logo_url = _parse_model(r.get("model", ""))
        provider_cell = _provider_img(logo_url)
        duration = r.get("duration_s", 0)
        time_str = f"{duration:.0f}s" if duration else "-"

        anchor = _anchor(r["case_id"], r.get("model", ""), r["prompt_name"])
        detail_link = f"[View](#{anchor})"

        lines.append(
            f"| {badge} | `{r['case_id']}` | {query} | {provider_cell} "
            f"| `{model_name}` | {r['prompt_name']} | {time_str} | {detail_link} |"
        )

    # Full details below the table — all collapsed
    lines.append("\n### Details\n")
    for r in results:
        judge = next((m for m in r["metrics"]), None)
        score_val = judge["score"] if judge and judge["score"] is not None else None
        pct = f"{round(score_val * 100)}%" if score_val is not None else "N/A"
        icon = "✅" if r["success"] else "❌"
        comment = (judge.get("reason") or "No judge comment") if judge else "No judge comment"
        output = r.get("actual_output", "")

        anchor = _anchor(r["case_id"], r.get("model", ""), r["prompt_name"])

        lines.append(
            f'<details><summary id="{anchor}">'
            f"{icon} <code>{r['case_id']}</code> · "
            f"<code>{r.get('model', '')}</code> · "
            f"{r['prompt_name']} — {pct}</summary>\n"
        )
        lines.append(f"**Query:** {r.get('input', '')}\n")
        lines.append(f"**Judge:** {comment}\n")
        if output:
            lines.append(f"**Response:**\n\n{output}\n")
        lines.append("</details>\n")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        path = Path("evals/results/eval_results.json")
    else:
        path = Path(sys.argv[1])

    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        results = json.load(f)

    print(generate_markdown(results))


if __name__ == "__main__":
    main()
