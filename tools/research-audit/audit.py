#!/usr/bin/env python3
"""Local subscription-based research reviews. Python 3.10+, standard library only."""

from __future__ import annotations

import argparse
import ast
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
PROVIDERS = ("codex", "claude", "gemini")
VERSION = 5
COURSE_END = "2026-12-04"
MAX_FILE = 60_000
MAX_CONTEXT = 240_000
CODE_SUFFIXES = {".py", ".r", ".do", ".ado", ".jl", ".m", ".sh", ".ps1", ".bat", ".cmd", ".sql", ".ipynb", ".rmd", ".qmd"}
SKIP_PARTS = {".audit", ".git", ".venv", "venv", "env", "node_modules", "renv", "vendor", "archive", "archived", "__pycache__", "site-packages", "tests", "test"}
SETUP_NAMES = {"pyproject.toml", "requirements.txt", "environment.yml", "environment.yaml", "renv.lock", "description", "makefile", "justfile", ".env.example", "package.json", "project.toml"}
CONFIG_SUFFIXES = {".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"}
PRACTICES = ("Shared parameters", "Reproducible environment", "Execution order",
             "Safe data handling", "Repeated code", "Documentation", "Other research risk")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                **{k: {"type": "string"} for k in ("title", "file", "evidence", "why", "fix", "success_criterion", "example")},
                "category": {"type": "string", "enum": list(PRACTICES)},
                "priority": {"type": "string", "enum": ["high", "medium"]},
                "confidence": {"type": "string", "enum": ["confirmed", "check"]},
                "line": {"type": "integer", "minimum": 1},
            },
            "required": ["priority", "confidence", "title", "file", "line", "evidence", "why", "fix", "success_criterion", "example", "category"],
        }},
    }, "required": ["summary", "findings"],
}


class AuditError(Exception):
    pass


