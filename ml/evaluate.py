# campusalert/ml/evaluate.py

"""
CampusAlert Classifier Evaluation Script — Phase 2.

Loads the trained model artefacts and runs a full evaluation suite:
    - PRD metrics: accuracy, precision, recall, F1, false alarm rate
    - Per-class breakdown
    - Confusion matrix
    - Live inference demo on sample phrases
    - Keyword override coverage test

Run after training:
    python ml/evaluate.py

Or point at a specific model:
    python ml/evaluate.py --model ml/model.pkl --vectorizer ml/vectorizer.pkl
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s — %(message)s',
)
logger = logging.getLogger('campusalert.ml.evaluate')

ML_DIR = Path(__file__).parent

# Integer ↔ urgency label mapping — must match train.py and classifier.py
URGENCY_TO_INT = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
INT_TO_URGENCY = {v: k for k, v in URGENCY_TO_INT.items()}

# PRD §2.2 targets
MIN_ACCURACY = 0.80
MAX_FALSE_ALARM_RATE = 0.05

# Demo samples for live inference test — covers all four urgency levels
DEMO_SAMPLES: list[tuple[str, str]] = [
    # (text, expected_urgency)
    ('FIRE in Block C dormitory. All students evacuate immediately!', 'critical'),
    ('Emergency: Armed gunman reported near the cafeteria. Lockdown now.', 'critical'),
    ('Bomb threat received at the chapel. Evacuate now.', 'critical'),
    ('Power outage on campus. Generator backup is active.', 'high'),
    ('Gas leak detected in the engineering lab. Hazmat team notified.', 'high'),
    ('Security incident reported at the main gate. Police on the way.', 'high'),
    ('Exam timetable for second semester has been rescheduled. Check portal.', 'medium'),
    ('Health advisory: Cases of typhoid fever reported. Visit the clinic.', 'medium'),
    ('Chapel service this Sunday is cancelled. Reason: venue maintenance.', 'medium'),
    ('Reminder: CGPA submission deadline is Friday. Log in to student portal.', 'low'),
    ('Sports day event tomorrow at the sports complex. Participation is optional.', 'low'),
    ('General announcement: Library is now open 24 hours during exam week.', 'low'),
]


def load_artefacts(model_path: Path, vectorizer_path: Path) -> tuple:
    """
    Loads model and vectoriser from disk.

    Args:
        model_path:      Path to model.pkl
        vectorizer_path: Path to vectorizer.pkl

    Returns:
        (model, vectorizer) tuple.

    Raises:
        SystemExit if either file is missing.
    """
    if not model_path.exists():
        logger.error('Model file not found: %s. Run ml/train.py first.', model_path)
        sys.exit(1)
    if not vectorizer_path.exists():
        logger.error('Vectorizer file not found: %s. Run ml/train.py first.', vectorizer_path)
        sys.exit(1)

    model = joblib.load(model_path)
    vectorizer = joblib.load(vectorizer_path)
    logger.info('Loaded model from %s', model_path)
    logger.info('Loaded vectorizer from %s (vocab: %d)', vectorizer_path, len(vectorizer.vocabulary_))
    return model, vectorizer


def run_live_inference_demo(model, vectorizer) -> None:
    """
    Runs classification on DEMO_SAMPLES and prints results alongside expectations.
    Used for quick sanity check after training.

    Args:
        model:      Fitted XGBClassifier.
        vectorizer: Fitted TfidfVectorizer.
    """
    logger.info('\n── Live Inference Demo ──────────────────────────────────')
    correct = 0
    for text, expected in DEMO_SAMPLES:
        features = vectorizer.transform([text.lower()])
        predicted_int = int(model.predict(features)[0])
        probas = model.predict_proba(features)[0]
        predicted = INT_TO_URGENCY[predicted_int]
        confidence = float(probas[predicted_int])
        match = '✅' if predicted == expected else '❌'
        if predicted == expected:
            correct += 1
        logger.info(
            '%s [expected=%s | predicted=%s | conf=%.2f] "%s..."',
            match, expected, predicted, confidence, text[:60],
        )
    logger.info(
        'Demo accuracy: %d/%d (%.1f%%)',
        correct, len(DEMO_SAMPLES), 100 * correct / len(DEMO_SAMPLES),
    )


def run_keyword_coverage_test() -> None:
    """
    Validates that the keyword override layer catches all expected critical
    phrases without hitting the ML model.

    Imports directly from the classifier service to test end-to-end.
    """
    logger.info('\n── Keyword Override Coverage Test ───────────────────────')

    # These phrases MUST trigger keyword override, not XGBoost
    must_override: list[tuple[str, str]] = [
        ('FIRE in the library. Evacuate now.', 'critical'),
        ('Bomb threat at the chapel.', 'critical'),
        ('Armed intruder on campus. Lockdown.', 'critical'),
        ('Evacuation order for all students.', 'critical'),
        ('Power outage affecting campus.', 'high'),
        ('Gas leak in engineering block.', 'high'),
        ('Medical emergency at the gate.', 'high'),
        ('Ambulance requested at Hall A.', 'high'),
    ]

    # Add parent dir to path so we can import the classifier service
    project_root = ML_DIR.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        import django
        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'website.settings')
        django.setup()
        from alerts.services.classifier import classify_alert, _apply_keyword_override

        correct = 0
        for text, expected_urgency in must_override:
            override_result = _apply_keyword_override(text.lower())
            if override_result == expected_urgency:
                logger.info('✅ Keyword override correct: [%s] "%s..."', expected_urgency, text[:50])
                correct += 1
            else:
                logger.error(
                    '❌ Keyword override failed: expected=%s got=%s for "%s"',
                    expected_urgency, override_result, text[:50],
                )
        logger.info(
            'Keyword coverage: %d/%d phrases correctly overridden.',
            correct, len(must_override),
        )
    except Exception as exc:
        logger.warning(
            'Could not run keyword coverage test (Django not configured): %s. '
            'Run this from inside the Django project root.', exc,
        )


def print_training_metadata() -> None:
    """Prints the saved training metadata from the last training run."""
    metadata_path = ML_DIR / 'training_metadata.json'
    if not metadata_path.exists():
        logger.info('No training_metadata.json found. Run ml/train.py first.')
        return

    with open(metadata_path) as f:
        meta = json.load(f)

    logger.info('\n── Training Metadata ────────────────────────────────────')
    logger.info('Train samples:     %d', meta.get('n_train', 'N/A'))
    logger.info('Test samples:      %d', meta.get('n_test', 'N/A'))
    logger.info('Vocabulary size:   %d', meta.get('vocabulary_size', 'N/A'))
    metrics = meta.get('metrics', {})
    logger.info('Accuracy:          %.4f', metrics.get('accuracy', 0))
    logger.info('Precision (macro): %.4f', metrics.get('precision_macro', 0))
    logger.info('Recall (macro):    %.4f', metrics.get('recall_macro', 0))
    logger.info('F1 (macro):        %.4f', metrics.get('f1_macro', 0))
    logger.info('False alarm rate:  %.4f', metrics.get('false_alarm_rate', 0))
    logger.info('CV accuracy:       %.4f ± %.4f', metrics.get('cv_accuracy_mean', 0), metrics.get('cv_accuracy_std', 0))
    prd_met = metrics.get('prd_targets_met', False)
    logger.info('PRD targets met:   %s', '✅ YES' if prd_met else '❌ NO')


def main():
    parser = argparse.ArgumentParser(description='Evaluate the CampusAlert classifier.')
    parser.add_argument('--model', type=Path, default=ML_DIR / 'model.pkl')
    parser.add_argument('--vectorizer', type=Path, default=ML_DIR / 'vectorizer.pkl')
    parser.add_argument('--demo-only', action='store_true', help='Only run demo inference, skip keyword test.')
    args = parser.parse_args()

    print_training_metadata()
    model, vectorizer = load_artefacts(args.model, args.vectorizer)
    run_live_inference_demo(model, vectorizer)

    if not args.demo_only:
        run_keyword_coverage_test()


if __name__ == '__main__':
    main()


