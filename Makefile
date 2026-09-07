COMPOSE := docker compose
WEB := $(COMPOSE) exec web
PYTHON := $(WEB) python
MANAGE := $(PYTHON) manage.py

.PHONY: help build config up down restart logs ps shell migrations migrate test test-v coverage check seed superuser clean reset bootstrap

help:
	@echo "FinCore commands"
	@echo ""
	@echo "  make build        Build Docker images"
	@echo "  make config       Validate the Compose configuration"
	@echo "  make up           Start application"
	@echo "  make down         Stop application"
	@echo "  make restart      Restart application"
	@echo "  make logs         Follow application logs"
	@echo "  make ps           Show running services"
	@echo "  make shell        Open Django shell"
	@echo "  make migrations   Create migrations"
	@echo "  make migrate      Apply migrations"
	@echo "  make test         Run tests"
	@echo "  make test-v       Run verbose tests"
	@echo "  make coverage     Run tests with terminal coverage report"
	@echo "  make check        Run Django checks"
	@echo "  make seed         Create deterministic development demo data"
	@echo "  make superuser    Create admin user"
	@echo "  make reset        Rebuild containers"
	@echo "  make clean        Remove Python cache files"
	@echo "  make bootstrap    Build, start, migrate, seed, and check application"

build:
	$(COMPOSE) build

config:
	$(COMPOSE) config --quiet

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f web

ps:
	$(COMPOSE) ps

shell:
	$(MANAGE) shell

migrations:
	$(MANAGE) makemigrations

migrate:
	$(MANAGE) migrate

test:
	$(PYTHON) -m pytest

test-v:
	$(PYTHON) -m pytest -vv

coverage:
	$(PYTHON) -m pytest --cov --cov-report=term-missing

check:
	$(MANAGE) check

seed:
	$(MANAGE) seed_demo

superuser:
	$(MANAGE) createsuperuser

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

reset:
	$(COMPOSE) down
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

bootstrap:
	$(COMPOSE) config --quiet
	$(COMPOSE) build
	$(COMPOSE) up -d
	$(MANAGE) migrate
	$(MANAGE) seed_demo
	$(MANAGE) check
