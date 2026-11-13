"""openapi.json in the repository is the contract; it must match what the code serves.

Regenerate after a change of the routes or the envelopes:
    SERVICE_KEY=x python -m app.openapi > openapi.json
"""
import json
from pathlib import Path

from app.main import api


def test_checked_in_openapi_matches_the_code():
    served = json.loads(json.dumps(api.openapi(), sort_keys=True))
    stored = json.loads(Path(__file__).resolve().parent.parent.joinpath("openapi.json").read_text())
    assert served == stored, "openapi.json is stale: regenerate it (see this file's docstring)"
