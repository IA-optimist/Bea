.PHONY: ci-local ci-local-no-lint p2-hardening-apply clean-workspace

ci-local:
	bash scripts/ci/local_ci.sh

ci-local-no-lint:
	python -m pip install --upgrade pip
	python -m pip install -r requirements.txt
	python -m pip install pytest pytest-cov pytest-asyncio pytest-xdist
	DATABASE_URL=$${DATABASE_URL:-postgresql://localhost:5432/beamax_test} \
	REDIS_URL=$${REDIS_URL:-redis://localhost:6379} \
	TESTING=$${TESTING:-true} \
	pytest tests/ -v -n auto --dist=loadfile --cov=core --cov-report=xml --cov-report=term --cov-fail-under=55

p2-hardening-apply:
	bash scripts/github/apply_p2_repo_hardening.sh IA-optimist/Bea main

# Hygiène locale : archive les vieux builds, purge les caches Python.
# DRY_RUN=1 pour prévisualiser, KEEP_DAYS=N pour ajuster la rétention.
clean-workspace:
	bash scripts/clean_workspace.sh
