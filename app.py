"""FastAPI application for the FX conversion tool."""

import os

from fastapi import FastAPI


DEFAULT_FX_UPSTREAM_BASE = "https://api.frankfurter.dev"
FX_UPSTREAM_BASE = os.getenv("FX_UPSTREAM_BASE", DEFAULT_FX_UPSTREAM_BASE).rstrip("/")

app = FastAPI(title="FX conversion tool")
