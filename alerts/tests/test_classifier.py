# campusalert/alerts/tests/test_classifier.py

"""
Unit tests for the alert classification service — Phase 2.

Tests cover:
- Keyword override fires for all defined critical/high keywords
- XGBoost fallback path (mocked to avoid requiring model files)
- False positive rate: low/medium alerts must not be misclassified as critical/high
- Edge cases: empty text, mixed case, multi-word keywords
- Return type shape: (urgency, method, confidence)

Run with:
    python manage.py test alerts.tests.test_classifier
    # or with pytest:
    pytest alerts/tests/test_classifier.py -v
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from alerts.services.classifier import (
    URGENCY_KEYWORDS,
    _text_contains_keyword,
    classify_alert,
)


class KeywordMatchingTests(TestCase):
    """Tests for the _text_contains_keyword helper."""

    def test_single_word_keyword_matched_as_whole_word(self):
        """'fire' should match 'fire' but not 'firetruck'."""
        self.assertTrue(_text_contains_keyword('fire in building', ['fire']))
        self.assertFalse(_text_contains_keyword('firetruck is nearby', ['fire']))

    def test_multi_word_keyword_matched_as_substring(self):
        """Multi-word keywords like 'gas leak' are matched as substrings."""
        self.assertTrue(_text_contains_keyword('there is a gas leak in block c', ['gas leak']))
        self.assertFalse(_text_contains_keyword('the gas is leaking slowly', ['gas leak']))

    def test_case_insensitive_matching(self):
        """Keyword matching must be case-insensitive."""
        self.assertTrue(_text_contains_keyword('FIRE IN THE LAB', ['fire']))
        self.assertTrue(_text_contains_keyword('Emergency Evacuation required', ['evacuation']))

    def test_empty_text_returns_false(self):
        self.assertFalse(_text_contains_keyword('', ['fire']))

    def test_no_keywords_returns_false(self):
        self.assertFalse(_text_contains_keyword('fire in the lab', []))


class KeywordOverrideTests(TestCase):
    """Tests that keyword override fires correctly for all defined keywords."""

    def _assert_keyword_override(self, text: str, expected_urgency: str) -> None:
        """Helper: assert that a text produces the expected urgency via keyword override."""
        urgency, method, confidence = classify_alert(title=text, body='')
        self.assertEqual(urgency, expected_urgency, f'Expected {expected_urgency} for: {text!r}')
        self.assertEqual(method, 'keyword_override')
        self.assertIsNone(confidence)

    def test_critical_keywords_trigger_override(self):
        """All critical keywords must trigger immediate critical classification."""
        critical_texts = [
            'There is a fire in Hall C',
            'A bomb has been reported',
            'Evacuate the building immediately',
            'Lockdown is in effect now',
            'Armed gunman on campus',
            'Emergency: medical response needed',
            'Attack reported near the gate',
            'Threat detected in the library',
        ]
        for text in critical_texts:
            with self.subTest(text=text):
                self._assert_keyword_override(text, 'critical')

    def test_high_keywords_trigger_override(self):
        """High-urgency keywords must trigger high classification via keyword override."""
        high_texts = [
            'Danger: power outage in Block A',
            'Medical emergency at Hall D',
            'Ambulance needed at the clinic',
            'Police are on campus',
            'Gas leak detected in the lab',
        ]
        for text in high_texts:
            with self.subTest(text=text):
                self._assert_keyword_override(text, 'high')

    def test_keyword_in_body_triggers_override(self):
        """Keywords in the body (not just title) must trigger override."""
        urgency, method, confidence = classify_alert(
            title='Important Notice',
            body='Please evacuate the building immediately. Fire alarm activated.',
        )
        self.assertEqual(urgency, 'critical')
        self.assertEqual(method, 'keyword_override')

    def test_critical_takes_priority_over_high(self):
        """If both critical and high keywords appear, critical wins."""
        urgency, method, confidence = classify_alert(
            title='Emergency',
            body='fire detected, danger level high, ambulance called.',
        )
        self.assertEqual(urgency, 'critical')


class XGBoostFallbackTests(TestCase):
    """
    Tests for the XGBoost classification path.
    Model is mocked so tests run without requiring model.pkl.
    """

    def _mock_model_and_vectorizer(self, predicted_label: int, confidence: float):
        """
        Returns a tuple of (mock_model, mock_vectorizer) that simulate the
        XGBoost + TF-IDF behaviour for the given predicted_label and confidence.
        """
        mock_vectorizer = MagicMock()
        mock_vectorizer.transform.return_value = MagicMock()

        mock_model = MagicMock()
        mock_model.predict.return_value = [predicted_label]

        proba = [0.0] * 4
        proba[predicted_label] = confidence
        mock_model.predict_proba.return_value = [proba]

        return mock_model, mock_vectorizer

    @patch('alerts.services.classifier._load_model')
    def test_xgboost_low_urgency(self, mock_load):
        """Non-keyword text classified as low by mocked XGBoost."""
        mock_model, mock_vec = self._mock_model_and_vectorizer(
            predicted_label=0, confidence=0.92
        )
        mock_load.return_value = (mock_model, mock_vec)

        urgency, method, confidence = classify_alert(
            title='Reminder about chapel attendance',
            body='Please attend the midweek service tomorrow morning.',
        )
        self.assertEqual(urgency, 'low')
        self.assertEqual(method, 'xgboost')
        self.assertAlmostEqual(confidence, 0.92)

    @patch('alerts.services.classifier._load_model')
    def test_xgboost_medium_urgency(self, mock_load):
        """Non-keyword text classified as medium by mocked XGBoost."""
        mock_model, mock_vec = self._mock_model_and_vectorizer(
            predicted_label=1, confidence=0.78
        )
        mock_load.return_value = (mock_model, mock_vec)

        urgency, method, confidence = classify_alert(
            title='Notice: Lecture cancelled',
            body='The afternoon lecture has been rescheduled due to a scheduling conflict.',
        )
        self.assertEqual(urgency, 'medium')
        self.assertEqual(method, 'xgboost')

    @patch('alerts.services.classifier._load_model')
    def test_model_unavailable_defaults_to_low(self, mock_load):
        """If model.pkl is missing, classification defaults to low (never crashes)."""
        mock_load.side_effect = FileNotFoundError('model.pkl not found')

        urgency, method, confidence = classify_alert(
            title='General update about the cafeteria',
            body='The cafeteria will open late tomorrow.',
        )
        # Must not raise — must return a safe default
        self.assertEqual(urgency, 'low')
        self.assertEqual(method, 'xgboost')
        self.assertIsNone(confidence)


class FalseAlarmRateTests(TestCase):
    """
    Tests that routine alerts are not misclassified as critical/high.
    These verify the keyword override does NOT fire on benign text.
    PRD target: false alarm rate < 5%.
    """

    LOW_URGENCY_TEXTS = [
        ('Chapel reminder', 'Midweek service is at 6:30am tomorrow.'),
        ('Cafeteria update', 'The cafeteria will serve jollof rice for lunch today.'),
        ('Library notice', 'New library hours are effective from next week.'),
        ('Sports event', 'Inter-hall football semi-finals are this Saturday.'),
        ('Hall dues', 'Hall dues payment deadline is the 30th of this month.'),
        ('Graduation', 'Graduating students must collect their gowns from the bookshop.'),
        ('Information', 'The university bus schedule has been updated for this semester.'),
    ]

    @patch('alerts.services.classifier._load_model')
    def test_routine_alerts_do_not_trigger_keyword_override(self, mock_load):
        """Routine low-urgency alerts must not fire keyword override."""
        mock_model, mock_vec = MagicMock(), MagicMock()
        mock_model.predict.return_value = [0]  # low
        mock_model.predict_proba.return_value = [[0.9, 0.05, 0.03, 0.02]]
        mock_vec.transform.return_value = MagicMock()
        mock_load.return_value = (mock_model, mock_vec)

        for title, body in self.LOW_URGENCY_TEXTS:
            with self.subTest(title=title):
                urgency, method, _ = classify_alert(title=title, body=body)
                self.assertNotEqual(
                    method, 'keyword_override',
                    f'Keyword override incorrectly fired for routine alert: {title!r}',
                )


class ClassifyAlertReturnTypeTests(TestCase):
    """Tests that classify_alert always returns the correct 3-tuple shape."""

    @patch('alerts.services.classifier._load_model')
    def test_return_is_three_tuple(self, mock_load):
        """classify_alert must always return a (str, str, float|None) tuple."""
        mock_model, mock_vec = MagicMock(), MagicMock()
        mock_model.predict.return_value = [0]
        mock_model.predict_proba.return_value = [[0.9, 0.05, 0.03, 0.02]]
        mock_vec.transform.return_value = MagicMock()
        mock_load.return_value = (mock_model, mock_vec)

        result = classify_alert(title='Hello', body='World')
        self.assertEqual(len(result), 3)
        urgency, method, confidence = result
        self.assertIsInstance(urgency, str)
        self.assertIsInstance(method, str)
        self.assertIn(urgency, ('critical', 'high', 'medium', 'low'))
        self.assertIn(method, ('keyword_override', 'xgboost'))

    def test_keyword_override_confidence_is_none(self):
        """Keyword override always returns None confidence (no model score)."""
        urgency, method, confidence = classify_alert(
            title='FIRE', body='evacuate now'
        )
        self.assertEqual(method, 'keyword_override')
        self.assertIsNone(confidence)


