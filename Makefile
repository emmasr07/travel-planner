# make run starts the server; make verify runs every test (later: the 20 test itineraries).
run:
	uvicorn backend.main:app --reload

verify:
	pytest -q
