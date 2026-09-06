from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    root: Path
    start: str = "2022-01-01"
    end: str = "2026-09-01"
    timezone: str = "Europe/Helsinki"

    fingrid_api_base: str = field(
        default_factory=lambda: os.getenv(
            "FINGRID_API_BASE",
            "https://data.fingrid.fi/api"
        )
    )

    entsoe_api_base: str = field(
        default_factory=lambda: os.getenv(
            "ENTSOE_API_BASE",
            "https://web-api.tp.entsoe.eu/api"
        )
    )

    fingrid_api_key: str = field(
        default_factory=lambda: os.getenv("FINGRID_API_KEY", "")
    )

    entsoe_token: str = field(
        default_factory=lambda:
            os.getenv("ENTSOE_API_TOKEN")
            or os.getenv("ENTSOE_TOKEN", "")
    )

    @property
    def raw_dir(self):
        return self.root / "data" / "raw"

    @property
    def processed_dir(self):
        return self.root / "data" / "processed"

    @property
    def reports_dir(self):
        return self.root / "data" / "reports"


FINGRID_DATASETS = {
    "consumption_actual_mw": 124,
    "production_actual_mw": 74,
    "consumption_forecast_day_ahead_mw": 165,
    "production_forecast_day_ahead_mw": 242,
    "wind_actual_mw": 75,
    "wind_forecast_day_ahead_mw": 246,
    "wind_capacity_mw": 268,
    "capacity_se1_to_fi_mw": 24,
    "capacity_fi_to_se1_mw": 26,
    "capacity_fi_to_ee_mw": 115,
}

FINLAND_ENTSOE_DOMAIN = "10YFI-1--------U"