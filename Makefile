.PHONY: ci-local ci-local-no-lint p2-hardening-apply

ci-local:
	bash scripts/ci/local_ci.sh

ci-local-no-lint:
	python -m pip install --upgrade pip
	python -m pip install -r requirements.txt
	python -m pip install pytest pytest-cov pytest-asyncio pytest-xdist
	DATABASE_URL=$${DATABASE_URL:-postgresql://localhost:5432/jarvismax_test} \
	REDIS_URL=$${REDIS_URL:-redis://localhost:6379} \
	TESTING=$${TESTING:-true} \
	pytest tests/ -v -n auto --dist=loadfile --cov=core --cov-report=xml --cov-report=term --cov-fail-under=55

p2-hardening-apply:
	bash scripts/github/apply_p2_repo_hardening.sh IA-optimist/Bea main
