# Weekly research reproducibility audit

This tool reviews undergraduate economics research code and posts a short GitHub
issue with at most three priorities. It uses **your existing signed-in CLI**:
Codex with ChatGPT, Claude Code with Claude, or Gemini CLI with Google. Separate
API keys are not required. Runs count toward your account's usage allowance.

It reviews the latest **pushed default branch**, even if your local checkout is
on another branch or has uncommitted work. It fetches commits but does not pull,
merge, switch branches, edit project files, or run the analysis.

## One-time setup

You need Git, Python **3.10 or newer**, GitHub CLI (`gh`), and one of the three
model CLIs. On Windows, use a normal PowerShell terminal and native Windows
Python/CLIs for Task Scheduler. In WSL, use the Linux instructions and a working
user systemd service instead. Use `python` or `py -3` below if your Python
installation does not provide `python3`.

1. Install [GitHub CLI](https://cli.github.com/) and sign in:

   ```sh
   gh auth login
   ```

2. Install your chosen CLI and sign in interactively once:

   | Provider | Installation and login |
   |---|---|
   | Codex | Follow the [Codex CLI setup](https://learn.chatgpt.com/docs/cli), run `codex`, and select **Sign in with ChatGPT**. |
   | Claude | Follow the [Claude Code setup](https://code.claude.com/docs/en/quickstart), run `claude`, and select your **Claude subscription**. |
   | Gemini | Follow the [Gemini CLI setup](https://geminicli.com/docs/get-started/), run `gemini`, and select **Sign in with Google**, using the Google account associated with your subscription if applicable. |

   Use your subscription/Google login rather than a Console API key. The runner
   removes common API-key environment variables from the model process to avoid
   accidental API billing. Keep your CLI configured for the intended account.
   Do not copy login files or credentials into this repository.

3. Open a terminal in your project repository and test a local-only report.
   Replace `codex` with `claude` or `gemini` as appropriate:

   ```sh
   python3 tools/research-audit/audit.py run --provider codex --no-post
   ```

   Inspect `.audit/latest.md`. A project with no eligible analysis code gets a
   local report without a model call or a GitHub issue. If you have code, the
   command below publishes the saved report without paying for another review:

   ```sh
   python3 tools/research-audit/audit.py run --provider codex
   ```

4. Enable weekly reviews, choosing your provider:

   ```sh
   python3 tools/research-audit/audit.py install --provider codex
   ```

   The default is **Sunday at 18:17 in your computer's local time**. To change it:

   ```sh
   python3 tools/research-audit/audit.py install --provider gemini --day fri --time 16:17
   ```

   `--model MODEL_NAME` is optional. Leave it out to use your CLI's available
   default rather than copying a model name your subscription may not support.

Pulling these files does **not** install a schedule. Complete step 4 on the
computer that will run the audit. Re-run installation if you move the project,
change providers, or replace your Python/CLI installation.

## What the schedule does

- macOS: installs a per-user LaunchAgent.
- Windows: installs a Task Scheduler task for the signed-in user.
- Linux: installs a systemd user service and timer.

The scheduler checks once an hour whether the weekly review is due. **It does
not call the model hourly.** It also checks after login/startup: macOS runs a
check when the LaunchAgent loads and catches up calendar events missed during
sleep; Windows checks about two minutes after login or unlocking; Linux checks
about two minutes after the user's service manager starts and catches up missed
calendar events. Opening a laptop usually wakes it; unlocking/logging in ensures
the student's session and saved credentials are available.

An overdue audit runs **once**, reviewing the latest pushed code. It does not
produce a backlog if several weeks were missed. Keep the computer connected to
the internet and logged in. If the network is not ready at login/wake, the next
hourly check retries. A sleeping/offline computer or an expired login can delay
a report. Usage limits can also interrupt a review.
Failed model or publishing attempts are retried after a six-hour delay; a failed
fetch or repository lookup is retried at the next hourly check.

The schedule is local, not a GitHub Actions job. No terminal window needs to stay
open. It cannot produce a report while the student's computer remains off.
After updating the scheduling code, re-run the same `install --provider ...`
command to refresh the operating-system schedule. Reinstalling with the same
day and time preserves an already-overdue review.

## Saved artifacts

Each new review uses a directory such as:

```text
.audit/
  config.json
  state.json
  latest.md
  runs/
    2026-10-27T18-17-00-123456Z-a1b2c3d4/
      report.md
      review.json
      run.json
      provider.log
```

| Artifact | Contents |
|---|---|
| GitHub issue | The readable report, with links to the exact reviewed commit and code lines. This is the shared artifact for the student, instructor, and TA. |
| `report.md` | A local Markdown copy, saved **before** posting the issue. |
| `review.json` | The structured summary and findings used to create the report. |
| `run.json` | Reviewed commit, provider/model selection, inspected and omitted files, syntax results, status, errors, and issue URL when posted. |
| `provider.log` | CLI output for troubleshooting. May contain source excerpts; keep it local. Not created when no model call is needed. |
| `.audit/latest.md` | A convenient copy of the latest successfully generated report. Check run status if publication failed. |

`.audit/` is ignored by Git and also added to the clone's local Git exclusion
file. Credentials are not stored in it. Reports and logs are not committed or
pushed; the **issue** is what other people see. A failed model call leaves run
details and any available log, without publishing an incomplete report.

If relevant inputs have not changed, the run reuses the prior report instead of
calling the model or opening another issue. If posting failed, the next run
retries the saved report. An identifying marker prevents duplicate issues for
the same review among the repository's 100 most recent issues. Reports are
preserved until you remove the local `.audit/` directory yourself.

## Review scope and limits

The [rubric](rubric.md) focuses on portability, execution order, dependency and
data-access instructions, fragile hardcoding, joins, units, sample restrictions,
and inconsistent transformations. Findings require matching file-and-line
evidence. An unverified risk is labeled **check**, rather than called a proven
error. The report is advisory; matching evidence does not prove the diagnosis.

The runner reads committed source and setup documentation directly from Git.
It excludes data values, paper contents, generated output, notebook outputs,
test suites, installed packages, and directories named `archive` or `archived`.
README files describing data and outputs remain eligible. It does not inspect
uncommitted work. Recognizable tokens and literal credential assignments are
redacted before review; do not commit secrets or confidential material in the
first place. Eligible code is sent to your chosen provider under your account.

Python files and ordinary Python notebook cells receive a parse-only syntax
check using the installed Python version; no imports or project code run.
Notebook cells with magics or non-Python kernels are inspected without that check. Other languages
receive model inspection only. Invalid notebook JSON and oversized files are
listed as omissions. Reviews are capped at 60 KB per file and 240 KB of source
per run; setup files and changed code are prioritized. A partial review is
explicitly identified in the report. Notebooks may be up to 10 MB including
outputs, but only their source cells enter the 60 KB per-file source allowance.
Notebook citations name the code cell and
its source line, with a link to the notebook; these are not JSON line numbers.

**This version does not execute the analysis**, acquire data, contact project
APIs, or establish that results reproduce. Missing data and paid services are
reviewed through the code and setup instructions. The model receives a supplied
source bundle in a temporary directory, not the student's working tree.

## Useful commands

```sh
# Show schedule configuration, last run, and report location
python3 tools/research-audit/audit.py status

# Run now (uses the installed provider configuration)
python3 tools/research-audit/audit.py run

# Re-review unchanged inputs without posting
python3 tools/research-audit/audit.py run --provider codex --force --no-post

# Preview committed local HEAD rather than fetching the remote default branch
python3 tools/research-audit/audit.py run --provider codex --local --no-post

# Configure manual use without installing a schedule
python3 tools/research-audit/audit.py install --provider claude --no-schedule

# Remove the schedule, preserving every saved report
python3 tools/research-audit/audit.py uninstall
```

For authentication failures, open the chosen CLI interactively, sign in again,
and retry the audit. For GitHub errors, run `gh auth status` and verify that
issues are enabled for the repository. On macOS, scheduler output is in
`.audit/scheduler.log` and `.audit/scheduler-error.log`. On Linux, use
`journalctl --user -u 'edu.mit.research-audit.*'`. On Windows, inspect Task
Scheduler's Last Run Result and the local run details.

## Adding this tool to an existing student project

Repositories generated with **Use this template** do not automatically receive
updates. From the student's repository, the following copies only the new audit
directory, preserving the student's README, analysis, and Git history:

```sh
git fetch https://github.com/jonpcohen/mit-14.33-project-template.git main
git restore --source=FETCH_HEAD -- tools/research-audit
git add tools/research-audit
git commit -m "Add weekly research code review tools"
git push
```

Start with a clean working tree. If `tools/research-audit` already exists with
local edits, commit or preserve those edits before updating. This command
copies the specified directory from the fetched template version; it does not
merge local modifications within that directory. The installer protects
`.audit/` locally even without copying the template's `.gitignore` change.
Then complete the one-time setup above. If the instructor instead adds these
files directly to your own remote repository, receive that commit through your
normal pull process before setup.

## Maintainer validation

```sh
python3 -m unittest discover -s tools/research-audit -p 'test_*.py' -v
```

Official references: [Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Claude noninteractive mode](https://code.claude.com/docs/en/headless), and
[Gemini cached authentication in headless mode](https://geminicli.com/docs/get-started/authentication/#running-in-headless-mode).
