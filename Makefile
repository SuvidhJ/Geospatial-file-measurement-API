PYTHON ?= python
IMAGE ?= geospatial-measurement-api

.PHONY: install run test lint format sample-data docker-build docker-run

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) -m uvicorn app.main:create_app --factory --reload

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

sample-data:
	$(PYTHON) -m scripts.make_sample_data

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -p 8000:8000 -v geoapi-data:/data $(IMAGE)
