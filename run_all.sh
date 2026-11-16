#!/usr/bin/env bash
#
# run_all.sh — rebuild the paper from scratch.
#
#   1. Run the analysis, which (re)writes the files in paper_output/.
#   2. Compile the paper into paper.pdf.
#
# Run this whenever your analysis changes. Dependencies are listed in
# Step 0 of the guide; this script assumes they are installed and on PATH.
#
# Usage, from the project root:
#   bash run_all.sh          (or:  chmod +x run_all.sh  &&  ./run_all.sh)

set -euo pipefail

# Always work from the folder this script lives in (the project root),
# so it can be run from anywhere.
cd "$(dirname "$0")"

# ===================== CONFIG — edit these two ======================
# 1) Your analysis. List every command that writes to paper_output/.
run_analysis() {
  python3 code/analyze.py
  # Add more steps here if your analysis has several, e.g.:
  #   python3 code/clean.py
  #   Rscript    code/figures.R
}

# 2) Which paper to build: "quarto" (builds paper.qmd) or "latex"
#    (builds paper.tex). Set this to match your project.
#    NOTE: if you build with quarto, do NOT keep a paper.tex in this
#    folder — `quarto render` creates and then deletes its own paper.tex
#    and will overwrite yours.
PIPELINE="quarto"
# ====================================================================

echo "==> [1/2] Running the analysis"
run_analysis

echo "==> [2/2] Compiling the paper (pipeline: $PIPELINE)"
case "$PIPELINE" in
  quarto)
    command -v quarto >/dev/null 2>&1 \
      || { echo "ERROR: quarto not found (see Step 0 of the guide)." >&2; exit 1; }
    quarto render paper.qmd
    ;;
  latex)
    if command -v latexmk >/dev/null 2>&1; then
      latexmk -pdf paper.tex
    elif command -v pdflatex >/dev/null 2>&1; then
      echo "    latexmk not found; running pdflatex twice instead."
      pdflatex -interaction=nonstopmode paper.tex
      pdflatex -interaction=nonstopmode paper.tex
    else
      echo "ERROR: neither latexmk nor pdflatex found (see Step 0 of the guide)." >&2
      exit 1
    fi
    ;;
  *)
    echo "ERROR: PIPELINE must be \"quarto\" or \"latex\", not \"$PIPELINE\"." >&2
    exit 1
    ;;
esac

if [ -f paper.pdf ]; then
  echo "==> Done. Wrote paper.pdf"
else
  echo "ERROR: build finished but paper.pdf was not created." >&2
  exit 1
fi
