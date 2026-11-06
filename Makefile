PY ?= python
.PHONY: data data-verify setup db test ingest synth-changes benchmark ablate robustness llm-eval app reproduce clean-results

setup:            ## install package + dev deps
	$(PY) -m pip install -e ".[dev,db]"
db:               ## start Postgres and apply schema
	docker compose up -d db
test:
	$(PY) -m pytest -q
data:             ## download + audit + build curated RCAEval copy (Zenodo is 39 GB; mirror is 3.3 GB)
	$(PY) -I scripts/download_rcaeval.py
	$(PY) -I scripts/download_zenodo.py
	$(PY) -I scripts/compare_hf_zenodo.py || true
	$(PY) -I scripts/build_rcaeval_processed.py
	$(PY) -I scripts/verify_rcaeval.py data/processed/rcaeval
	$(PY) -I scripts/derive_call_graph.py
data-verify:      ## re-run structural checks on the curated copy
	$(PY) -I scripts/verify_rcaeval.py data/processed/rcaeval
ingest:           ## load RCAEval into data/processed (see docs/NEXT_STEPS.md)
	$(PY) -m cloudrca.ingest.rcaeval --src data/processed/rcaeval --out data/processed/cases
synth-changes:    ## synthetic change events (seeded)
	$(PY) -m cloudrca.ingest.synth_changes --config configs/eval.yaml
benchmark:        ## main table: baselines vs ours on the test split
	$(PY) -m cloudrca.eval.run_rca_eval --config configs/eval.yaml
ablate:
	$(PY) -m cloudrca.eval.run_rca_eval --config configs/eval.yaml --ablations
robustness:
	$(PY) -m cloudrca.eval.robustness --config configs/eval.yaml
llm-eval:
	$(PY) -m cloudrca.eval.run_llm_eval --config configs/llm.yaml
app:
	streamlit run app/Home.py
reproduce: ingest synth-changes benchmark ablate robustness llm-eval
clean-results:
	rm -rf results/*
