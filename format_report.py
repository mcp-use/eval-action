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


# ── Formatting helpers ───────────────────────────────────────────────────────


def _parse_model(model_id: str) -> tuple[str, str, str]:
    """Return (provider, model_name, logo_url) from a model ID like 'openai/gpt-4o'."""
    provider, _, model_name = model_id.partition("/")
    if not model_name:
        provider, model_name = "", provider
    return provider, model_name, PROVIDER_LOGOS.get(provider, "")


def _score_badge(score: float | None) -> str:
    if score is None:
        return '<img src="https://img.shields.io/badge/N%2FA-grey" alt="N/A">'
    pct = round(score * 100)
    passing = round(THRESHOLD * 100)
    color, label = (
        ("2da44e", "passing") if pct >= passing else
        ("d29922", "failing") if pct >= passing - 10 else
        ("d1242f", "failing")
    )
    return f'<img src="https://img.shields.io/badge/{pct}%25-{label}-{color}" alt="{pct}%">'


def _provider_img(logo_url: str) -> str:
    if not logo_url:
        return ""
    return f'<img src="{logo_url}" width="16" height="16">'


def _anchor(case_id: str, model: str, prompt: str) -> str:
    return f"{case_id}-{model}-{prompt}".replace("/", "-").replace(" ", "-").lower()


def _pct_str(score: float | None) -> str:
    return f"{round(score * 100)}%" if score is not None else "N/A"


def _get_judge(result: dict) -> dict | None:
    return next(iter(result.get("metrics", [])), None)


def _format_expected_val(val: object) -> str:
    """Format an expected arg value for display in markdown."""
    match val:
        case {"contains": substr}:
            return f"contains `{substr}`"
        case {"pattern": pat}:
            return f"matches `{pat}`"
        case _:
            return f"`{val}`"


# ── Tool assertion formatting ────────────────────────────────────────────────


def _format_tool_check(check: dict) -> str:
    """Format a single tool assertion check as a markdown list item."""
    icon = "✅" if check["passed"] else "❌"
    parts = [f"- {icon} `{check['tool']}` — {check.get('reason', '')}"]

    expected = check.get("expected_args")
    if expected:
        args_str = ", ".join(
            f"`{k}`: {_format_expected_val(v)}" for k, v in expected.items()
        )
        parts[0] += f" (expected {args_str})"

    actual_args = check.get("actual_args", []) if not check["passed"] else []
    for a in actual_args:
        actual_str = ", ".join(f"`{k}`=`{v}`" for k, v in a.items())
        parts.append(f"  - Got: {actual_str}")

    return "\n".join(parts)


def _format_tool_assertions_section(tool_assertions: dict) -> list[str]:
    """Format the full tool assertions detail section. Returns lines."""
    checks = tool_assertions.get("checks", [])
    if not checks:
        return []

    status = "✅ Passed" if tool_assertions.get("passed") else "❌ Failed"
    lines = [f"#### Tool Assertions — {status}\n"]
    lines.extend(_format_tool_check(c) for c in checks)
    lines.append("")
    return lines


def _format_tools_cell(tool_assertions: dict) -> str:
    """Format the Tools column cell for the summary table."""
    checks = tool_assertions.get("checks", [])
    if not checks:
        return "—"
    icon = "✅" if tool_assertions.get("passed") else "❌"
    passed_count = sum(1 for c in checks if c["passed"])
    return f"{icon} {passed_count}/{len(checks)}"


# ── Report generation ────────────────────────────────────────────────────────


def _generate_header(results: list[dict]) -> list[str]:
    total = len(results)
    passed = sum(1 for r in results if r["success"])
    failed = total - passed
    total_time = results[0].get("total_duration_s", 0) if results else 0

    lines = ["# Eval Report\n"]
    parts = []
    parts.append(
        f"**All {total} evals passed**" if passed == total
        else f"**{passed}/{total} passed** — {failed} failed"
    )
    if total_time:
        parts.append(f"{total_time:.0f}s")
    parts.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append(f"> {' · '.join(parts)}\n")
    return lines


def _generate_table(results: list[dict], show_tools_col: bool) -> list[str]:
    lines = ["<table>", "<tr>"]

    headers = ["Score", "Case", "Provider", "Model", "Prompt"]
    if show_tools_col:
        headers.append("Tools")
    headers.extend(["Time", "Details"])
    lines.extend(f'<th align="center">{h}</th>' for h in headers)
    lines.append("</tr>")

    for r in results:
        judge = _get_judge(r)
        score_val = judge["score"] if judge and judge["score"] is not None else None
        _, model_name, logo_url = _parse_model(r.get("model", ""))
        duration = r.get("duration_s", 0)
        anchor = _anchor(r["case_id"], r.get("model", ""), r["prompt_name"])

        cells = [
            f'<td align="center">{_score_badge(score_val)}</td>',
            f'<td><code>{r["case_id"]}</code></td>',
            f'<td align="center">{_provider_img(logo_url)}</td>',
            f'<td><code>{model_name}</code></td>',
            f'<td align="center">{r["prompt_name"]}</td>',
        ]
        if show_tools_col:
            cells.append(
                f'<td align="center">{_format_tools_cell(r.get("tool_assertions", {}))}</td>'
            )
        cells.extend([
            f'<td align="center">{f"{duration:.0f}s" if duration else "-"}</td>',
            f'<td align="center"><a href="#{anchor}">View</a></td>',
        ])

        lines.append("<tr>")
        lines.extend(cells)
        lines.append("</tr>")

    lines.append("</table>\n")
    return lines


def _generate_details(results: list[dict]) -> list[str]:
    lines = ["### Details\n"]

    for r in results:
        judge = _get_judge(r)
        score_val = judge["score"] if judge and judge["score"] is not None else None
        pct = _pct_str(score_val)
        icon = "✅" if r["success"] else "❌"
        comment = (judge.get("reason") or "No judge comment") if judge else "No judge comment"
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

        lines.extend(_format_tool_assertions_section(r.get("tool_assertions", {})))

        output = r.get("actual_output", "")
        if output:
            lines.append("#### Agent Response\n")
            lines.append(f"```\n{output}\n```\n")

        lines.append("</details>\n")

    return lines


def generate_markdown(results: list[dict]) -> str:
    show_tools_col = any(
        r.get("tool_assertions", {}).get("checks") for r in results
    )
    lines = []
    lines.extend(_generate_header(results))
    lines.extend(_generate_table(results, show_tools_col))
    lines.extend(_generate_details(results))
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    path = Path(sys.argv[1]) if len(sys.argv) >= 2 else Path("evals/results/eval_results.json")

    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        results = json.load(f)

    print(generate_markdown(results))


if __name__ == "__main__":
    main()
