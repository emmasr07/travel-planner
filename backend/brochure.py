# The brochure, built from the kept experiences, with no AI. Session 1: the sublist (visiting order).
# Session 3 adds the PDF.
from backend.budget import counts
from backend.checks import minutes


def sublist(trip):
    """Kept, non-rejected experiences by day, then local start time, numbered as stops on the map."""
    kept = sorted((e for e in trip["experiences"] if counts(e)),
                  key=lambda e: (e["schedule"]["day"], minutes(e["schedule"]["start"])))
    return [{"id": e["id"], "day": e["schedule"]["day"], "start": e["schedule"]["start"], "end": e["schedule"]["end"],
             "stop": n} for n, e in enumerate(kept, start=1)]
