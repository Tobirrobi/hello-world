"""Nachrichten-Sentiment: Lexikon-Verfahren (DE/EN) und optional Claude.

Jede Schlagzeile bekommt einen Wert zwischen -1 (sehr negativ) und +1 (sehr
positiv). Die Einzelwerte werden mit exponentiellem Zeitverfall (Halbwertszeit)
zu einem Nachrichten-Score verdichtet. Zusätzlich wird die Nachrichtenmenge
gemessen: Ungewöhnlich viele Meldungen verstärken das Signal.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Protocol, Sequence

from .models import NewsItem

log = logging.getLogger(__name__)

# Gewichtete Begriffe/Phrasen. Mehrwortphrasen haben Vorrang vor Einzelwörtern.
POSITIVE_TERMS: dict[str, float] = {
    # Englisch
    "beats estimates": 1.0, "beat estimates": 1.0, "tops estimates": 1.0, "beats expectations": 1.0,
    "raises guidance": 1.2, "raised guidance": 1.2, "raises outlook": 1.1, "boosts forecast": 1.1,
    "record revenue": 1.0, "record profit": 1.0, "record high": 0.6, "all-time high": 0.6,
    "upgrade": 0.9, "upgraded": 0.9, "outperform": 0.7, "overweight": 0.6, "buy rating": 0.8,
    "price target raised": 0.8, "raises price target": 0.8, "buyback": 0.7, "share repurchase": 0.7,
    "dividend increase": 0.8, "raises dividend": 0.8, "strong demand": 0.7, "surge": 0.6, "surges": 0.6,
    "soar": 0.7, "soars": 0.7, "rally": 0.4, "rallies": 0.4, "jumps": 0.5, "gains": 0.3,
    "approval": 0.7, "approved": 0.6, "partnership": 0.5, "contract win": 0.7, "wins contract": 0.7,
    "acquisition": 0.2, "expands": 0.3, "growth": 0.3, "profit": 0.2, "beat": 0.6, "strong": 0.3,
    "breakthrough": 0.7, "insider buying": 0.8, "narrower loss": 0.5, "returns to profit": 0.9,
    # Deutsch
    "übertrifft erwartungen": 1.0, "übertrifft prognosen": 1.0, "über den erwartungen": 0.9,
    "prognose angehoben": 1.2, "hebt prognose an": 1.2, "erhöht prognose": 1.2, "ausblick angehoben": 1.1,
    "rekordumsatz": 1.0, "rekordgewinn": 1.0, "rekordhoch": 0.6, "allzeithoch": 0.6,
    "hochgestuft": 0.9, "kaufempfehlung": 0.8, "kursziel angehoben": 0.8, "hebt kursziel": 0.8,
    "aktienrückkauf": 0.7, "dividendenerhöhung": 0.8, "erhöht dividende": 0.8, "starke nachfrage": 0.7,
    "gewinnsprung": 1.0, "kurssprung": 0.6, "steigt": 0.3, "legt zu": 0.4, "zulassung": 0.7,
    "genehmigt": 0.6, "partnerschaft": 0.5, "großauftrag": 0.8, "auftrag": 0.4, "wachstum": 0.3,
    "durchbruch": 0.7, "insiderkäufe": 0.8, "übernahmeangebot": 0.8,
}

NEGATIVE_TERMS: dict[str, float] = {
    # Englisch
    "misses estimates": 1.0, "missed estimates": 1.0, "below expectations": 0.9, "misses expectations": 1.0,
    "cuts guidance": 1.2, "lowers guidance": 1.2, "lowered guidance": 1.2, "cuts outlook": 1.1,
    "profit warning": 1.3, "downgrade": 0.9, "downgraded": 0.9, "underperform": 0.7, "underweight": 0.6,
    "sell rating": 0.8, "price target cut": 0.8, "cuts price target": 0.8, "lawsuit": 0.7, "sued": 0.7,
    "investigation": 0.8, "probe": 0.7, "sec charges": 1.1, "fraud": 1.3, "accounting irregularities": 1.3,
    "recall": 0.8, "layoffs": 0.6, "job cuts": 0.6, "bankruptcy": 1.5, "chapter 11": 1.5, "default": 1.0,
    "going concern": 1.4, "dividend cut": 1.0, "suspends dividend": 1.1, "plunge": 0.8, "plunges": 0.8,
    "tumble": 0.7, "tumbles": 0.7, "slump": 0.7, "crash": 0.9, "falls": 0.3, "drops": 0.4, "decline": 0.4,
    "weak demand": 0.7, "loss": 0.4, "losses": 0.5, "dilution": 0.7, "share offering": 0.6,
    "short seller": 0.8, "short report": 0.9, "delisting": 1.2, "halted": 0.6, "insider selling": 0.6,
    "miss": 0.6, "weak": 0.3, "warning": 0.6, "slowing growth": 0.6, "growth slows": 0.6,
    # Deutsch
    "verfehlt erwartungen": 1.0, "unter den erwartungen": 0.9, "verfehlt prognose": 1.0,
    "prognose gesenkt": 1.2, "senkt prognose": 1.2, "kappt prognose": 1.2, "ausblick gesenkt": 1.1,
    "gewinnwarnung": 1.3, "umsatzwarnung": 1.2, "herabgestuft": 0.9, "abgestuft": 0.8,
    "verkaufsempfehlung": 0.8, "kursziel gesenkt": 0.8, "senkt kursziel": 0.8, "klage": 0.7,
    "ermittlungen": 0.8, "razzia": 1.0, "betrug": 1.3, "bilanzskandal": 1.4, "rückruf": 0.8,
    "stellenabbau": 0.6, "insolvenz": 1.5, "insolvenzantrag": 1.6, "zahlungsunfähig": 1.5,
    "dividendenkürzung": 1.0, "streicht dividende": 1.1, "kurssturz": 0.9, "bricht ein": 0.8,
    "sackt ab": 0.7, "fällt": 0.3, "verliert": 0.4, "schwache nachfrage": 0.7, "verlust": 0.5,
    "kapitalerhöhung": 0.5, "leerverkäufer": 0.8, "warnung": 0.6, "wachstum verlangsamt": 0.6,
    "wachstum schwächt sich ab": 0.6,
}

NEGATIONS = {"not", "no", "never", "without", "nicht", "kein", "keine", "keinen", "ohne", "nie"}
_TOKEN = re.compile(r"[\wäöüß\-]+", re.UNICODE)


class SentimentScorer(Protocol):
    name: str

    def score(self, items: Sequence[NewsItem]) -> list[float]: ...


class LexiconSentimentScorer:
    """Schnelles, transparentes Wörterbuch-Verfahren mit Negationserkennung."""

    name = "Lexikon (DE/EN)"

    def __init__(self, positive: Optional[dict] = None, negative: Optional[dict] = None):
        self.terms = [(k, v) for k, v in (positive or POSITIVE_TERMS).items()]
        self.terms += [(k, -v) for k, v in (negative or NEGATIVE_TERMS).items()]
        # längere Phrasen zuerst, damit "raises guidance" vor "guidance" greift
        self.terms.sort(key=lambda kv: len(kv[0]), reverse=True)

    def score_text(self, text: str) -> float:
        text = " " + text.lower() + " "
        total, hits = 0.0, 0
        consumed = [False] * len(text)
        for term, weight in self.terms:
            for m in re.finditer(r"(?<![\wäöüß])" + re.escape(term) + r"(?![\wäöüß])", text):
                if any(consumed[m.start():m.end()]):
                    continue
                for i in range(m.start(), m.end()):
                    consumed[i] = True
                before = _TOKEN.findall(text[max(0, m.start() - 25):m.start()])[-3:]
                sign = -1.0 if any(t in NEGATIONS for t in before) else 1.0
                total += sign * weight
                hits += 1
        if hits == 0:
            return 0.0
        return float(math.tanh(total / 1.5))

    def score(self, items: Sequence[NewsItem]) -> list[float]:
        return [self.score_text(f"{it.headline}. {it.summary}") for it in items]


class ClaudeSentimentScorer:
    """Bewertet Schlagzeilen mit Claude (benötigt ``pip install anthropic`` und API-Zugang).

    Fällt bei Fehlern automatisch auf das Lexikon-Verfahren zurück.
    """

    name = "Claude"
    MODEL = "claude-opus-5-5"

    def __init__(self, model: Optional[str] = None, fallback: Optional[SentimentScorer] = None):
        import anthropic  # noqa: F401  (früh scheitern, wenn nicht installiert)

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or self.MODEL
        self.fallback = fallback or LexiconSentimentScorer()

    def score(self, items: Sequence[NewsItem]) -> list[float]:
        if not items:
            return []
        lines = "\n".join(
            f"{i}: {it.headline}" + (f" — {it.summary[:300]}" if it.summary else "") for i, it in enumerate(items)
        )
        prompt = (
            "Du bewertest Finanznachrichten zu einer einzelnen Aktie. Gib für jede nummerierte Meldung "
            "einen Score von -1.0 (klar kursbelastend für die Aktie) bis +1.0 (klar kurstreibend) an; "
            "0 für neutral oder irrelevant. Berücksichtige, ob eine Meldung bereits Erwartungen "
            "übertrifft/verfehlt, Prognoseänderungen, Analystenurteile, Rechtsrisiken und Finanzierung.\n\n"
            + lines
        )
        schema = {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"index": {"type": "integer"}, "score": {"type": "number"}},
                        "required": ["index", "score"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["scores"],
            "additionalProperties": False,
        }
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}],
            )
            if response.stop_reason in ("refusal", "max_tokens"):
                raise RuntimeError(f"Antwort unbrauchbar (stop_reason={response.stop_reason})")
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
            result = [0.0] * len(items)
            for entry in data.get("scores", []):
                idx = int(entry["index"])
                if 0 <= idx < len(items):
                    result[idx] = max(-1.0, min(1.0, float(entry["score"])))
            return result
        except Exception as exc:  # Netzwerk, Limits, Parsing ... -> Lexikon
            log.warning("Claude-Sentiment fehlgeschlagen (%s), nutze Lexikon.", exc)
            return self.fallback.score(items)


@dataclass
class NewsSentiment:
    score: Optional[float]  # zeitgewichteter Mittelwert, -1..1
    count: int
    recent_count: int  # Meldungen der letzten 3 Tage
    attention: Optional[float]  # Verhältnis aktuelle zu durchschnittlicher Meldungsfrequenz
    scorer: str = ""
    top_positive: list[tuple[str, float]] = field(default_factory=list)
    top_negative: list[tuple[str, float]] = field(default_factory=list)


def aggregate_news(
    items: Sequence[NewsItem],
    as_of: datetime,
    scorer: SentimentScorer,
    lookback_days: int = 14,
    half_life_days: float = 3.0,
) -> NewsSentiment:
    window = [it for it in items if as_of - timedelta(days=lookback_days) <= it.published <= as_of]
    if not window:
        return NewsSentiment(score=None, count=0, recent_count=0, attention=None, scorer=scorer.name)
    scores = scorer.score(window)
    num = den = 0.0
    for it, s in zip(window, scores):
        age = (as_of - it.published).total_seconds() / 86400
        w = 0.5 ** (age / half_life_days)
        num += w * s
        den += w
    recent = sum(1 for it in window if (as_of - it.published).days < 3)
    avg_per_3d = len(window) / lookback_days * 3
    attention = recent / avg_per_3d if avg_per_3d > 0 else None
    ranked = sorted(zip(window, scores), key=lambda x: x[1])
    return NewsSentiment(
        score=num / den if den else None,
        count=len(window),
        recent_count=recent,
        attention=attention,
        scorer=scorer.name,
        top_positive=[(it.headline, s) for it, s in reversed(ranked) if s > 0.1][:3],
        top_negative=[(it.headline, s) for it, s in ranked if s < -0.1][:3],
    )
