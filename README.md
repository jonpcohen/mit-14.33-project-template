# Research project title

Replace this text with a one-sentence description of the research question.

## Reproducing the project

Document the software requirements, working software/package versions, and the
single command needed to reproduce the analysis from the documented inputs. A
master script can call separate cleaning, analysis, and output scripts. Until the
project has a one-command workflow, list the scripts in the exact order they
should be run and explain any manual steps.

Explain how to set up the software environment and run the analysis within it.
For Python projects using external packages, use a project-specific virtual
environment or equivalent managed environment. Keep the environment directory
out of Git and record the dependencies needed to recreate it.

For data obtained outside the code, document the provider/dataset, source link,
release/version or vintage where available, retrieval date, and instructions for
obtaining the same files, including download selections or filters, expected
filenames, and where to place them. Explain any access restrictions. A linked
data README, such as `data/raw/README.md`, can hold these details. For sources
that revise their data, identify the release or saved extract used as precisely
as possible.

If your package manager generates a lockfile, keep it in Git and document how to
install from it. A lockfile records the exact package versions selected by the
tool. For a simple Python project using pip, a pinned `requirements.txt` plus the
Python version and installation command is a reasonable starting point.

Identify the final outputs, where they are saved, and which scripts produce them.
Clear filenames or a short description can suffice. Note any special operating
system/software requirements or substantial runtime, storage, or download needs.

## Meeting preparation and project decisions

On your project's GitHub page, select **Issues → New issue** and choose
**Meeting preparation** to prepare for a 1-on-1 meeting, or **Project decision or question**
to document a consequential question or decision. The templates contain the
prompts to complete.

## Weekly research code review

The [audit setup guide](tools/research-audit/README.md) explains how to enable
optional weekly code reviews through December 4, 2026, on your computer using an existing Codex, Claude Code, or
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
- Preserve original input data and make cleaning steps reproducible in code.
  Save derived data separately and make their creation reproducible from a fresh session.
- Generate final tables and figures from code and save them to files. Keep key
  reported numbers traceable to the generated results.
- Update this README whenever the reproduction steps or directory structure change.
