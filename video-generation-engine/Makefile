# Video Generation Engine - developer commands.
#
# Requires GNU Make. On Windows without `make` on PATH (e.g. plain Git
# Bash), run the recipe body directly instead - each target is a single
# command, copy-pasteable from this file.

VENV      := .venv
PY        := $(VENV)/Scripts/python.exe
BACKEND   := backend

.PHONY: venv install run test lint format typecheck check docker-up docker-down clean

venv:
	python -m venv $(VENV)

install: venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r $(BACKEND)/requirements-dev.txt

# No --reload: on Windows, uvicorn's --reload unconditionally switches to
# WindowsSelectorEventLoopPolicy (uvicorn/loops/asyncio.py), and that loop
# cannot spawn subprocesses at all - every FFmpeg call in the renderer
# raises a bare NotImplementedError (stringifies to "", so it shows up as
# a silent, message-less step failure) the moment a render is attempted.
# Restart manually after code changes instead. Matches the production
# Dockerfile, which never uses --reload either.
run:
	$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir $(BACKEND)

test:
	PYTEST_TRUNCATE_DB=1 $(PY) -m pytest --rootdir=$(BACKEND) -c $(BACKEND)/pytest.ini

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m black backend
	$(PY) -m ruff check --fix .

typecheck:
	$(PY) -m mypy $(BACKEND)/app

check: lint typecheck test

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf $(BACKEND)/storage/*
