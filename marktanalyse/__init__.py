"""Marktanalyse – regelbasierte Aktienanalyse mit Long-/Short-Empfehlungen."""

from .config import Config, load_config
from .engine import Analyzer
from .models import AnalysisReport, Recommendation, Regime

__version__ = "0.1.0"
__all__ = ["Analyzer", "AnalysisReport", "Config", "Recommendation", "Regime", "load_config"]
