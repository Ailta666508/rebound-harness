.PHONY: test lint benchmark frontend build
test:
	python -m pytest -q
lint:
	python -m ruff check src tests examples
	python -m mypy src/rebound
benchmark:
	rebound benchmark --output benchmarks/local-results --seeds 2 --lengths 4,16,32
frontend:
	cd frontend && pnpm install --frozen-lockfile && pnpm build
build: frontend
	python -m build
