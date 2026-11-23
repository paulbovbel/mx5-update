"""Explicitly registered, pinned-source firmware mod adapters."""

import json
from importlib.resources import files

SOURCES = json.loads(files(__package__).joinpath("sources.json").read_text(encoding="utf-8"))
