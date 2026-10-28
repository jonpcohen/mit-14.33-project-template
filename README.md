# Research project title

Replace this text with a one-sentence description of the research question.

## Reproducing the project

Document the software requirements and the single command needed to reproduce the analysis. Until the project has a one-command workflow, list the scripts in the exact order they should be run.

## Meeting preparation and project decisions

On your project's GitHub page, select **Issues → New issue** and choose
**Meeting preparation** to prepare for a 1-on-1 meeting, or **Project decision or question**
to document a consequential question or decision. The templates contain the
prompts to complete.

## Weekly research code review

The [audit setup guide](tools/research-audit/README.md) explains how to enable
weekly code reviews on your computer using an existing Codex, Claude Code, or
Gemini CLI login. Reviews examine the pushed default branch and post a brief
GitHub issue; they do not run the analysis. The latest local report is saved
at `.audit/latest.md`, which is ignored by Git.

## Repository structure

| Directory | Purpose |
|---|---|
| `code/` | Scripts used to acquire, clean, analyze, and visualize data |
| `data/raw/` | Original source data; ignored by Git unless explicitly allowed |
| `data/derived/` | Data created by the project's code; ignored by Git unless explicitly allowed |
| `output/` | Generated figures, tables, and other results |
| `paper/` | Paper source files and rendered drafts |
| `tools/research-audit/` | Weekly code review tool, setup instructions, and review rubric |

## Working practices

- Keep the `main` branch in a usable state.
- Use GitHub issues to record consequential tasks, questions, and decisions.
- Use short-lived branches to test important alternatives, then record the conclusion in the related issue.
- Commit small, coherent changes with descriptive messages.
- Never commit passwords, API keys, restricted data, or personally identifiable information.
- Update this README whenever the reproduction steps or directory structure change.
