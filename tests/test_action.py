"""Exercise the action's Bash step without calling an MCP server or an LLM."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())
RUN_STEP = next(step for step in ACTION["runs"]["steps"] if step.get("id") == "evals")


class ActionParallelTests(unittest.TestCase):
    def run_action(self, parallel=None, runner_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            bin_dir = work / "bin"
            bin_dir.mkdir()
            runner = bin_dir / "python"
            runner.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path('argv.json').write_text(json.dumps(sys.argv[1:]))\n"
                "Path('eval-results.json').write_text('[]')\n"
                "sys.exit(int(os.environ['TEST_RUNNER_EXIT']))\n"
            )
            runner.chmod(0o755)
            env = {
                "PATH": f"{bin_dir}{os.pathsep}{os.defpath}",
                "GITHUB_OUTPUT": str(work / "outputs"),
                "SERVER_CONFIG": '{"url":"http://localhost:3000/mcp"}',
                "EVAL_CASES": "eval_cases.yaml",
                "EVAL_FILTER": "",
                "EVAL_MAX_STEPS": "30",
                "EVAL_PARALLEL": ACTION["inputs"]["parallel"]["default"]
                if parallel is None else parallel,
                "TEST_RUNNER_EXIT": str(runner_exit),
            }
            script = RUN_STEP["run"].replace("${{ github.action_path }}", str(ROOT))
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (
                result,
                json.loads((work / "argv.json").read_text()),
                (work / "outputs").read_text(),
            )

    def test_false_requests_sequential_execution(self):
        result, args, outputs = self.run_action("false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-parallel", args)
        self.assertNotIn("--parallel", args)
        self.assertIn("passed=true\n", outputs)

    def test_default_and_true_preserve_parallel_execution(self):
        for parallel in (None, "true"):
            with self.subTest(parallel=parallel):
                result, args, outputs = self.run_action(parallel)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--parallel", args)
                self.assertNotIn("--no-parallel", args)
                self.assertIn("passed=true\n", outputs)

    def test_sequential_runner_failure_is_propagated(self):
        result, args, outputs = self.run_action("false", runner_exit=3)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("--no-parallel", args)
        self.assertIn("results_json=eval-results.json\n", outputs)
        self.assertIn("passed=false\n", outputs)


if __name__ == "__main__":
    unittest.main()
