"""Pure local tests for the OJ4-A Actions routing contract."""

import pathlib  # noqa: I001
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
CLASSIFIER_PATH = ROOT / "scripts" / "ci" / "classify_changes.py"
CLASSIFIER = {"__name__": "ci_classifier"}
CLASSIFIER_SOURCE = CLASSIFIER_PATH.read_text(encoding="utf-8")
exec(
    compile(CLASSIFIER_SOURCE, str(CLASSIFIER_PATH), "exec"),
    CLASSIFIER,
)
classify_paths = CLASSIFIER["classify_paths"]
route_for = CLASSIFIER["route_for"]
targeted_test_roots = CLASSIFIER["targeted_test_roots"]


def _git(repo_root: pathlib.Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class CiCostGovernanceTests(unittest.TestCase):
    def route(self, event: str, draft: bool, *paths: str) -> dict[str, bool]:
        return route_for(event, draft, classify_paths(paths))

    def test_draft_python_uses_fast_lane_without_coverage(self) -> None:
        route = self.route("pull_request", True, "src/openjarvis/core/config.py")
        self.assertTrue(route["draft_fast_lane"])
        self.assertFalse(route["full_ci_required"])
        self.assertTrue(route["run_python_targeted"])
        self.assertFalse(route["run_python_full"])
        self.assertFalse(route["run_windows_313"])

    def test_draft_codex_or_integration_change_is_targeted(self) -> None:
        route = self.route("pull_request", True, "src/openjarvis/integrations/codex.py")
        self.assertTrue(route["run_codex_targeted"])
        self.assertFalse(route["run_python_targeted"])
        self.assertFalse(route["run_python_full"])

    def test_draft_rust_change_runs_one_rust_gate(self) -> None:
        route = self.route(
            "pull_request", True, "rust/crates/openjarvis-python/src/lib.rs"
        )
        self.assertTrue(route["run_rust"])
        self.assertFalse(route["run_python_full"])
        self.assertFalse(route["run_windows_313"])

    def test_windows_sensitive_draft_is_limited_to_312(self) -> None:
        route = self.route(
            "pull_request", True, "tests/hardware/test_hardware_profiles.py"
        )
        self.assertTrue(route["run_windows_312"])
        self.assertFalse(route["run_windows_313"])

    def test_docs_only_draft_skips_heavy_docs_build(self) -> None:
        route = self.route(
            "pull_request", True, "docs/project/CURRENT-PROJECT-STATE.md"
        )
        self.assertFalse(route["docs_build_required"])
        self.assertFalse(route["run_python_targeted"])

    def test_ready_pr_runs_full_gate(self) -> None:
        route = self.route("pull_request", False, "docs/index.md")
        self.assertTrue(route["full_ci_required"])
        self.assertTrue(route["run_python_full"])
        self.assertTrue(route["run_windows_312"])
        self.assertTrue(route["run_windows_313"])
        self.assertTrue(route["docs_build_required"])

    def test_synchronize_ready_pr_has_same_full_route(self) -> None:
        first = self.route("pull_request", False, "src/openjarvis/cli/main.py")
        second = self.route("pull_request", False, "src/openjarvis/cli/main.py")
        self.assertEqual(first, second)

    def test_push_main_and_dispatch_run_full(self) -> None:
        for event in ("push", "workflow_dispatch"):
            with self.subTest(event=event):
                route = self.route(event, False, "README.md")
                self.assertTrue(route["full_ci_required"])
                self.assertTrue(route["run_python_full"])

    def test_workflow_or_classifier_change_activates_governance(self) -> None:
        flags = classify_paths([".github/workflows/ci.yml"])
        route = route_for("pull_request", True, flags)
        self.assertTrue(flags["workflow_changed"])
        self.assertTrue(route["run_governance"])
        self.assertTrue(route["draft_fast_lane"])
        self.assertFalse(route["full_ci_required"])

    def test_gate_and_security_contracts_are_static(self) -> None:
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        docs = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
        self.assertIn("ci-gate:", ci)
        self.assertIn("if: always()", ci)
        self.assertIn("skipped", ci)
        self.assertNotIn("pull_request_target", ci)
        self.assertNotIn("deploy", ci.lower())
        self.assertIn("github.event_name != 'pull_request'", docs)
        self.assertIn("if: github.event_name == 'pull_request'", docs)
        self.assertNotIn("github.event.pull_request.title", ci + docs)

    def test_targeted_roots_are_bounded_to_existing_tests(self) -> None:
        roots = targeted_test_roots(
            [
                "src/openjarvis/cli/main.py",
                "tests/ops/test_ci_cost_governance.py",
                "tests/deleted.py",
            ],
            ROOT,
        )
        self.assertIn("tests/cli", roots)
        self.assertIn("tests/ops/test_ci_cost_governance.py", roots)
        self.assertNotIn("tests/deleted.py", roots)

    def test_changed_paths_includes_deleted_relevant_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            deleted_files = [
                "src/deleted.py",
                "rust/src/deleted.rs",
                ".github/workflows/deleted.yml",
            ]
            for relative_path in deleted_files:
                file_path = repo_root / relative_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("placeholder\n", encoding="utf-8")

            _git(repo_root, "init")
            _git(repo_root, "config", "user.name", "OJ4-A Test")
            _git(repo_root, "config", "user.email", "oj4a-test@example.invalid")
            _git(repo_root, "add", ".")
            _git(repo_root, "commit", "-m", "base")
            base_sha = _git(repo_root, "rev-parse", "HEAD")

            for relative_path in deleted_files:
                (repo_root / relative_path).unlink()
            _git(repo_root, "commit", "-am", "delete relevant files")
            head_sha = _git(repo_root, "rev-parse", "HEAD")

            paths = CLASSIFIER["changed_paths"](base_sha, head_sha, repo_root)
            flags = classify_paths(paths)
            roots = targeted_test_roots(paths, repo_root)

            for relative_path in deleted_files:
                self.assertIn(relative_path, paths)
                self.assertNotIn(relative_path, roots)
            self.assertTrue(flags["python_changed"])
            self.assertTrue(flags["rust_changed"])
            self.assertTrue(flags["workflow_changed"])

    def test_docs_workflow_handles_ready_for_review_without_untrusted_deploy(
        self,
    ) -> None:
        docs = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
        pull_request = docs.split("  pull_request:\n", 1)[1].split(
            "  workflow_dispatch:", 1
        )[0]
        self.assertIn("types:", pull_request)
        self.assertIn("- ready_for_review", pull_request)
        self.assertNotIn("converted_to_draft", pull_request)
        self.assertNotIn("pull_request_target", docs)

        deploy = docs.split("  deploy:\n", 1)[1]
        self.assertIn("github.event_name != 'pull_request'", deploy)

        secret_step = docs.split(
            "      - name: Inject leaderboard Supabase anon key", 1
        )[1].split("      - name: Build documentation", 1)[0]
        self.assertIn("if: github.event_name != 'pull_request'", secret_step)
        self.assertIn("secrets.VITE_SUPABASE_ANON_KEY", secret_step)
        pr_step = docs.split(
            "      - name: Write disabled leaderboard config for pull requests", 1
        )[1].split("      - name: Inject leaderboard Supabase anon key", 1)[0]
        self.assertNotIn("secrets.", pr_step)

    def test_docs_ready_routes_build_for_docs_python_and_workflow_changes(self) -> None:
        for path in (
            "docs/index.md",
            "src/openjarvis/core/config.py",
            ".github/workflows/docs.yml",
        ):
            with self.subTest(path=path):
                route = self.route("pull_request", False, path)
                self.assertTrue(route["docs_build_required"])


if __name__ == "__main__":
    unittest.main()