def command(args, *, cwd=None, input=None, env=None, timeout=120, check=True):
    try:
        result = subprocess.run([str(a) for a in args], cwd=cwd, input=input,
                                env=env, text=True, encoding="utf-8", errors="replace",
                                capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError(f"Could not run {args[0]}: {exc}") from exc
    if check and result.returncode:
        raise AuditError(f"{args[0]} failed: {redact(result.stderr or result.stdout)[-2000:]}")
    return result


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def redact(text):
    """Remove recognizable tokens and literal secret assignments before model input."""
    text = re.sub(r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{25,})", "[REDACTED]", text)
    return re.sub(r'''(?im)((?:api[_-]?key|access[_-]?token|secret|password)\s*[=:]\s*)(["'])([^\n"']{8,})(\2)''', r'\1\2[REDACTED]\4', text)


def project_root():
    return Path(command(["git", "rev-parse", "--show-toplevel"], cwd=HERE).stdout.strip())


def state_dir(root):
    directory = root / ".audit"
    directory.mkdir(exist_ok=True)
    # Also protect existing student copies whose .gitignore predates this tool.
    exclude = Path(command(["git", "rev-parse", "--git-path", "info/exclude"], cwd=root).stdout.strip())
    if not exclude.is_absolute():
        exclude = root / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if "/.audit/" not in existing.splitlines():
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write("\n# Local research review state\n/.audit/\n")
    return directory


@contextlib.contextmanager
def run_lock(directory):
    """OS-released lock; a killed job cannot leave a permanently stale lock."""
    with (directory / "run.lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                stream.write(b"0")
                stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AuditError("Another audit is already running.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def source_kind(name):
    path = PurePosixPath(name)
    parts = {p.lower() for p in path.parts[:-1]}
    if parts & SKIP_PARTS or name.startswith("tools/research-audit/"):
        return None
    base = path.name.lower()
    if "data" in parts or "output" in parts or "paper" in parts:
        return "documentation" if base.startswith("readme") else None
    if base.startswith(".env") and base != ".env.example":
        return None
    if any(word in base for word in ("secret", "credential", "password", "token")):
        return None
    configuration = (path.suffix.lower() in CONFIG_SUFFIXES
                     and (base.split(".")[0] in {"config", "settings", "parameters", "params"}
                          or bool(parts & {"config", "configs"})))
    dependency = (base in {"uv.lock", "poetry.lock", "pipfile", "pipfile.lock"}
                  or (base.startswith("requirements") and path.suffix.lower() == ".txt"))
    if base in SETUP_NAMES or base.startswith("readme") or configuration or dependency:
        return "documentation"
    return "code" if path.suffix.lower() in CODE_SUFFIXES else None


def repository_info(root, local):
    info = json.loads(command(["gh", "repo", "view", "--json", "nameWithOwner,defaultBranchRef"], cwd=root).stdout)
    repo = info["nameWithOwner"]
    branch = info["defaultBranchRef"]["name"]
    if local:
        sha = command(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    else:
        command(["git", "fetch", "--quiet", "--no-tags", "origin", branch], cwd=root)
        sha = command(["git", "rev-parse", "FETCH_HEAD^{commit}"], cwd=root).stdout.strip()
    return repo, branch, sha


def collect_sources(root, sha, previous_files=None):
    tree = command(["git", "ls-tree", "-r", "-z", "--long", sha], cwd=root).stdout
    candidates, omitted, files, used = [], [], [], 0
    for entry in tree.split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, kind, blob, size = metadata.split()
        category = source_kind(name)
        if not category:
            continue
        if mode != "100644" and mode != "100755":
            omitted.append({"file": name, "reason": "not a regular file"})
            continue
        candidates.append((name, blob, int(size), category))
    # Setup context first, then changed code, then remaining active code.
    previous_files = previous_files or {}
    candidates.sort(key=lambda x: (x[3] != "documentation", previous_files.get(x[0]) == x[1], x[0]))
    for name, blob, size, category in candidates:
        notebook_file = name.lower().endswith(".ipynb")
        # Large notebook outputs should not crowd out a small amount of source.
        if size > (10_000_000 if notebook_file else MAX_FILE):
            omitted.append({"file": name, "reason": f"larger than {MAX_FILE} bytes"})
            continue
        content = command(["git", "show", f"{sha}:{name}"], cwd=root).stdout
        if "\0" in content:
            omitted.append({"file": name, "reason": "binary content"})
            continue
        entries = []
        if notebook_file:
            try:
                notebook = json.loads(content)
                notebook_metadata = notebook.get("metadata", {})
                language = notebook_metadata.get("language_info", {}).get("name") or notebook_metadata.get("kernelspec", {}).get("language", "python")
                for index, cell in enumerate(notebook["cells"], 1):
                    if cell.get("cell_type") == "code":
                        source = cell.get("source", [])
                        text = source if isinstance(source, str) else "".join(source)
                        entries.append({"file": f"{name}::cell-{index}", "text": redact(text), "category": "code", "blob": blob, "language": language})
            except (ValueError, KeyError, TypeError):
                omitted.append({"file": name, "reason": "invalid notebook JSON"})
                continue
        else:
            entries.append({"file": name, "text": redact(content), "category": category, "blob": blob})
        cost = sum(len(e["text"].encode("utf-8")) for e in entries)
        if notebook_file and cost > MAX_FILE:
            omitted.append({"file": name, "reason": f"notebook source larger than {MAX_FILE} bytes"})
            continue
        if used + cost > MAX_CONTEXT:
            omitted.append({"file": name, "reason": "review context limit"})
            continue
        files.extend(entries)
        used += cost
    manifest = {name: blob for name, blob, _, _ in candidates}
    return files, omitted, manifest


def syntax_checks(files):
    results = []
    for source in files:
        name, text = source["file"], source["text"]
        notebook = "::cell-" in name
        if not name.lower().endswith(".py") and not notebook:
            continue
        if notebook and source.get("language", "python").lower() not in {"python", "python3"}:
            results.append({"file": name, "status": "skipped", "reason": "not a Python notebook kernel"})
            continue
        if notebook and any(line.lstrip().startswith(("%", "!", "?")) for line in text.splitlines()):
            results.append({"file": name, "status": "skipped", "reason": "notebook magics or shell syntax"})
            continue
        try:
            ast.parse(text, filename=name)
            results.append({"file": name, "status": "passed"})
        except SyntaxError as exc:
            results.append({"file": name, "status": "failed", "line": exc.lineno, "reason": exc.msg})
    return results


def fingerprint(manifest, provider, model):
    payload = {"version": VERSION, "files": manifest, "provider": provider, "model": model,
               "rubric": (HERE / "rubric.md").read_text(encoding="utf-8")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def review_prompt(files, omitted, checks, previous, manifest=None, previous_metadata=None):
    bundle = [{"file": f["file"], "source": "\n".join(f"{i}: {line}" for i, line in enumerate(f["text"].splitlines(), 1))} for f in files]
    return ((HERE / "rubric.md").read_text(encoding="utf-8") + "\n\n"
            + "Python syntax diagnostics use Python " + platform.python_version() + ". "
            + "Other languages were inspected only; nothing was executed.\n"
            + json.dumps({"eligible_file_inventory": sorted(manifest or {f["file"]: None for f in files}),
                          "files": bundle, "omitted": omitted, "syntax_checks": checks,
                          "previous_review": previous,
                          "previous_review_context": {k: previous_metadata[k] for k in ("date", "commit", "scope", "files")
                                                      if k in (previous_metadata or {})}}, ensure_ascii=False))


def subscription_environment(config):
    env = os.environ.copy()
    # Do not accidentally switch a subscription review to separately billed API use.
    for key in list(env):
        if key in {"OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_GENAI_USE_VERTEXAI", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "GH_TOKEN", "GITHUB_TOKEN", "BASH_ENV", "ENV"}:
            env.pop(key)
    env["PATH"] = config.get("path", env.get("PATH", ""))
    env["NO_COLOR"] = "1"
    return env


def provider_command(provider, executable, work, model=None):
    if provider == "codex":
        schema = work / "schema.json"
        write_json(schema, SCHEMA)
        args = [executable, "exec", "--ignore-user-config", "--sandbox", "read-only",
                "--ephemeral", "--skip-git-repo-check", "--output-schema", schema,
                "--output-last-message", work / "answer.json", "-"]
    elif provider == "claude":
        args = [executable, "-p", "--tools", "", "--disallowedTools", "mcp__*",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "", "--no-session-persistence", "--output-format", "json",
                "--json-schema", json.dumps(SCHEMA)]
    else:
        # User auth remains in ~/.gemini; these settings affect this temp workspace only.
        settings = work / ".gemini" / "settings.json"
        policy = work / "deny-tools.toml"
        policy.write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n', encoding="utf-8")
        write_json(settings, {"tools": {"core": []}, "mcpServers": {}, "mcp": {"allowed": []},
                              "hooksConfig": {"enabled": False}, "skills": {"enabled": False},
                              "policyPaths": [str(policy)], "advanced": {"ignoreLocalEnv": True}})
        args = [executable, "--prompt", "Review the complete audit input on stdin. Return only the requested JSON. Do not use tools.", "--output-format", "json"]
    if model:
        args.extend(["--model", model])
    return args


def parse_review(provider, stdout, work):
    if provider == "codex":
        answer = work / "answer.json"
        text = answer.read_text(encoding="utf-8") if answer.exists() else stdout
    else:
        envelope = json.loads(stdout)
        if envelope.get("error") or envelope.get("is_error"):
            raise AuditError("Provider returned an error; see provider.log.")
        if provider == "claude" and isinstance(envelope.get("structured_output"), dict):
            return envelope["structured_output"]
        text = envelope.get("response" if provider == "gemini" else "result", "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text)


def validate_review(review, files):
    by_name = {f["file"]: f["text"].splitlines() for f in files}
    if not isinstance(review, dict) or not isinstance(review.get("summary"), str) or not review["summary"].strip():
        raise AuditError("Provider did not return a valid review summary.")
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise AuditError("Provider must return a list of findings.")
    for finding in findings:
        if not isinstance(finding, dict):
            raise AuditError("Malformed finding.")
        if any(not isinstance(finding.get(k), str) or not finding[k].strip() for k in ("title", "file", "evidence", "why", "fix", "success_criterion")):
            raise AuditError("A finding is missing its explanation or evidence.")
        example = finding.get("example")
        if not isinstance(example, str) or len(example.splitlines()) > 5:
            raise AuditError("A finding's example must be a string of at most five lines, or empty.")
        if finding.get("category") not in PRACTICES:
            raise AuditError("A finding has an invalid practice category.")
        line = finding.get("line")
        lines = by_name.get(finding["file"], [])
        if type(line) is not int or not 1 <= line <= len(lines) or finding["evidence"] not in lines[line - 1]:
            raise AuditError("A finding's file, line, or quoted evidence does not match the reviewed source. Nothing was posted.")
        if finding.get("priority") not in {"high", "medium"} or finding.get("confidence") not in {"confirmed", "check"}:
            raise AuditError("A finding has an invalid priority or confidence.")
        if "[REDACTED]" in finding["evidence"]:
            finding["evidence"] = "[Credential value omitted]"
    return review


def generate_review(provider, config, prompt, files, run):
    executable = config.get("executable") if config.get("provider") == provider else None
    executable = executable or shutil.which(provider)
    if not executable:
        raise AuditError(f"Install {provider}, sign in interactively once, and retry.")
    with tempfile.TemporaryDirectory(prefix="research-audit-") as temporary:
        work = Path(temporary)
        args = provider_command(provider, executable, work, config.get("model"))
        result = command(args, cwd=work, input=prompt, env=subscription_environment(config),
                         timeout=config.get("timeout_seconds", 900), check=False)
        (run / "provider.log").write_text(redact(result.stderr + "\n" + result.stdout), encoding="utf-8")
        if result.returncode:
            raise AuditError(f"{provider} exited with status {result.returncode}. Check provider.log; you may need to sign in again or wait for your usage allowance.")
        try:
            return validate_review(parse_review(provider, result.stdout, work), files)
        except (ValueError, TypeError, KeyError) as exc:
            raise AuditError("Provider returned invalid JSON. Nothing was posted; see provider.log.") from exc


def source_link(repo, sha, name, line):
    notebook = "::cell-" in name
    path = name.split("::cell-")[0]
    return f"https://github.com/{repo}/blob/{sha}/{quote(path, safe='/')}" + ("" if notebook else f"#L{line}")


def render_report(review, metadata):
    repo, sha = metadata["repository"], metadata["commit"]
    lines = [f"# Research reproducibility audit — {metadata['date']}", "",
             f"Reviewed [{sha[:10]}](https://github.com/{repo}/commit/{sha}) with **{metadata['provider']}**.", "",
             review["summary"], ""]
    # Keep every serious finding visible, even when there are more than three.
    findings = sorted(review["findings"], key=lambda f: f["priority"] != "high")
    visible_count = max(3, sum(f["priority"] == "high" for f in findings))
    if findings:
        lines += ["## Start here", ""]
    for index, finding in enumerate(findings):
        if index == visible_count:
            lines += ["<details>", f"<summary>Additional improvements ({len(findings) - visible_count})</summary>", ""]
        link = source_link(repo, sha, finding["file"], finding["line"])
        lines += [f"### {finding['priority'].capitalize()}: {finding['title']} ({finding['confidence']})", "",
                  f"[{finding['file']}, line {finding['line']}]({link})", "",
                  f"**Practice:** {finding.get('category', 'Other research risk')}", "",
                  f"> {finding['evidence']}", "", finding["why"], "", f"**Next step:** {finding['fix']}", ""]
        if finding.get("success_criterion"):
            lines += [f"**Done when:** {finding['success_criterion']}", ""]
        if finding.get("example", "").strip():
            # Choose a fence that cannot be closed by backticks in the example.
            fence = "`" * max(3, max((len(s) + 1 for s in re.findall(r"`+", finding["example"])), default=0))
            lines += ["**Example:**", "", fence, finding["example"], fence, ""]
    if len(findings) > visible_count:
        lines += ["</details>", ""]
    if not review["findings"]:
        lines += ["No supported priority findings in the inspected files. This does not establish that the analysis reproduces.", ""]
    checks = metadata["syntax_checks"]
    passed = sum(c["status"] == "passed" for c in checks)
    failed = [c for c in checks if c["status"] == "failed"]
    lines += ["### What was checked", "",
              f"Inspected {len(metadata['files'])} source/documentation entries. Python {platform.python_version()} parsing: {passed} passed, {len(failed)} failed. Other languages received code inspection only."]
    lines.extend(f"- Syntax diagnostic: `{c['file']}:{c.get('line', '?')}` — {c['reason']}" for c in failed[:3])
    lines += ["", "Project code, data acquisition, paid APIs, and the analysis were not executed. Data values and notebook outputs were excluded."]
    if metadata["omitted"]:
        lines += ["", f"Coverage is partial: {len(metadata['omitted'])} candidate file(s) were omitted; the local run.json lists them."]
    if any(c["status"] == "skipped" for c in checks):
        lines += ["Cells with notebook magics or non-Python kernels were inspected without a Python syntax check."]
    lines += ["", "Automated feedback is advisory; verify each finding before changing the analysis.", "",
              f"<!-- research-audit:{metadata['fingerprint']} -->", ""]
    return redact("\n".join(lines))


def post_report(root, repo, report, marker):
    issues = json.loads(command(["gh", "issue", "list", "--repo", repo, "--state", "all", "--limit", "100", "--json", "body,url"], cwd=root).stdout)
    for issue in issues:
        if marker in issue.get("body", ""):
            return issue["url"]
    title = report.read_text(encoding="utf-8").splitlines()[0].removeprefix("# ")
    return command(["gh", "issue", "create", "--repo", repo, "--title", title, "--body-file", report], cwd=root).stdout.strip()


def new_run(directory, sha):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    run = directory / "runs" / f"{stamp}-{sha[:8]}"
    run.mkdir(parents=True)
    return run


def perform_run(root, directory, config, args):
    with run_lock(directory):
        state = read_json(directory / "state.json", {})
        if args.scheduled:
            # Gate before GitHub, providers, retries, and overdue catch-up.
            # The fallback also expires installs made before end dates existed.
            if dt.date.today() > dt.date.fromisoformat(config.get("end_date", COURSE_END)):
                print("Course review schedule has ended; removing automatic reviews.")
                uninstall(directory)
                return
            if not config.get("scheduler"):
                return
            due = config.get("next_due", 0)
            retry = state.get("retry_after", 0)
            if time.time() < max(due, retry):
                return
        repo, branch, sha = repository_info(root, args.local)
        files, omitted, manifest = collect_sources(root, sha, state.get("files"))
        provider = args.provider or config.get("provider")
        if not provider:
            raise AuditError("Choose --provider codex, claude, or gemini, or run install first.")
        runtime_config = {**config, "model": args.model or config.get("model")}
        digest = fingerprint(manifest, provider, runtime_config.get("model"))
        previous_run = Path(state["last_run"]) if state.get("last_run") else None
        if not args.force and state.get("fingerprint") == digest and previous_run and (previous_run / "report.md").exists():
            if not args.no_post and not state.get("issue_url") and state.get("has_code"):
                try:
                    url = post_report(root, repo, previous_run / "report.md", f"<!-- research-audit:{digest} -->")
                    state["issue_url"] = url
                    write_json(directory / "state.json", state)
                    metadata = read_json(previous_run / "run.json")
                    metadata.update(status="posted", issue_url=url)
                    write_json(previous_run / "run.json", metadata)
                    print(f"Posted saved report: {url}")
                except AuditError:
                    state["retry_after"] = time.time() + 6 * 3600
                    write_json(directory / "state.json", state)
                    raise
            else:
                print(f"No relevant changes; saved report: {previous_run / 'report.md'}")
            finish_schedule(directory, config)
            return
        run = new_run(directory, sha)
        metadata = {"date": dt.date.today().isoformat(), "repository": repo, "branch": branch,
                    "commit": sha, "provider": provider, "model": runtime_config.get("model"),
                    "fingerprint": digest, "files": [f["file"] for f in files], "omitted": omitted,
                    "syntax_checks": syntax_checks(files), "status": "started", "scope": "local HEAD" if args.local else "pushed default branch"}
        write_json(run / "run.json", metadata)
        has_code = any(f["category"] == "code" for f in files)
        try:
            if has_code:
                previous = read_json(previous_run / "review.json") if previous_run else None
                previous_metadata = read_json(previous_run / "run.json", {}) if previous_run else {}
                review = generate_review(provider, runtime_config, review_prompt(files, omitted, metadata["syntax_checks"], previous, manifest, previous_metadata), files, run)
            else:
                review = {"summary": "No eligible analysis code was available in this commit. No model review was run and no issue was posted.", "findings": []}
            write_json(run / "review.json", review)
            report = run / "report.md"
            report.write_text(render_report(review, metadata), encoding="utf-8")
            shutil.copyfile(report, directory / "latest.md")
            metadata["status"] = "saved" if has_code else "no_code"
            state = {"fingerprint": digest, "files": manifest, "last_run": str(run), "has_code": has_code}
            # Save before publishing, so a failed post never requires another model call.
            write_json(directory / "state.json", state)
            write_json(run / "run.json", metadata)
            print(f"Saved report: {report}")
            if has_code and not args.no_post:
                url = post_report(root, repo, report, f"<!-- research-audit:{digest} -->")
                state["issue_url"] = metadata["issue_url"] = url
                metadata["status"] = "posted"
                print(f"GitHub issue: {url}")
            write_json(directory / "state.json", state)
            finish_schedule(directory, config)
        except Exception as exc:
            metadata.update(status="post_failed" if (run / "report.md").exists() else "failed", error=redact(str(exc)))
            state["retry_after"] = time.time() + 6 * 3600
            write_json(directory / "state.json", state)
            print(f"Run details: {run / 'run.json'}", file=sys.stderr)
            raise
        finally:
            write_json(run / "run.json", metadata)


def next_weekly(day, clock, now=None):
    now = now or dt.datetime.now()
    hour, minute = map(int, clock.split(":"))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidate += dt.timedelta(days=(DAYS.index(day) - now.weekday()) % 7)
    if candidate <= now:
        candidate += dt.timedelta(days=7)
    return candidate.timestamp()


def finish_schedule(directory, config):
    if "next_due" in config:
        config["next_due"] = next_weekly(config["day"], config["time"])
        write_json(directory / "config.json", config)


def scheduler_spec(root, config, system=None):
    system = system or platform.system()
    identity = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    label = f"edu.mit.research-audit.{identity}"
    argv = [config["python"], str(HERE / "audit.py"), "run", "--scheduled"]
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        body = {"Label": label, "ProgramArguments": argv, "WorkingDirectory": str(root),
                # Calendar events coalesce across sleep; RunAtLoad covers login
                # after shutdown. The Python due check prevents extra reviews.
                "StartCalendarInterval": {"Minute": int(config.get("time", "18:17").split(":")[1])},
                "RunAtLoad": True,
                "EnvironmentVariables": {"PATH": config["path"]},
                "StandardOutPath": str(root / ".audit" / "scheduler.log"),
                "StandardErrorPath": str(root / ".audit" / "scheduler-error.log")}
        return path, plistlib.dumps(body), label
    if system == "Windows":
        # InteractiveToken uses the signed-in student's cached CLI credentials.
        task = ET.Element("Task", {"version": "1.2", "xmlns": "http://schemas.microsoft.com/windows/2004/02/mit/task"})
        triggers = ET.SubElement(task, "Triggers")
        trigger = ET.SubElement(triggers, "TimeTrigger")
        now = dt.datetime.now()
        boundary = now.replace(minute=int(config.get("time", "18:17").split(":")[1]), second=0, microsecond=0)
        if boundary <= now:
            boundary += dt.timedelta(hours=1)
        # Optional Enabled is omitted so the shared trigger-base fields follow
        # the schema order across Task Scheduler versions.
        ET.SubElement(trigger, "StartBoundary").text = boundary.isoformat(timespec="seconds")
        repetition = ET.SubElement(trigger, "Repetition")
        ET.SubElement(repetition, "Interval").text = "PT1H"
        ET.SubElement(repetition, "StopAtDurationEnd").text = "false"
        user = command(["whoami"]).stdout.strip()
        login = ET.SubElement(triggers, "LogonTrigger")
        ET.SubElement(login, "UserId").text = user
        ET.SubElement(login, "Delay").text = "PT2M"
        unlock = ET.SubElement(triggers, "SessionStateChangeTrigger")
        ET.SubElement(unlock, "UserId").text = user
        ET.SubElement(unlock, "Delay").text = "PT2M"
        ET.SubElement(unlock, "StateChange").text = "SessionUnlock"
        principals = ET.SubElement(task, "Principals")
        principal = ET.SubElement(principals, "Principal", {"id": "Student"})
        ET.SubElement(principal, "UserId").text = user
        ET.SubElement(principal, "LogonType").text = "InteractiveToken"
        ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
        settings = ET.SubElement(task, "Settings")
        for key, value in {"MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false", "StopIfGoingOnBatteries": "false", "StartWhenAvailable": "true", "ExecutionTimeLimit": "PT30M"}.items():
            ET.SubElement(settings, key).text = value
        action = ET.SubElement(ET.SubElement(task, "Actions", {"Context": "Student"}), "Exec")
        ET.SubElement(action, "Command").text = argv[0]
        ET.SubElement(action, "Arguments").text = subprocess.list2cmdline(argv[1:])
        ET.SubElement(action, "WorkingDirectory").text = str(root)
        path = root / ".audit" / "task.xml"
        return path, ET.tostring(task, encoding="utf-16", xml_declaration=True), label
    if system == "Linux":
        # systemd's hourly timer catches missed runs at login; the Python gate is weekly.
        path = Path.home() / ".config" / "systemd" / "user" / f"{label}.service"
        def escape(value):
            return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
        body = "[Unit]\nDescription=Weekly research reproducibility review\n[Service]\nType=oneshot\n"
        body += "ExecStart=" + " ".join(escape(v) for v in argv) + "\n"
        body += "Environment=" + escape("PATH=" + config["path"]) + "\n"
        return path, body.encode(), label
    raise AuditError("Automatic scheduling supports macOS, Windows, and Linux with systemd. Run the audit command manually on other systems.")


def install(root, directory, args):
    end_date = getattr(args, "end_date", COURSE_END)
    if not args.no_schedule and dt.date.fromisoformat(end_date) < dt.date.today():
        raise AuditError("The schedule end date has passed. Use --no-schedule for manual reviews or choose a future --end-date.")
    executable = shutil.which(args.provider)
    if not executable:
        raise AuditError(f"Install {args.provider} and sign in before installing the audit schedule.")
    command(["gh", "auth", "status"])
    previous = read_json(directory / "config.json", {})
    if args.no_schedule and previous.get("scheduler"):
        uninstall(directory)
    config = {"provider": args.provider, "model": args.model, "executable": executable,
              "python": sys.executable, "path": os.environ.get("PATH", ""),
              "day": args.day, "time": args.time, "next_due": next_weekly(args.day, args.time),
              "timeout_seconds": 900, "end_date": end_date}
    if previous.get("day") == args.day and previous.get("time") == args.time:
        config["next_due"] = previous.get("next_due", config["next_due"])
    if not args.no_schedule:
        path, body, label = scheduler_spec(root, config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        system = platform.system()
        config["scheduler"] = {"path": str(path), "label": label, "system": system}
        write_json(directory / "config.json", config)
        if system == "Darwin":
            domain = f"gui/{os.getuid()}"
            command(["launchctl", "bootout", f"{domain}/{label}"], check=False)
            # Write config before loading: RunAtLoad can start the process immediately.
            write_json(directory / "config.json", config)
            command(["launchctl", "bootstrap", domain, path])
        elif system == "Windows":
            command(["schtasks", "/Create", "/TN", label, "/XML", path, "/F"])
        else:
            timer = path.with_suffix(".timer")
            timer.write_text(linux_timer(config), encoding="utf-8")
            write_json(directory / "config.json", config)
            command(["systemctl", "--user", "daemon-reload"])
            command(["systemctl", "--user", "enable", "--now", f"{label}.timer"])
        config["scheduler"] = {"path": str(path), "label": label, "system": system}
    write_json(directory / "config.json", config)
    if args.no_schedule:
        print(f"Configured {args.provider} for manual reviews; no schedule installed.")
        return
    print(f"Automatic reviews end after {end_date} (local time); the next scheduler check removes the schedule.")
    print("Stop earlier: python3 tools/research-audit/audit.py uninstall")
    print(f"Configured {args.provider}; weekly on {args.day} at {args.time} (computer's local time).")
    print("The hourly scheduler only checks whether a review is due; it does not call the model hourly.")
    print("Test now: python3 tools/research-audit/audit.py run --no-post")


def linux_timer(config):
    minute = int(config["time"].split(":")[1])
    return ("[Unit]\nDescription=Check weekly research audit schedule\n[Timer]\n"
            f"OnCalendar=*-*-* *:{minute:02d}:00\nOnStartupSec=2min\nPersistent=true\n"
            "[Install]\nWantedBy=timers.target\n")


def uninstall(directory):
    config = read_json(directory / "config.json", {})
    scheduler = config.get("scheduler")
    if not scheduler:
        print("No installed schedule recorded.")
        return
    label, path = scheduler["label"], Path(scheduler["path"])
    if scheduler["system"] == "Darwin":
        pass  # Unload last: launchctl may terminate this process.
    elif scheduler["system"] == "Windows":
        command(["schtasks", "/Delete", "/TN", label, "/F"])
    else:
        command(["systemctl", "--user", "disable", "--now", f"{label}.timer"])
        path.with_suffix(".timer").unlink(missing_ok=True)
    path.unlink(missing_ok=True)
    config.pop("scheduler")
    config.pop("next_due", None)
    write_json(directory / "config.json", config)
    print("Schedule removed. Saved reports are preserved.", flush=True)
    if scheduler["system"] == "Darwin":
        command(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], check=False)


def date_value(value):
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD, for example 2026-12-04.") from exc


def clock_value(value):
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise argparse.ArgumentTypeError("Use 24-hour HH:MM, for example 18:17.")
    return value


def render_status(directory, config, state, now=None):
    """Summarize saved local information without contacting GitHub or a provider."""
    now = now or dt.datetime.now()
    def local_time(stamp):
        return dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")

    provider = config.get("provider")
    lines = [f"Provider: {provider or 'not configured'}"]
    if config.get("scheduler"):
        end = config.get("end_date", COURSE_END)
        if now.date() > dt.date.fromisoformat(end):
            lines += [f"Automatic reviews: ended after {end}.",
                      "Schedule removal is pending the next scheduler check."]
        else:
            day = config.get("day", "sun")
            weekday = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")[DAYS.index(day)]
            lines += [f"Automatic reviews: configured weekly on {weekday} at {config.get('time', '18:17')} (local time).",
                      f"Last day of automatic reviews: {end} (local time)."]
            due = max(config.get("next_due", 0), state.get("retry_after", 0))
            if due <= now.timestamp():
                lines += ["Next review: overdue; will be attempted at the next scheduler check."]
            elif dt.datetime.fromtimestamp(due).date() > dt.date.fromisoformat(end):
                lines += ["No further automatic reviews are due before the end date."]
            else:
                lines += [f"Next review due: {local_time(due)} (local time)."]
            lines += ["Reviews require this computer to be on, logged in, and connected to the internet."]
        lines += ["Stop automatic reviews: python3 tools/research-audit/audit.py uninstall"]
    else:
        lines += ["Automatic reviews: off. You can run reviews manually."]

    latest = directory / "latest.md"
    lines += [f"Latest saved report: {latest}" if latest.exists() else "Latest saved report: none yet."]
    if state.get("issue_url"):
        lines += [f"Last published report: {state['issue_url']}"]

    # The last attempt can have failed before replacing the last saved report.
    attempts = sorted((directory / "runs").glob("*/run.json"))
    if attempts:
        details = attempts[-1]
        metadata = read_json(details, {})
        labels = {"started": "not completed", "saved": "report saved locally; not posted",
                  "posted": "report posted to GitHub", "no_code": "no eligible analysis code; no model call or issue",
                  "failed": "review failed; no new report posted", "post_failed": "report saved, but posting failed"}
        result = metadata.get("status", "unknown")
        lines += [f"Latest attempt: {metadata.get('date', 'unknown date')} — {labels.get(result, result)}."]
        if metadata.get("commit"):
            lines += [f"Reviewed commit: {metadata['commit'][:10]} ({metadata.get('scope', 'scope not recorded')})."]
        if metadata.get("error"):
            lines += [f"Problem: {metadata['error']}"]
        if result == "post_failed":
            lines += ["Check GitHub access with gh auth status, then rerun the review to retry posting the saved report."]
        elif result == "failed":
            lines += [f"Run details: {details}"]
            if (details.parent / "provider.log").exists():
                lines += [f"CLI log: {details.parent / 'provider.log'}"]
            if any(word in metadata.get("error", "").lower() for word in ("auth", "sign in", "login")):
                cli = metadata.get("provider", provider or "your model CLI")
                lines += [f"For a model login problem, open {cli} interactively, sign in, and retry."]
        provider = provider or metadata.get("provider")
    command = "python3 tools/research-audit/audit.py run"
    if not config.get("provider"):
        command += f" --provider {provider or 'codex'}"
    lines += [f"Preview a review without posting: {command} --no-post"]
    return redact("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    setup = commands.add_parser("install", help="Configure a provider and install a weekly local schedule")
    setup.add_argument("--provider", choices=PROVIDERS, required=True)
    setup.add_argument("--model", help="Optional model supported by your subscription; otherwise use the CLI default")
    setup.add_argument("--day", choices=DAYS, default="sun")
    setup.add_argument("--time", type=clock_value, default="18:17")
    setup.add_argument("--end-date", type=date_value, default=COURSE_END,
                       help="Last day of automatic reviews, local time (default: %(default)s)")
    setup.add_argument("--no-schedule", action="store_true", help="Configure manual runs only")
    run = commands.add_parser("run", help="Review pushed default-branch code and post an issue")
    run.add_argument("--provider", choices=PROVIDERS)
    run.add_argument("--model")
    run.add_argument("--no-post", action="store_true", help="Save the report locally without posting an issue")
    run.add_argument("--force", action="store_true", help="Review again even if inputs have not changed")
    run.add_argument("--local", action="store_true", help="Review committed local HEAD rather than fetching the pushed default branch")
    run.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    status = commands.add_parser("status", help="Show the schedule, latest report, and any recorded problem")
    status.add_argument("--json", action="store_true", help="Show raw configuration and state for troubleshooting")
    commands.add_parser("uninstall", help="Remove the schedule and preserve reports")
    args = parser.parse_args(argv)
    if args.action == "run" and args.local and not args.no_post:
        raise AuditError("--local is a preview; add --no-post so unpushed commits cannot produce broken issue links.")
    root = project_root()
    directory = state_dir(root)
    if args.action == "install":
        install(root, directory, args)
    elif args.action == "uninstall":
        uninstall(directory)
    elif args.action == "status":
        config = read_json(directory / "config.json", {})
        state = read_json(directory / "state.json", {})
        if args.json:
            print(json.dumps({"config": config, "state": state, "latest_report": str(directory / "latest.md")}, indent=2))
        else:
            print(render_status(directory, config, state))
    else:
        perform_run(root, directory, read_json(directory / "config.json", {}), args)


if __name__ == "__main__":
    try:
        main()
    except (AuditError, ValueError, KeyError) as error:
        print(f"Audit stopped: {error}", file=sys.stderr)
        sys.exit(1)
