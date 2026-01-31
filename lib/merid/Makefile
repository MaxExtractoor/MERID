# Convenience makefile for local development
.PHONY: build up run test

build:
	docker build -t merid:local .

up: build
	docker-compose up --detach

run:
	python -m uvicorn web.main:app --reload

test:
	python -m pytest -q
