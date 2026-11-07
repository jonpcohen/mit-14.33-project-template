"""Offline checks: no model calls, GitHub writes, or scheduler installation."""

import argparse
import contextlib
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("research_audit", Path(__file__).with_name("audit.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def review(file="code/analysis.py", evidence="value = 1"):
    return {"summary": "One assumption warrants checking.", "findings": [{
        "priority": "medium", "confidence": "check", "title": "Explain the analysis constant",
        "file": file, "line": 1, "evidence": evidence, "why": "The intended meaning is unclear.",
        "category": "Documentation", "fix": "Document the substantive meaning.",
        "success_criterion": "A reader can identify what value measures and its units.", "example": ""}]}


class SourceTests(unittest.TestCase):
    def test_scope(self):
        for name in ("data/raw/values.csv", "data/raw/secret.py", "output/result.json", "paper/draft.qmd", "archive/old.py", ".venv/lib/example.py", "tests/test_analysis.py", ".env", "config/secrets.json", "credentials.json", "data/config.yaml", "tools/research-audit/audit.py"):
            self.assertIsNone(audit.source_kind(name), name)
        for name in ("code/clean.py", "code/table.R", "code/results.do", "code/notebook.ipynb", "analysis.qmd",
                     "run.ps1", "run.bat", "run.cmd"):
            self.assertEqual(audit.source_kind(name), "code", name)
        for name in ("README.md", "data/raw/README.md", "requirements.txt", ".env.example",
                     "config.yaml", "config/analysis.json", "settings.toml", "uv.lock", "requirements-dev.txt"):
            self.assertEqual(audit.source_kind(name), "documentation", name)

    def test_redaction_preserves_lines(self):
        source = 'api_key = "a-very-secret-value"\nx = 2\n'
        redacted = audit.redact(source)
        self.assertNotIn("a-very-secret-value", redacted)
        self.assertEqual(len(source.splitlines()), len(redacted.splitlines()))
        self.assertIn("x = 2", redacted)

    def test_syntax_checks_do_not_execute(self):
        files = [{"file": "a.py", "text": "raise RuntimeError('must not run')\n"},
                 {"file": "b.py", "text": "if :\n"},
                 {"file": "n.ipynb::cell-2", "text": "%matplotlib inline\nx = 1"}]
        self.assertEqual([x["status"] for x in audit.syntax_checks(files)], ["passed", "failed", "skipped"])

    def test_r_notebook_is_not_checked_as_python(self):
        checks = audit.syntax_checks([{"file": "a.ipynb::cell-1", "text": "x <- function() { 1 }", "language": "R"}])
        self.assertEqual(checks[0]["status"], "skipped")


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.files = [{"file": "code/analysis.py", "text": "value = 1\n"}]

    def findings_review(self, priorities):
        return {"summary": "Prioritized research-code improvements.", "findings": [
            {**review()["findings"][0], "title": f"Finding {index}", "priority": priority}
            for index, priority in enumerate(priorities, 1)]}

    def render(self, value):
        metadata = {"repository": "o/r", "commit": "abc", "date": "2026-11-06",
                    "provider": "codex", "syntax_checks": [], "files": ["code/analysis.py"],
                    "omitted": [], "fingerprint": "123"}
        return audit.render_report(value, metadata)

    def test_more_than_three_findings_allowed_and_all_evidence_validated(self):
        value = self.findings_review(["medium"] * 5)
        self.assertEqual(audit.validate_review(value, self.files), value)
        # Provider output schemas must also allow the full findings list.
        self.assertNotIn("maxItems", audit.SCHEMA["properties"]["findings"])
        value["findings"][-1]["evidence"] = "invented evidence"
        with self.assertRaises(audit.AuditError):
            audit.validate_review(value, self.files)

    def test_report_keeps_three_visible_and_preserves_additional_details(self):
        value = self.findings_review(["medium"] * 5)
        value["findings"][3]["example"] = "value = 1"
        report = self.render(value)
        visible, _, rest = report.partition("<details>")
        additional, close, footer = rest.partition("</details>")
        self.assertIn("## Start here", visible)
        for index in (1, 2, 3):
            self.assertIn(f"Finding {index}", visible)
        for index in (4, 5):
            self.assertNotIn(f"Finding {index}", visible)
            self.assertIn(f"Finding {index}", additional)
        self.assertIn("Additional improvements (2)", additional)
        self.assertIn("/blob/abc/code/analysis.py#L1", additional)
        self.assertIn("**Next step:** Document the substantive meaning.", additional)
        self.assertIn("**Done when:**", additional)
        self.assertIn("```\nvalue = 1\n```", additional)
        self.assertTrue(close)
        self.assertIn("### What was checked", footer)
        self.assertEqual(len(value["findings"]), 5)

    def test_all_high_priority_findings_stay_visible_even_if_unsorted(self):
        value = self.findings_review(["medium", "high", "high", "medium", "high", "high"])
        report = self.render(value)
        visible, _, additional = report.partition("<details>")
        for index in (2, 3, 5, 6):
            self.assertIn(f"Finding {index}", visible)
            self.assertNotIn(f"Finding {index}", additional)
        self.assertNotIn("### Medium:", visible)
        self.assertIn("Finding 1", additional)
        self.assertIn("Finding 4", additional)
        # Presentation must not alter the saved review's original findings.
        self.assertEqual(value["findings"][0]["priority"], "medium")

    def test_short_and_empty_reports_have_no_extra_section(self):
        for priorities in ([], ["medium"], ["medium"] * 3, ["high"] * 4):
            with self.subTest(priorities=priorities):
                report = self.render(self.findings_review(priorities))
                self.assertNotIn("<details>", report)
                self.assertNotIn("Additional improvements", report)
        self.assertNotIn("## Start here", self.render(self.findings_review([])))

    def test_rejects_invented_evidence(self):
        with self.assertRaises(audit.AuditError):
            audit.validate_review(review(evidence="value = 99"), self.files)

    def test_rejects_invented_file(self):
        with self.assertRaises(audit.AuditError):
            audit.validate_review(review(file="missing.py"), self.files)

    def test_rejects_invented_line(self):
        value = review()
        value["findings"][0]["line"] = 8
        with self.assertRaises(audit.AuditError):
            audit.validate_review(value, self.files)

    def test_accepts_empty_findings(self):
        value = {"summary": "No material risk found in the supplied code.", "findings": []}
        self.assertEqual(audit.validate_review(value, self.files), value)

    def test_category_validation_and_rendering(self):
        value = review()
        audit.validate_review(value, self.files)
        metadata = {"repository": "o/r", "commit": "abc", "date": "2026-11-06",
                    "provider": "codex", "syntax_checks": [], "files": ["code/analysis.py"],
                    "omitted": [], "fingerprint": "123"}
        self.assertIn("**Practice:** Documentation", audit.render_report(value, metadata))
        value["findings"][0]["category"] = "Packaging"
        with self.assertRaises(audit.AuditError):
            audit.validate_review(value, self.files)
        del value["findings"][0]["category"]
        with self.assertRaises(audit.AuditError):
            audit.validate_review(value, self.files)

    def test_completion_criterion_and_optional_example(self):
        value = review()
        metadata = {"repository": "o/r", "commit": "abc", "date": "2026-11-06",
                    "provider": "codex", "syntax_checks": [], "files": ["code/analysis.py"],
                    "omitted": [], "fingerprint": "123"}
        audit.validate_review(value, self.files)
        report = audit.render_report(value, metadata)
        self.assertIn("**Done when:** A reader can identify", report)
        self.assertNotIn("**Example:**", report)
        value["findings"][0]["example"] = '# value is measured in dollars.\nvalue = 1'
        audit.validate_review(value, self.files)
        report = audit.render_report(value, metadata)
        self.assertIn('```\n# value is measured in dollars.\nvalue = 1\n```', report)
        # Previously saved reports without the new fields remain readable.
        del value["findings"][0]["success_criterion"]
        del value["findings"][0]["example"]
        self.assertNotIn("**Done when:**", audit.render_report(value, metadata))

    def test_rejects_missing_completion_criterion_and_long_examples(self):
        for criterion in (None, "", " ", 12):
            value = review()
            value["findings"][0]["success_criterion"] = criterion
            with self.subTest(criterion=criterion), self.assertRaises(audit.AuditError):
                audit.validate_review(value, self.files)
        for example in (None, 12, "line\n" * 6):
            value = review()
            value["findings"][0]["example"] = example
            with self.subTest(example=example), self.assertRaises(audit.AuditError):
                audit.validate_review(value, self.files)

    def test_parses_all_provider_envelopes(self):
        value = review()
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            audit.write_json(work / "answer.json", value)
            self.assertEqual(audit.parse_review("codex", "progress logs", work), value)
            self.assertEqual(audit.parse_review("claude", json.dumps({"structured_output": value}), work), value)
            self.assertEqual(audit.parse_review("gemini", json.dumps({"response": json.dumps(value)}), work), value)
            with self.assertRaises(audit.AuditError):
                audit.parse_review("gemini", '{"error":{"message":"auth failed"}}', work)

    def test_provider_commands_and_subscription_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            codex = audit.provider_command("codex", "codex", work)
            self.assertIn("read-only", codex)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", codex)
            claude = audit.provider_command("claude", "claude", work)
            self.assertEqual(claude[claude.index("--tools") + 1], "")
            gemini = audit.provider_command("gemini", "gemini", work)
            self.assertIn("--prompt", gemini)
            self.assertEqual(audit.read_json(work / ".gemini/settings.json")["hooksConfig"]["enabled"], False)
            self.assertIn('decision = "deny"', (work / "deny-tools.toml").read_text())
        with patch.dict(audit.os.environ, {"OPENAI_API_KEY": "secret", "ANTHROPIC_API_KEY": "secret", "GEMINI_API_KEY": "secret", "GH_TOKEN": "secret"}):
            env = audit.subscription_environment({})
            for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GH_TOKEN"):
                self.assertNotIn(key, env)

    def test_notebook_links_do_not_claim_json_line_numbers(self):
        self.assertTrue(audit.source_link("owner/repo", "abc", "analysis.py", 12).endswith("#L12"))
        self.assertTrue(audit.source_link("owner/repo", "abc", "analysis.ipynb::cell-3", 12).endswith("analysis.ipynb"))


class ScheduleTests(unittest.TestCase):
    def test_weekly_due_time(self):
        now = dt.datetime(2026, 10, 27, 9, 0)  # Tuesday
        due = dt.datetime.fromtimestamp(audit.next_weekly("sun", "18:17", now))
        self.assertEqual(due, dt.datetime(2026, 11, 1, 18, 17))
        next_due = dt.datetime.fromtimestamp(audit.next_weekly("sun", "18:17", due))
        self.assertEqual(next_due, dt.datetime(2026, 11, 8, 18, 17))

    def test_scheduler_files_for_all_platforms(self):
        config = {"python": "/path with spaces/python", "path": "/custom/bin:/usr/bin"}
        root = Path("/project with spaces")
        _, data, _ = audit.scheduler_spec(root, config, "Darwin")
        launch = plistlib.loads(data)
        self.assertEqual(launch["StartCalendarInterval"], {"Minute": 17})
        self.assertTrue(launch["RunAtLoad"])
        self.assertIn("--scheduled", launch["ProgramArguments"])
        self.assertEqual(launch["EnvironmentVariables"]["PATH"], config["path"])
        _, data, _ = audit.scheduler_spec(root, config, "Linux")
        self.assertIn('"/path with spaces/python"', data.decode())
        with patch.object(audit, "command", return_value=subprocess.CompletedProcess([], 0, "school\\student\n", "")):
            _, data, _ = audit.scheduler_spec(root, config, "Windows")
        task = ET.fromstring(data)
        namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(task.find(".//t:Interval", namespace).text, "PT1H")
        self.assertEqual(task.find(".//t:LogonType", namespace).text, "InteractiveToken")
        self.assertEqual(task.find(".//t:LogonTrigger/t:Delay", namespace).text, "PT2M")
        self.assertEqual(task.find(".//t:SessionStateChangeTrigger/t:StateChange", namespace).text, "SessionUnlock")
        self.assertEqual(task.find(".//t:SessionStateChangeTrigger/t:Delay", namespace).text, "PT2M")
        # Task Scheduler requires base fields before the Repetition element.
        time_trigger = task.find(".//t:TimeTrigger", namespace)
        self.assertEqual([e.tag.split("}")[-1] for e in time_trigger], ["StartBoundary", "Repetition"])
        timer = audit.linux_timer({"time": "18:17"})
        self.assertIn("OnStartupSec=2min", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("OnCalendar=*-*-* *:17:00", timer)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-status-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.now = dt.datetime(2026, 11, 6, 12)
        self.config = {"provider": "codex", "scheduler": {"system": "Darwin"},
                       "day": "sun", "time": "18:17", "end_date": "2026-12-04",
                       "next_due": dt.datetime(2026, 11, 8, 18, 17).timestamp()}

    def test_no_setup_or_report(self):
        with patch.object(audit, "command") as command:
            text = audit.render_status(self.directory, {}, {}, self.now)
        command.assert_not_called()
        self.assertIn("Provider: not configured", text)
        self.assertIn("Automatic reviews: off", text)
        self.assertIn("Latest saved report: none yet", text)
        self.assertIn("--provider codex --no-post", text)

    def test_active_overdue_retry_and_expired_schedule(self):
        text = audit.render_status(self.directory, self.config, {}, self.now)
        self.assertIn("Sunday at 18:17", text)
        self.assertIn("Next review due: 2026-11-08 18:17", text)
        self.assertIn("Last day of automatic reviews: 2026-12-04", text)
        self.assertIn("audit.py uninstall", text)
        self.config["next_due"] = 0
        self.assertIn("overdue", audit.render_status(self.directory, self.config, {}, self.now))
        state = {"retry_after": dt.datetime(2026, 11, 7, 18).timestamp()}
        self.assertIn("Next review due: 2026-11-07 18:00",
                      audit.render_status(self.directory, self.config, state, self.now))
        self.config["next_due"] = dt.datetime(2026, 12, 6, 18, 17).timestamp()
        self.assertIn("No further automatic reviews", audit.render_status(self.directory, self.config, {}, self.now))
        text = audit.render_status(self.directory, self.config, {}, dt.datetime(2026, 12, 5))
        self.assertIn("ended after 2026-12-04", text)
        self.assertIn("removal is pending", text)
        self.assertNotIn("Next review due", text)

    def test_failed_attempt_does_not_hide_saved_report_and_offers_login_help(self):
        (self.directory / "latest.md").write_text("Earlier successful report")
        details = self.directory / "runs" / "2026-11-06-new" / "run.json"
        audit.write_json(details, {"date": "2026-11-06", "provider": "claude",
                                  "commit": "abc123", "scope": "local HEAD", "status": "failed",
                                  "error": "Authentication failed; sign in again."})
        (details.parent / "provider.log").write_text("CLI error")
        text = audit.render_status(self.directory, {}, {}, self.now)
        self.assertIn(f"Latest saved report: {self.directory / 'latest.md'}", text)
        self.assertIn("review failed; no new report posted", text)
        self.assertIn("abc123 (local HEAD)", text)
        self.assertIn("open claude interactively", text)
        self.assertIn("--provider claude --no-post", text)
        audit.write_json(details, {"date": "2026-11-06", "status": "post_failed"})
        text = audit.render_status(self.directory, self.config, {}, self.now)
        self.assertIn("gh auth status", text)
        self.assertIn("retry posting the saved report", text)

    def test_status_command_defaults_to_text_and_retains_json_option(self):
        audit.write_json(self.directory / "config.json", self.config)
        with patch.object(audit, "project_root", return_value=self.directory), \
             patch.object(audit, "state_dir", return_value=self.directory):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                audit.main(["status"])
            self.assertTrue(output.getvalue().startswith("Provider: codex"))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                audit.main(["status", "--json"])
            self.assertEqual(json.loads(output.getvalue())["config"], self.config)


class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-tests-")
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Audit Test")
        self.git("config", "user.email", "audit@example.invalid")
        self.write("code/analysis.py", "value = 1\n")
        self.write("README.md", "# Example research project\n")
        self.write("data/raw/private.csv", "private values\n")
        self.write("archive/old.py", "old = True\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Fixture")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.directory = audit.state_dir(self.root)
        self.args = argparse.Namespace(provider="codex", model=None, local=True, scheduled=False, force=False, no_post=False)

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return audit.command(["git", *args], cwd=self.root).stdout

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_collects_committed_source_and_strips_notebook_outputs(self):
        notebook = {"cells": [{"cell_type": "code", "source": ["print(1)\n"], "outputs": [{"text": "PRIVATE OUTPUT"}]}]}
        self.write("code/book.ipynb", json.dumps(notebook))
        self.git("add", ".")
        self.git("commit", "-qm", "Notebook")
        self.write("code/analysis.py", "uncommitted = True\n")
        files, omitted, _ = audit.collect_sources(self.root, "HEAD")
        content = json.dumps(files)
        self.assertNotIn("PRIVATE OUTPUT", content)
        self.assertNotIn("private values", content)
        self.assertNotIn("uncommitted", content)
        self.assertNotIn("old.py", content)
        self.assertIn("::cell-1", content)
        self.assertIn("value = 1", content)
        self.assertEqual(omitted, [])

    def test_configuration_and_inventory_with_omissions(self):
        self.write("config/analysis.yaml", "end_year: 2026\n")
        self.write("config/secrets.json", '{"password": "private value"}')
        self.git("add", ".")
        self.git("commit", "-qm", "Configuration")
        with patch.object(audit, "MAX_CONTEXT", 25):
            files, omitted, manifest = audit.collect_sources(self.root, "HEAD")
        self.assertIn("config/analysis.yaml", manifest)
        self.assertNotIn("config/secrets.json", manifest)
        prompt = audit.review_prompt(files, omitted, [], None, manifest)
        payload = json.loads(prompt.split("nothing was executed.\n", 1)[1])
        self.assertIn("config/analysis.yaml", payload["eligible_file_inventory"])
        self.assertTrue(omitted)
        self.assertNotIn("private value", prompt)

    def test_windows_master_scripts_are_included_without_python_parsing(self):
        scripts = {"run.ps1": "Write-Error 'not to be executed'\n",
                   "run.cmd": "exit /b 99\n", "run.bat": "exit /b 99\n"}
        for name, source in scripts.items():
            self.write(name, source)
        self.git("add", ".")
        self.git("commit", "-qm", "Windows master scripts")
        files, omitted, manifest = audit.collect_sources(self.root, "HEAD")
        by_name = {source["file"]: source for source in files}
        for name, source in scripts.items():
            self.assertIn(name, manifest)
            self.assertEqual(by_name[name]["text"], source)
            self.assertEqual(audit.syntax_checks([by_name[name]]), [])
        self.assertEqual(omitted, [])

    def test_size_limits_are_disclosed(self):
        with patch.object(audit, "MAX_FILE", 2):
            files, omitted, _ = audit.collect_sources(self.root, self.sha)
        self.assertEqual(files, [])
        self.assertTrue(omitted)

    def test_large_notebook_outputs_do_not_exclude_small_source(self):
        notebook = {"cells": [{"cell_type": "code", "source": ["print(1)\n"], "outputs": [{"text": "output" * 20_000}]}]}
        self.write("code/large.ipynb", json.dumps(notebook))
        self.git("add", ".")
        self.git("commit", "-qm", "Notebook outputs")
        files, omitted, _ = audit.collect_sources(self.root, "HEAD")
        self.assertIn("code/large.ipynb::cell-1", [f["file"] for f in files])
        self.assertFalse(any(o["file"] == "code/large.ipynb" for o in omitted))

    def test_local_state_is_ignored(self):
        self.assertIn(".audit", self.git("check-ignore", ".audit/state.json"))

    def run_with_mocks(self, generated, posted):
        with patch.object(audit, "repository_info", return_value=("owner/repo", "main", self.sha)), \
             patch.object(audit, "generate_review", generated), patch.object(audit, "post_report", posted):
            audit.perform_run(self.root, self.directory, {}, self.args)

    def test_save_before_post_skip_unchanged_and_preserve_worktree(self):
        from unittest.mock import Mock
        generated = Mock(return_value=review())
        def check_saved(root, repo, report, marker):
            self.assertTrue(report.exists())
            self.assertTrue((self.directory / "latest.md").exists())
            return "https://github.com/owner/repo/issues/1"
        posted = Mock(side_effect=check_saved)
        before = self.git("status", "--porcelain")
        self.run_with_mocks(generated, posted)
        self.run_with_mocks(generated, posted)
        generated.assert_called_once()
        posted.assert_called_once()
        self.assertEqual(self.git("status", "--porcelain"), before)
        state = audit.read_json(self.directory / "state.json")
        self.assertEqual(state["issue_url"], "https://github.com/owner/repo/issues/1")
        metadata = audit.read_json(Path(state["last_run"]) / "run.json")
        self.assertEqual(metadata["status"], "posted")
        self.assertIn(f"/blob/{self.sha}/code/analysis.py#L1", (self.directory / "latest.md").read_text())

    def test_failed_post_retries_saved_report_without_model(self):
        from unittest.mock import Mock
        generated = Mock(return_value=review())
        posted = Mock(side_effect=audit.AuditError("network unavailable"))
        with self.assertRaises(audit.AuditError):
            self.run_with_mocks(generated, posted)
        state = audit.read_json(self.directory / "state.json")
        self.assertTrue((Path(state["last_run"]) / "report.md").exists())
        self.assertEqual(audit.read_json(Path(state["last_run"]) / "run.json")["status"], "post_failed")
        posted = Mock(return_value="https://github.com/owner/repo/issues/2")
        self.run_with_mocks(generated, posted)
        generated.assert_called_once()
        self.assertEqual(audit.read_json(self.directory / "state.json")["issue_url"], "https://github.com/owner/repo/issues/2")

    def test_preview_then_publish_without_second_model_call(self):
        from unittest.mock import Mock
        generated, posted = Mock(return_value=review()), Mock(return_value="https://github.com/owner/repo/issues/3")
        self.args.no_post = True
        self.run_with_mocks(generated, posted)
        posted.assert_not_called()
        self.args.no_post = False
        self.run_with_mocks(generated, posted)
        generated.assert_called_once()
        posted.assert_called_once()

    def test_next_review_receives_previous_findings_commit_and_coverage(self):
        from unittest.mock import Mock
        generated = Mock(return_value=review())
        self.args.no_post = True
        self.run_with_mocks(generated, Mock())
        first_sha = self.sha
        self.write("code/analysis.py", "# This constant measures dollars.\nvalue = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Explain constant")
        self.sha = self.git("rev-parse", "HEAD").strip()
        generated = Mock(return_value={"summary": "The constant's units are now documented.", "findings": []})
        self.run_with_mocks(generated, Mock())
        prompt = generated.call_args.args[2]
        payload = json.loads(prompt.split("nothing was executed.\n", 1)[1])
        self.assertEqual(payload["previous_review"], review())
        self.assertEqual(payload["previous_review_context"]["commit"], first_sha)
        self.assertIn("code/analysis.py", payload["previous_review_context"]["files"])
        self.assertEqual(payload["previous_review_context"]["scope"], "local HEAD")
        current = {source["file"]: source["source"] for source in payload["files"]}
        self.assertIn("# This constant measures dollars.", current["code/analysis.py"])
        self.assertIn("units are now documented", (self.directory / "latest.md").read_text())

    def test_not_due_never_contacts_github_or_model(self):
        self.args.scheduled = True
        with patch.object(audit, "repository_info") as info:
            audit.perform_run(self.root, self.directory, {"next_due": audit.time.time() + 3600, "scheduler": {"system": "test"}, "end_date": "2099-12-04"}, self.args)
        info.assert_not_called()

    def test_multiple_missed_weeks_catch_up_once_then_return_to_schedule(self):
        from unittest.mock import Mock
        self.args.scheduled = True
        config = {"day": "sun", "time": "18:17", "next_due": audit.time.time() - 14 * 86400,
                  "scheduler": {"system": "test"}, "end_date": "2099-12-04"}
        generated = Mock(return_value=review())
        posted = Mock(return_value="https://github.com/owner/repo/issues/4")
        with patch.object(audit, "repository_info", return_value=("owner/repo", "main", self.sha)) as info, \
             patch.object(audit, "generate_review", generated), patch.object(audit, "post_report", posted):
            audit.perform_run(self.root, self.directory, config, self.args)
            updated = audit.read_json(self.directory / "config.json")
            self.assertGreater(updated["next_due"], audit.time.time())
            audit.perform_run(self.root, self.directory, updated, self.args)
        generated.assert_called_once()
        posted.assert_called_once()
        info.assert_called_once()

    def test_expired_schedule_removes_itself_before_any_network_call(self):
        self.args.scheduled = True
        for system in ("Darwin", "Windows", "Linux"):
            with self.subTest(system=system):
                path = self.root / "schedule.plist"
                path.write_text("schedule")
                path.with_suffix(".timer").write_text("timer")
                config = {"end_date": "2000-12-04", "next_due": 0,
                          "scheduler": {"system": system, "path": str(path), "label": "test"}}
                audit.write_json(self.directory / "config.json", config)
                with patch.object(audit, "repository_info") as info, patch.object(audit, "command") as cmd:
                    audit.perform_run(self.root, self.directory, config, self.args)
                info.assert_not_called()
                self.assertFalse(path.exists())
                saved = audit.read_json(self.directory / "config.json")
                self.assertNotIn("scheduler", saved)
                self.assertTrue(cmd.called)

    def test_legacy_schedule_expires_and_cutoff_is_inclusive(self):
        self.args.scheduled = True
        class CourseDate(dt.date):
            @classmethod
            def today(cls):
                return cls(2026, 12, 5)
        with patch.object(audit.dt, "date", CourseDate), patch.object(audit, "uninstall") as remove, \
             patch.object(audit, "repository_info") as info:
            audit.perform_run(self.root, self.directory, {"next_due": 0}, self.args)
        remove.assert_called_once()
        info.assert_not_called()
        class LastDay(dt.date):
            @classmethod
            def today(cls):
                return cls(2026, 12, 4)
        with patch.object(audit.dt, "date", LastDay), patch.object(audit, "uninstall") as remove:
            audit.perform_run(self.root, self.directory,
                              {"scheduler": {"system": "test"}, "next_due": float("inf")}, self.args)
        remove.assert_not_called()

    def test_manual_review_still_works_after_expiry(self):
        from unittest.mock import Mock
        generated = Mock(return_value=review())
        self.args.no_post = True
        with patch.object(audit, "repository_info", return_value=("owner/repo", "main", self.sha)), \
             patch.object(audit, "generate_review", generated), patch.object(audit, "uninstall") as remove:
            audit.perform_run(self.root, self.directory, {"end_date": "2000-12-04"}, self.args)
        generated.assert_called_once()
        remove.assert_not_called()

    def test_setup_saves_cutoff_before_scheduler_can_start(self):
        args = argparse.Namespace(provider="codex", model=None, day="sun", time="18:17",
                                  no_schedule=False, end_date="2099-12-04")
        path = self.root / "schedule.plist"
        def registration(cmd, **kwargs):
            if cmd[0] == "launchctl" and cmd[1] == "bootstrap":
                config = audit.read_json(self.directory / "config.json")
                self.assertEqual(config["end_date"], "2099-12-04")
                self.assertEqual(config["scheduler"]["system"], "Darwin")
        with patch.object(audit.shutil, "which", return_value="/bin/codex"), \
             patch.object(audit, "scheduler_spec", return_value=(path, b"schedule", "test")), \
             patch.object(audit.platform, "system", return_value="Darwin"), \
             patch.object(audit, "command", side_effect=registration):
            audit.install(self.root, self.directory, args)
        self.assertTrue(path.exists())

    def test_install_rejects_past_end_date(self):
        args = argparse.Namespace(no_schedule=False, end_date="2000-01-01")
        with patch.object(audit, "command") as cmd, self.assertRaises(audit.AuditError):
            audit.install(self.root, self.directory, args)
        cmd.assert_not_called()

    def test_reinstall_preserves_overdue_review(self):
        overdue = audit.time.time() - 86400
        audit.write_json(self.directory / "config.json", {"day": "sun", "time": "18:17", "next_due": overdue})
        args = argparse.Namespace(provider="codex", model=None, day="sun", time="18:17", no_schedule=True)
        with patch.object(audit.shutil, "which", return_value="/bin/codex"), patch.object(audit, "command"):
            audit.install(self.root, self.directory, args)
        self.assertEqual(audit.read_json(self.directory / "config.json")["next_due"], overdue)

    def test_no_code_uses_no_model_and_posts_no_issue(self):
        from unittest.mock import Mock
        self.git("rm", "code/analysis.py")
        self.git("commit", "-qm", "No analysis yet")
        self.sha = self.git("rev-parse", "HEAD").strip()
        generated, posted = Mock(), Mock()
        self.run_with_mocks(generated, posted)
        generated.assert_not_called()
        posted.assert_not_called()
        self.assertIn("No eligible analysis code", (self.directory / "latest.md").read_text())

    def test_duplicate_issue_is_reused(self):
        marker = "<!-- research-audit:abc -->"
        response = subprocess.CompletedProcess([], 0, json.dumps([{"body": marker, "url": "https://github.com/o/r/issues/1"}]), "")
        with patch.object(audit, "command", return_value=response) as called:
            url = audit.post_report(self.root, "owner/repo", Path("unused"), marker)
        self.assertEqual(url, "https://github.com/o/r/issues/1")
        called.assert_called_once()


if __name__ == "__main__":
    unittest.main()
