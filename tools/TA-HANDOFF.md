# TA handoff: review the weekly audit and develop interactive project quizzes

Please review the weekly research code audit for usefulness and reliability,
then develop two interactive project quizzes: **quiz-code** and **quiz-design**.
The audience is undergraduate economics researchers using Codex, Claude Code,
or Gemini CLI through an existing subscription/Google login. Keep installation
and maintenance simple. This is a review and development brief; the quiz tools
have not been implemented yet.

## 1. Review the existing weekly audit

Start with these files:

- [Student setup and artifact guide](research-audit/README.md)
- [Research review rubric](research-audit/rubric.md)
- [Runner and scheduler](research-audit/audit.py)
- [Offline tests](research-audit/test_audit.py)

The current implementation reviews the pushed default branch, checks Python
syntax without executing project code, and generates at most three findings.
It saves a Markdown report and JSON run details under `.audit/runs/`, copies the
latest report to `.audit/latest.md`, and can publish the report as a GitHub issue.
It skips unchanged inputs and retains a report if publishing fails. Local
schedules remember overdue reviews and check after login/wake as well as hourly.
It does **not** run the analysis, access project APIs, or establish that results
reproduce.

The 25 offline tests pass. They simulate provider output, GitHub writes, and
schedule files; they are **not** evidence that live authentication and OS
scheduling work on every provider/computer combination. Please close that gap.

Work on a branch and use a scratch GitHub repository containing a small example
analysis for publishing and scheduler tests. The empty template itself has no
eligible analysis code, so reviewing it will not exercise the model integration.

```sh
git switch -c ta/audit-review-and-quizzes
python3 -m unittest discover -s tools/research-audit -p 'test_*.py' -v
python3 tools/research-audit/audit.py run --provider codex --no-post
```

Replace the provider with `claude` or `gemini` as needed. For a committed local
test fixture, add `--local --no-post`. Use the scratch repository to exercise
issue publication; use `--no-post` when reviewing real student projects.

Concentrate the review on four questions:

1. **Does the advice help a student?** Compare reports from a few projects with
   your own reading. Findings should identify a concrete research risk, explain
   its consequence, and suggest a manageable fix. Check false positives: a
   documented sample period is not bad hardcoding, and a join without an
   assertion is not proof of duplicate observations. Include examples with a
   personal path, inconsistent units, missing API setup, and legitimate
   documented constants. Assess cross-file reasoning and partial coverage.
2. **Does each provider work with a real login?** Try Codex, Claude Code, and
   Gemini CLI using their normal signed-in accounts. Confirm that the runner
   produces valid findings and useful errors, uses the intended account, and
   recovers from expired login or exhausted usage. Record CLI versions and any
   combination you could not test. Do not assume an offline mock proves this.
3. **Does automation behave correctly?** On the operating systems students
   actually use, verify installation, an overdue run after shutdown/sleep and
   return, no repeated model calls for unchanged code, and uninstall. Check the
   operating system's real task registration, not just generated XML/plist text.
   Verify a failed GitHub post preserves the report and can be retried without
   another model call. Use a near-term test schedule and restore the weekly one.
4. **Can a student follow the instructions?** Test receiving the tool in an
   existing project, first login, preview, publication, scheduling, and finding
   the saved artifacts. Look for unnecessary steps, confusing feedback, and
   obstacles on Windows or with missing data. Confirm that local work, secrets,
   and project data are not inadvertently included or modified.

Deliver a short review memo with prioritized problems and suggested
improvements, one or two representative reports with your assessment, and a
record of what you tested. Fix clear bugs on the branch; explain larger changes
in the pull request. Prioritize reliable operation and useful feedback over
expanding the number of checks.

## 2. Develop the two quizzes

Build interactive tutoring workflows inside the student's existing CLI. A
terminal conversation is a sufficient first interface; no website, separate API
backend, or scheduled quiz is needed. Students should be able to start a quiz
with a short command in their project and use the same subscription they already
use for the CLI.

Keep the teaching instructions shared across providers. Use thin provider
adapters to load those instructions rather than maintain three independent
versions of each quiz. A practical arrangement is shared Markdown under
`tools/project-quizzes/` with repository-local skills/commands that read it.
Avoid relying on symlinks, which complicate Windows distribution.

| CLI | Suggested adapter | Student invocation |
|---|---|---|
| Codex | `.agents/skills/quiz-code/SKILL.md` and a corresponding `quiz-design` skill | `$quiz-code` or `$quiz-design`; selection through `/skills` is another option. |
| Claude Code | `.claude/skills/quiz-code/SKILL.md` and a corresponding `quiz-design` skill | `/quiz-code` or `/quiz-design`. Make them explicitly invoked workflows. |
| Gemini CLI | `.gemini/commands/quiz-code.toml` and `quiz-design.toml`, loading the shared instructions | `/quiz-code` or `/quiz-design`. Gemini also supports repository-local skills. |

