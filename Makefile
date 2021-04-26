ifeq ($(OS), Windows_NT)
	SYS_PYTHON ?= python.exe
	ENV_PYTHON ?= .env/Scripts/python.exe
	ENV_PIP ?= .env/Scripts/pip
else
	SYS_PYTHON ?= python3
	ENV_PYTHON ?= .env/bin/python
	ENV_PIP ?= .env/bin/pip
endif

all: Makefile
	@sed -n 's/^.PHONY:/ /p' $<

.PHONY: init
init:
	$(SYS_PYTHON) -m venv .env --clear

.PHONY: install-production
install-production: \
	init
	$(ENV_PIP) install --no-cache-dir -r requirements.txt

.PHONY: install-development
install-development: \
	init
	$(ENV_PIP) install --no-cache-dir -r requirements.txt black flake8 mypy

.PHONY: clean
clean:
	test -d ".git" && git clean -X -d --force --exclude="!.env" --exclude="!audio-streams-recorder.yaml" || rm -rf .env

.PHONY: run
run:
	$(ENV_PYTHON) -Bu audio-streams-recorder.py daemon
