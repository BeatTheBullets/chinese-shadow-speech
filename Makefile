.PHONY: dev test backend frontend
backend:
	cd backend && uv run uvicorn shadow.main:app --host 127.0.0.1 --port 8000 --reload
frontend:
	cd frontend && npm run dev
dev:
	$(MAKE) -j2 backend frontend
test:
	cd backend && uv run pytest -q
	cd frontend && npm test -- --run
	cd frontend && npx eslint .
	cd frontend && npx tsc -b
