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

PROVIDER_LOGOS = {
    "anthropic": "https://cdn.mcp-use.com/claude.svg",
    "openai": "https://cdn.mcp-use.com/openai.svg",
    "google": "https://cdn.mcp-use.com/google.svg",
}


def _parse_model(model_id: str) -> tuple[str, str, str]:
    if "/" in model_id:
        provider, model_name = model_id.split("/", 1)
    else:
        provider, model_name = "", model_id
    return provider, model_name, PROVIDER_LOGOS.get(provider, "")


def _score_badge(score: float | None) -> str:
    if score is None:
        return '<img src="https://img.shields.io/badge/N%2FA-grey" alt="N/A">'
    pct = round(score * 100)
    if pct >= round(THRESHOLD * 100):
        color, label = "2da44e", "passing"
    elif pct >= round(THRESHOLD * 100) - 10:
        color, label = "d29922", "failing"
    else:
        color, label = "d1242f", "failing"
    return f'<img src="https://img.shields.io/badge/{pct}%25-{label}-{color}" alt="{pct}%">'


def _provider_img(logo_url: str) -> str:
    if not logo_url:
        return ""
    return f'<img src="{logo_url}" width="16" height="16">'


def _anchor(case_id: str, model: str, prompt: str) -> str:
    return f"{case_id}-{model}-{prompt}".replace("/", "-").replace(" ", "-").lower()


def generate_markdown(results: list[dict]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r["success"])
    failed = total - passed

    total_time = results[0].get("total_duration_s", 0) if results else 0
    total_time_str = f"{total_time:.0f}s" if total_time else ""

    lines = []

    # Header
    lines.append("# Eval Report\n")
    parts = []
    if passed == total:
        parts.append(f"**All {total} evals passed**")
    else:
        parts.append(f"**{passed}/{total} passed** — {failed} failed")
    if total_time_str:
        parts.append(total_time_str)
    parts.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append(f"> {' · '.join(parts)}\n")

    # HTML table
    lines.append("<table>")
    lines.append("<tr>")
    for h in ["Score", "Case", "Provider", "Model", "Prompt", "Time", "Details"]:
        lines.append(f'<th align="center">{h}</th>')
    lines.append("</tr>")

    for r in results:
        judge = next((m for m in r["metrics"]), None)
        score_val = judge["score"] if judge and judge["score"] is not None else None
        badge = _score_badge(score_val)

        _, model_name, logo_url = _parse_model(r.get("model", ""))
        duration = r.get("duration_s", 0)
        time_str = f"{duration:.0f}s" if duration else "-"
        anchor = _anchor(r["case_id"], r.get("model", ""), r["prompt_name"])

        lines.append("<tr>")
        lines.append(f'<td align="center">{badge}</td>')
        lines.append(f'<td><code>{r["case_id"]}</code></td>')
        lines.append(f'<td align="center">{_provider_img(logo_url)}</td>')
        lines.append(f'<td><code>{model_name}</code></td>')
        lines.append(f'<td align="center">{r["prompt_name"]}</td>')
        lines.append(f'<td align="center">{time_str}</td>')
        lines.append(f'<td align="center"><a href="#{anchor}">View</a></td>')
        lines.append("</tr>")

    lines.append("</table>\n")

    # Details section — all collapsed
    lines.append("### Details\n")
    for r in results:
        judge = next((m for m in r["metrics"]), None)
        score_val = judge["score"] if judge and judge["score"] is not None else None
        pct = f"{round(score_val * 100)}%" if score_val is not None else "N/A"
        icon = "✅" if r["success"] else "❌"
        comment = (judge.get("reason") or "No judge comment") if judge else "No judge comment"
        output = r.get("actual_output", "")
        anchor = _anchor(r["case_id"], r.get("model", ""), r["prompt_name"])

        lines.append(
            f'<details>\n<summary id="{anchor}">'
            f'{icon} <code>{r["case_id"]}</code> · '
            f'<code>{r.get("model", "")}</code> · '
            f'{r["prompt_name"]} — {pct}</summary>\n'
        )
        lines.append(f"#### Query\n")
        lines.append(f'> {r.get("input", "")}\n')
        lines.append(f"#### Judge — {pct}\n")
        lines.append(f"> {comment}\n")
        if output:
            lines.append(f"#### Agent Response\n")
            lines.append(f"```\n{output}\n```\n")
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
