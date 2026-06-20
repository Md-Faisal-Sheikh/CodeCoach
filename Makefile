# CodeCoach — common tasks
PY ?= python3

.PHONY: help install seed reseed run test demo study clean

help:
	@echo "make install   - install Python dependencies"
	@echo "make seed       - seed the database if empty"
	@echo "make reseed     - wipe and reseed (fresh demo data)"
	@echo "make run        - start the web server (seeds if empty)"
	@echo "make test       - run the test suite"
	@echo "make demo       - quick capability smoke test"
	@echo "make study      - run the end-to-end mock study, write CSV reports"
	@echo "make clean      - remove the database, reports, and caches"

install:
	$(PY) -m pip install -r requirements.txt --break-system-packages

seed:
	$(PY) -m app.seed

reseed:
	$(PY) -m app.seed --force

run:
	./run.sh

test:
	$(PY) -m pytest

demo:
	$(PY) scripts/demo.py

study:
	$(PY) scripts/run_study.py

clean:
	rm -f data/codecoach.db
	rm -rf data/reports
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
