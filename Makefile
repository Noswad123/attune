.DEFAULT_GOAL := install

PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
DESTDIR ?=
VENV ?= .venv
UV ?= uv
PYTHON ?= /usr/bin/python3

.PHONY: build install install-dev check-dev

build:
	UV_PROJECT_ENVIRONMENT="$(VENV)" "$(UV)" sync --locked --python "$(PYTHON)"

install: install-dev

# Copy the editable environment's entrypoint, retaining its venv interpreter.
install-dev: check-dev
	install -d "$(DESTDIR)$(BINDIR)"
	install -m 755 "$(VENV)/bin/attune" "$(DESTDIR)$(BINDIR)/attune"

check-dev:
	@test -x "$(VENV)/bin/attune" || { \
		printf '%s\n' 'Missing development launcher. Run make build first (UV=/path/to/uv if needed).' >&2; \
		exit 1; \
	}
