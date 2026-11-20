# GARDEKALINGA: common tasks. Docker targets read .env at the repository root.
COMPOSE = docker compose -f deploy/docker-compose.yml --env-file .env
PY ?= python3

.PHONY: help dev-api dev-web test firmware-test lint build up down logs migrate create-manager register-device \
        rotate-device-key train backup restore export-ca demo-model simulate

help: ## list the targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- development
dev-api: ## run the API on :5000 with the demo garden (SQLite)
	GK_DEMO_MODE=true flask --app "backend.app:create_app" run -p 5000 --debug

dev-web: ## run the dashboard on :5173 (proxies /api to :5000)
	cd frontend && npm run dev

test: ## backend tests with coverage
	$(PY) -m pytest backend/tests -q --cov=backend/services

firmware-test: ## native unit tests of the firmware logic (g++)
	g++ -std=c++17 -Wall -Wextra -Ifirmware/test/shim -o /tmp/gk_native_tests firmware/test/test_logic/test_main.cpp && /tmp/gk_native_tests

lint: ## ruff and TypeScript checks
	ruff check backend tools worker && cd frontend && npx tsc --noEmit -p .

build: ## build the dashboard
	cd frontend && npm ci && npm run build

demo-model: ## retrain the bundled demo model (needs requirements-ml.txt)
	$(PY) tools/make_demo_model.py

simulate: ## device simulator against a local API: make simulate SECRET=<hex>
	$(PY) tools/device_simulator.py --url http://localhost:5000 --secret $(SECRET)

# ---------------------------------------------------------------- docker deployment
up: ## build and start caddy, api, worker, mysql, backup
	$(COMPOSE) up -d --build

down: ## stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## follow the logs
	$(COMPOSE) logs -f --tail=200

migrate: ## apply database migrations with the migration user
	$(COMPOSE) run --rm api sh -c 'DATABASE_URL=$$MIGRATE_DATABASE_URL alembic -c backend/alembic.ini upgrade head'

create-manager: ## first manager account: make create-manager USERNAME=ana NAME="Ana Cruz"
	$(COMPOSE) run --rm api python -m backend.cli create-manager --username $${USERNAME:-manager} --name "$${NAME:-Garden manager}"

register-device: ## register Box B and print its secret once
	$(COMPOSE) run --rm api python -m backend.cli register-device --id $${ID:-gk-node-01}

rotate-device-key: ## new device secret (the old one stops working)
	$(COMPOSE) run --rm api python -m backend.cli rotate-device-key --id $${ID:-gk-node-01}

train: ## train the Random Forest now
	$(COMPOSE) run --rm worker python -m backend.cli train

backup: ## database backup now (into the backups volume)
	$(COMPOSE) exec backup sh -c 'f=/backups/gardekalinga-manual-$$(date +%Y%m%d-%H%M).sql.gz; mysqldump -h mysql -uroot -p"$$MYSQL_ROOT_PASSWORD" --single-transaction gardekalinga | gzip > $$f && echo $$f'

restore: ## restore a backup: make restore FILE=path.sql.gz
	sh deploy/backup/restore.sh $(FILE)

export-ca: ## print Caddy's internal root CA (paste it into the ESP32 setup page)
	$(COMPOSE) exec caddy cat /data/caddy/pki/authorities/local/root.crt
