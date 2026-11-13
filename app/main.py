"""payment-test: a stand-in payment provider behind the payment-service contract."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app import config

settings = config.load()

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

app = FastAPI(title="payment-test", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
