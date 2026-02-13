# Define targets
.PHONY: install test coverage-badge

# Define variables
PYTHON := .venv/bin/python
PIP := .venv/bin/pip
UV := uv

# Default target
default: install test

# Target to install package (dev)
install:
	$(UV) pip install -e ".[cli]"

# Target to install in termux (no venv)
install-in-termux:
	pip install moviebox-api --no-deps
	pip install 'pydantic==2.9.2'
	pip install rich click bs4 httpx throttlebuster

# Target to run tests
test:
	$(PYTHON) -m coverage run -m pytest -v

# Target to generate coverage-badge
coverage-badge:
	coverage-badge -o assets/coverage.svg -f

# Target to run Stremio addon server
run-stremio:
	$(PYTHON) -m moviebox_api.stremio

# target to build dist
build:
	rm build/ dist/ -rf
	$(UV) build

# Target to publish dist to pypi
publish:
	$(UV) publish --token $(shell cat pypi_token.txt)


