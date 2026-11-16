from .base import CachedProvider, DataProvider, normalize_prices
from .csv_store import CsvProvider, archive
from .synthetic import BENCHMARK as DEMO_BENCHMARK
from .synthetic import SyntheticProvider


def make_provider(kind: str, data_dir: str | None = None) -> DataProvider:
    kind = kind.lower()
    if kind in ("demo", "synthetic"):
        return SyntheticProvider()
    if kind in ("yahoo", "yf", "yfinance"):
        from .yahoo import YahooProvider

        return YahooProvider()
    if kind == "csv":
        if not data_dir:
            raise ValueError("Für --provider csv bitte --data-dir angeben.")
        return CsvProvider(data_dir)
    raise ValueError(f"Unbekannte Datenquelle: {kind} (demo | yahoo | csv)")


__all__ = [
    "CachedProvider",
    "CsvProvider",
    "DataProvider",
    "DEMO_BENCHMARK",
    "SyntheticProvider",
    "archive",
    "make_provider",
    "normalize_prices",
]
