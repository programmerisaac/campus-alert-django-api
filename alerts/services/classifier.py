# campusalert/alerts/services/classifier.py

"""
Alert urgency classification service — Phase 2.

Implements the two-step classification pipeline described in PRD §3.2:

    Step 1 — Keyword Rule Override:
        Scans the alert text for predefined keywords mapped to urgency levels.
        If a keyword is found, the urgency is set immediately and XGBoost is skipped.
        This ensures Critical alerts with known keywords (fire, evacuate, bomb)
        are classified and dispatched in < 500ms with no ML overhead.

    Step 2 — XGBoost Classification:
        If no keyword override fires, the combined title+body text is vectorized
        with the trained TF-IDF vectorizer and passed to the XGBoost classifier.
        Returns the predicted urgency class and the model's confidence score.

Model loading:
    Both model.pkl and vectorizer.pkl are loaded once at first call via
    @lru_cache(maxsize=1). Subsequent calls reuse the in-memory objects.
    This means the ~50ms joblib load cost is paid only once per worker process.

Usage:
    from alerts.services.classifier import classify_alert

    urgency, method, confidence = classify_alert(
        title="EMERGENCY: Fire in Hall C",
        body="All students must evacuate immediately.",
    )
    # urgency    → "critical"
    # method     → "keyword_override"
    # confidence → None  (keyword override, no model score)
"""

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger('campusalert.classifier')

# ── Urgency keyword map (PRD §3.3) ────────────────────────────────────────────
# Evaluated in priority order: critical → high → medium → low.
# A match at any level immediately returns that level; remaining levels are skipped.
# Keywords are matched as whole-word, case-insensitive substrings.
URGENCY_KEYWORDS: dict[str, list[str]] = {
    'critical': [
        'fire', 'explosion', 'bomb', 'armed', 'shooter', 'weapon',
        'evacuate', 'evacuation', 'emergency', 'attack', 'threat',
        'lockdown', 'hostage', 'casualty', 'fatality', 'collapse',
    ],
    'high': [
        'danger', 'hazard', 'medical', 'ambulance', 'injury', 'accident',
        'power outage', 'gas leak', 'flood', 'security breach', 'police',
        'arrest', 'suspect', 'incident', 'alert', 'warning',
    ],
    'medium': [
        'disruption', 'delay', 'cancelled', 'rescheduled', 'health advisory',
        'caution', 'notice', 'advisory', 'unwell', 'closed',
    ],
    'low': [
        'reminder', 'event', 'announcement', 'update', 'information',
        'schedule', 'note', 'meeting', 'chapel', 'sports', 'activity',
    ],
}

# Integer label mapping must match the training script's label encoding exactly
LABEL_TO_URGENCY: dict[int, str] = {
    0: 'low',
    1: 'medium',
    2: 'high',
    3: 'critical',
}


# ── Model loading ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_model():
    """
    Loads the trained XGBoost model and TF-IDF vectorizer from disk.
    Results are cached in memory for the lifetime of the worker process.
    This is called lazily on first classification request.

    Returns:
        Tuple of (XGBClassifier, TfidfVectorizer) loaded via joblib.

    Raises:
        FileNotFoundError: If model or vectorizer pickle files are missing.
                           Run ml/train.py to generate them.
        ImportError: If xgboost or scikit-learn are not installed.
    """
    try:
        import joblib
    except ImportError as exc:
        raise ImportError('joblib is required. Run: pip install joblib') from exc

    model_path: Path = settings.ML_MODEL_PATH
    vectorizer_path: Path = settings.ML_VECTORIZER_PATH

    if not model_path.exists():
        raise FileNotFoundError(
            f'XGBoost model not found at {model_path}. '
            f'Run python ml/train.py to generate it.'
        )
    if not vectorizer_path.exists():
        raise FileNotFoundError(
            f'TF-IDF vectorizer not found at {vectorizer_path}. '
            f'Run python ml/train.py to generate it.'
        )

    model = joblib.load(model_path)
    vectorizer = joblib.load(vectorizer_path)

    logger.info('XGBoost model and TF-IDF vectorizer loaded from disk.')
    return model, vectorizer


# ── Public classification function ───────────────────────────────────────────

def classify_alert(
    title: str,
    body: str,
) -> tuple[str, str, Optional[float]]:
    """
    Classifies an alert into one of four urgency levels.

    Implements the two-step pipeline from PRD §3.2:
        1. Keyword override — instant classification for known emergency terms
        2. XGBoost model    — probabilistic classification for everything else

    Args:
        title: The alert title text.
        body:  The alert body text.

    Returns:
        A 3-tuple of:
            urgency    (str)            — "critical" | "high" | "medium" | "low"
            method     (str)            — "keyword_override" | "xgboost"
            confidence (float | None)   — XGBoost confidence (0–1), None if keyword override
    """
    combined_text = f'{title} {body}'.lower().strip()

    # ── Step 1: Keyword override ───────────────────────────────────────────────
    # Check urgency levels in descending priority (critical first).
    # A match at a higher level short-circuits all lower-level checks.
    for urgency_level, keywords in URGENCY_KEYWORDS.items():
        if _text_contains_keyword(combined_text, keywords):
            logger.debug(
                'Keyword override triggered: urgency=%s for text="%s..."',
                urgency_level,
                combined_text[:60],
            )
            return urgency_level, 'keyword_override', None

    # ── Step 2: XGBoost classification ────────────────────────────────────────
    try:
        return _run_xgboost(combined_text)
    except (FileNotFoundError, ImportError) as exc:
        # If the model is not available (not yet trained), default to 'low'
        # and log the issue. This prevents 500 errors during initial setup.
        logger.warning(
            'XGBoost model unavailable (%s). Defaulting urgency to low.', exc
        )
        return 'low', 'xgboost', None


def _text_contains_keyword(text: str, keywords: list[str]) -> bool:
    """
    Checks whether any keyword from the list appears in the text.
    Uses whole-word matching to avoid false positives like
    "firetruck" matching the keyword "fire".

    Multi-word keywords (e.g. "gas leak", "power outage") are matched
    as literal substrings since word-boundary matching doesn't apply
    cleanly across spaces.
    """
    for keyword in keywords:
        if ' ' in keyword:
            # Multi-word keyword: match as a substring
            if keyword in text:
                return True
        else:
            # Single-word keyword: whole-word match to reduce false positives
            pattern = rf'\b{re.escape(keyword)}\b'
            if re.search(pattern, text):
                return True
    return False


def _run_xgboost(text: str) -> tuple[str, str, float]:
    """
    Runs the TF-IDF → XGBoost inference pipeline.

    Args:
        text: Lowercased, combined title+body text.

    Returns:
        Tuple of (urgency, "xgboost", confidence_score).
    """
    model, vectorizer = _load_model()

    # Transform text to TF-IDF feature vector (sparse matrix, shape [1, n_features])
    features = vectorizer.transform([text])

    # Predict the label (integer class index)
    predicted_label: int = int(model.predict(features)[0])

    # Get the probability for the predicted class as the confidence score
    probabilities = model.predict_proba(features)[0]
    confidence: float = float(probabilities[predicted_label])

    urgency = LABEL_TO_URGENCY.get(predicted_label, 'low')

    logger.debug(
        'XGBoost classification: urgency=%s confidence=%.3f text="%s..."',
        urgency,
        confidence,
        text[:60],
    )

    return urgency, 'xgboost', confidence

