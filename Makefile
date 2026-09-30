# =============================================================================
# Assistant Bot — Makefile (cross-platform convenience targets)
# =============================================================================
# Usage:  make start | make stop | make test | make logs | make status
# =============================================================================
.PHONY: start stop logs status test rebuild ingest tls health

start:
	podman compose up -d

stop:
	podman compose down

rebuild:
	podman compose up -d --build

logs:
	podman compose logs -f

status:
	podman compose ps

test:
	podman compose exec -T backend sh -c "cd /app && python -m pytest tests/ -v"
	cd frontend && npm test -- --run

test-backend:
	podman compose exec -T backend sh -c "cd /app && python -m pytest tests/ -v"

test-frontend:
	cd frontend && npm test -- --run

ingest:
	curl -s -X POST http://localhost:8000/api/ingest/local \
		-H "Content-Type: application/json" \
		-d '{"full_refresh": true}' | python3 -m json.tool

health:
	curl -s http://localhost:8000/api/health | python3 -m json.tool

tls:
	./run.sh --tls

certs:
	./generate-certs.sh
