PYTHON ?= python
IMAGE ?= geospatial-measurement-api

.PHONY: install run test lint typecheck check format migration sample-data accuracy up down docker-build docker-run

install:
	$(PYTHON) -m pip install -r requirements-dev.txt
	pre-commit install

run:
	$(PYTHON) -m uvicorn app.main:create_app --factory --reload

test:
	$(PYTHON) -m pytest -q --cov --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

check: lint typecheck test

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

migration:
	$(PYTHON) -m alembic revision --autogenerate -m "$(m)"

sample-data:
	$(PYTHON) -m scripts.make_sample_data

accuracy:
	$(PYTHON) -m scripts.accuracy_report

up:
	docker compose up --build

down:
	docker compose down

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p 8000:8000 -v geoapi-data:/data $(IMAGE)
