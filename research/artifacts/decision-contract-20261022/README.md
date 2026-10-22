# Decision-contract manuscript and numerical results

[Read the manuscript](paper/main.pdf) · [LaTeX source](paper/main.tex) · [Follow-up results](results.json)

This working preprint incorporates reference reuse, repeated sampling, the feedback ladder, and the discarded metamorphic alarm module. Frozen results and post-hoc reading sensitivity remain separate from the follow-ups. It is not a statement of conference acceptance.

Numerical sources are `baselines.json` and `rescore.json` for the original tables, with field mappings in `tables.json`; `results.json` contains the follow-up summaries, derived per-problem outcomes, source hashes, and dataset-partition counts. Generated TeX macros and cells quote these sources. Original prompts, model responses, problem text, credentials, and local source snapshots are not included.

The reference-reuse stage uses published NL4Opt structured annotations. No new human labels were collected, and human agreement is inapplicable. The metamorphic false-alarm fraction is conditional on the mapped official reference. The module's `discard_module` field is authoritative. The feedback ladder includes reference-assisted stopping and heuristic annotation-assisted anchors; these conditions are described in the manuscript.

## Check the published numerical aggregates

From the repository root, with Python 3.10 or newer:

```sh
python -B -m unittest discover -s tests -p test_decision_contract_protocol.py
node --test tests/decision-budget.test.mjs
```

These checks recompute published follow-up counts and intervals from the included derived outcomes. Tests requiring unshared frozen inputs are explicitly skipped on a clean checkout. They do not reconstruct model answers from the derived outcomes. Owners of the local archive can additionally run `python -m research.replay --check` to reconstruct the original tables from raw responses.

## Compile

With a TeX distribution providing pdfLaTeX, BibTeX, and the packages used in `paper/main.tex`:

```sh
cd research/artifacts/decision-contract-20261022/paper
pdflatex -interaction=nonstopmode -halt-on-error main.tex
bibtex main
pdflatex -interaction=nonstopmode -halt-on-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error main.tex
```

Windows users can run `paper/build.ps1`. The included AAAI template files retain their original notices and are used in preprint mode. Project-authored materials retain the repository's existing license.

Dataset attribution: NL4Opt competition, Ramamonjison et al., PMLR 220; source repository <https://github.com/nl4opt/nl4opt-competition>, revision `49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea`. The original benchmark text and annotation files remain in the local archive. Bibliographic links are recorded in `paper/refs.bib`.

`manifest.json` records the SHA-256 digest and size of each published file. It is a publication inventory, not an independent semantic validation of the underlying reference labels.