The command spelling need not be identical across products. Verify discovery
and invocation on the installed CLI versions and document each. A plain-language
fallback, such as “Read tools/project-quizzes/quiz-code.md and quiz me,” should
also work. Codex's skill creator can help draft the Codex adapter; keep the
learning behavior in the shared instructions.

### quiz-code: can the student explain their implementation?

Read the README, relevant active scripts/notebooks, dependency information, and
data setup instructions. Select a bounded part of the actual pipeline; do not
try to read every file before asking the first question. Note the inspected
branch/commit and whether local changes were included.

Ask questions that require reasoning about specific code, for example:

- Trace one observation from an input through cleaning, a merge, the estimation
  sample, and an output. What is the unit of observation at each stage?
- Explain a selected block in the student's own words. What does each important
  variable measure, and in what units?
- Predict the effect of a small change before running anything. What happens
  if a join key is duplicated, a value is missing, or a filter changes?
- Explain an assumption behind a transformation, weighting choice, random
  seed, or dependency on execution order. Suggest a small way to check it.
- Diagnose an apparent inconsistency using the code as evidence.

Favor conceptual tracing, prediction, and debugging over memorizing syntax.
Reference real paths and snippets; do not invent functions or data properties.
Use small hypothetical inputs when private or unavailable data would otherwise
be needed. Do not edit the analysis or execute acquisition/paid API calls.

### quiz-design: can the student defend their research choices?

Read the available research question, proposal/design notes, paper source, and
relevant analysis code. If the design is not documented, ask for a short
description before generating substantive questions. Distinguish the planned
design from what the code currently implements. Do not invent an identification
strategy or imply every project is causal.

Adapt questions to the actual project, for example:

- State the research question, target population, unit of analysis, and quantity
  the project aims to estimate. Is the claim descriptive, predictive, or causal?
- Explain how the data, sample, measurements, and specification answer that
  question. What does the main estimate mean in substantive units?
- For a causal design, explain the relevant comparison/counterfactual and
  identifying assumptions. Name a plausible violation and explain its effect.
- For descriptive or predictive work, discuss representativeness, measurement,
  leakage, validation, and the limits of the conclusions as appropriate.
- Propose one informative diagnostic, falsification, robustness exercise, or
  alternative explanation, and explain what it would and would not establish.
- Connect a design choice to its implementation: does the code's sample,
  variable construction, timing, or model match the stated research plan?

Allow multiple defensible answers. Separate conceptual errors from reasonable
research judgments and unresolved decisions that should be discussed with the
instructor. Ground feedback in the student's materials and the reasoning they
provide.

## 3. Shared interaction requirements

- Start a short session of roughly five questions or 10–15 minutes, with an
  option to focus on a file, a topic, or a recently changed part of the project.
- **Ask one question, then stop and wait for the student's answer.** Do not
  generate the full answer key or complete both sides of the conversation.
- After an attempt, give brief, specific feedback. Ask one follow-up when the
  answer is incomplete; offer progressively stronger hints when requested.
  Explain the answer after a reasonable attempt or an explicit request to skip.
- Adapt difficulty to the responses. Use new applications or counterexamples
  to distinguish understanding from repeating terminology. Avoid giving away
  the answer in the question.
- Keep reading and model usage bounded. Use relevant project context, carry
  forward the student's answers, and avoid rereading the entire repository for
  each question. Avoid student-specific hardcoded paths or model names.
- Finish with a brief summary of demonstrated understanding, remaining
  uncertainties, and one or two targeted practice steps. Offer a local Markdown
  summary in an ignored directory such as `.quiz/`; make it easy for the student
  to share at a meeting. Do not automatically post answers or transcripts as
  GitHub issues. Keep quiz artifacts separate from automated audit state.
- Treat the quizzes as formative practice. An LLM's assessment is not proof of
  mastery or authorship, and should not become an automatic course grade.

The code audit and the quizzes serve different purposes: the audit identifies
research-code risks; the quiz asks the student to reason through their own
implementation and research choices. An audit finding can inspire a question,
but the quiz should not simply read out the audit and ask the student to agree.

## 4. Pilot and deliver

Start with one provider and two contrasting example projects. Test a strong
answer, a plausible wrong answer, an incomplete answer, a hint request, and a
project with missing design documentation. Check that the tutor waits for input,
does not reveal answers prematurely, and gives evidence-based feedback. Then
exercise the same shared instructions through all three provider adapters.

Deliver a pull request containing the shared instructions, minimal adapters,
short student setup/invocation instructions, and an example dialogue for each
quiz. Include brief pilot observations and remaining limitations. Ask the
instructor to review the learning goals and sample questions before classroom
rollout. The first version should work as a small set of text files without a
new service or API account.

Provider references checked for this brief:

- [Codex: build skills, repository locations, and explicit invocation](https://learn.chatgpt.com/docs/build-skills)
- [Claude Code: skills and custom slash commands](https://code.claude.com/docs/en/skills)
- [Gemini CLI: custom slash commands](https://geminicli.com/docs/cli/custom-commands/)
- [Gemini CLI: repository-local Agent Skills](https://geminicli.com/docs/cli/skills/)
