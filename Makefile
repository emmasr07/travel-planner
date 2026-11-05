# make run starts the server; make verify runs every test (later: the 20 test itineraries).
ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python
else
PY := .venv/bin/python
endif

run:
	$(PY) -m uvicorn backend.main:app --reload

verify:
	$(PY) -m pytest -q
