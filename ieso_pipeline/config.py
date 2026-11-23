"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql+psycopg2://ieso:ieso@localhost:5432/ieso"
DEFAULT_DEMAND_DIR = "https://reports-public.ieso.ca/public/Demand/"
DEFAULT_FUEL_DIR = "https://reports-public.ieso.ca/public/GenOutputbyFuelHourly/"


@dataclass(frozen=True)
class Settings:
    database_url: str
    demand_dir: str
    fuel_dir: str
    http_timeout_s: float


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        demand_dir=os.getenv("IESO_DEMAND_DIR", DEFAULT_DEMAND_DIR),
        fuel_dir=os.getenv("IESO_FUEL_DIR", DEFAULT_FUEL_DIR),
        http_timeout_s=float(os.getenv("IESO_HTTP_TIMEOUT_S", "30")),
    )
