import io
import json
import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from ai_market_insights import generate_ai_insights, market_observations, parse_ai_response
from market_brief import format_investor_brief

IST = ZoneInfo('Asia/Kolkata')
NOW = datetime(2026, 11, 12, 22, 0, tzinfo=IST)
GOLD = {
    'published': date(2026, 11, 11),
    'silver_published': date(2026, 11, 10),
    'gold24': Decimal('142680'),
    'gold22': Decimal('130790'),
    'silverkg': Decimal('220900'),
    'delta24': Decimal('-400'),
    'delta22': Decimal('-380'),
    'delta_silver': Decimal('0'),
}
MARKETS = {
    'nifty': {'change_pct': Decimal('1.20')},
    'sensex': {'change_pct': Decimal('1.10')},
    'usdinr': {'change_pct': Decimal('-0.40')},
    'brent': {'change_pct': Decimal('0.70')},
}
SAFE = {'summary': 'Indian indices mein positivity hai aur rupee dollar ke comparison mein stronger dikh raha hai.',
        'watch': 'Crude futures ki movement aur currency direction par nazar rakhein, picture badal sakti hai.'}


class DummyResponse:
    status = 200

    def __init__(self, result):
        self.contents = json.dumps(result).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.contents[:limit]


class GroqInsightTests(unittest.TestCase):
    def test_no_key_no_request(self):
        with patch.dict(os.environ, {}, clear=True), patch('ai_market_insights.urlopen') as url:
            self.assertIsNone(generate_ai_insights(GOLD, MARKETS, NOW))
            url.assert_not_called()

    def test_model_receives_only_market_observations(self):
        facts = market_observations(GOLD, MARKETS, NOW.date())
        self.assertTrue(any('gold quote is stale' in x for x in facts))
        self.assertTrue(any('Nifty 50' in x for x in facts))
        serialized = json.dumps(facts)
        self.assertNotIn('142680', serialized)
        self.assertNotIn('220900', serialized)
        self.assertNotIn('919876', serialized)

    def test_valid_response_returns_two_safe_lines(self):
        reply = {'choices': [{'message': {'content': json.dumps(SAFE)}}]}
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen', return_value=DummyResponse(reply)) as call:
                result = generate_ai_insights(GOLD, MARKETS, NOW)
        self.assertEqual(result, SAFE)
        request = call.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.groq.com/openai/v1/chat/completions')
        payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'openai/gpt-oss-20b')
        self.assertTrue(payload['response_format']['json_schema']['strict'])
        self.assertEqual(payload['max_completion_tokens'], 240)
        self.assertNotIn('dummy-test-token', request.data.decode())
        self.assertNotIn('142680', request.data.decode())

    def test_allows_known_market_identifiers_without_opening_price_hallucinations(self):
        valid = {
            'summary': 'Nifty 50 aaj higher tha, jabki USD/INR lower raha; market trends mixed ho sakte hain.',
            'watch': 'Agle updates mein USD/INR aur Nifty 50 ki direction verify karte rahen.'
        }
        self.assertEqual(parse_ai_response({
            'choices': [{'message': {'content': json.dumps(valid)}}]
        }), valid)
        invalid = dict(valid, summary='Nifty 50 ka target 26000 hoga')
        self.assertIsNone(parse_ai_response({
            'choices': [{'message': {'content': json.dumps(invalid)}}]
        }))

    def test_reject_price_or_direct_buy_advice(self):
        for invalid in (
            dict(SAFE, summary='Buy now, this is a guaranteed profit!'),
            dict(SAFE, watch='Target ₹90,000 aaj guaranteed'),
            dict(SAFE, summary=''),
            dict(SAFE, watch='https://bad.example.com external facts'),
        ):
            with self.subTest(invalid=invalid):
                reply = {'choices': [{'message': {'content': json.dumps(invalid)}}]}
                self.assertIsNone(parse_ai_response(reply))

    def test_rate_limit_falls_back_without_raise(self):
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen', side_effect=HTTPError(
                    'https://api.groq.com/openai/v1/chat/completions',
                    429, 'too many requests', {}, io.BytesIO(b'quota exceeded'))):
                self.assertIsNone(generate_ai_insights(GOLD, MARKETS, NOW))

    def test_weak_market_data_skips_ai_even_with_key(self):
        weak = {k: None for k in MARKETS}
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen') as call:
                self.assertIsNone(generate_ai_insights(None, weak, NOW))
                call.assert_not_called()

    def test_format_appends_commentary_without_altering_rate_blocks(self):
        msg = format_investor_brief(GOLD, {}, NOW, ai_insights=SAFE)
        self.assertIn('AI MARKET INSIGHTS', msg)
        self.assertIn(SAFE['summary'], msg)
        self.assertIn(SAFE['watch'], msg)
        self.assertIn('₹1,42,680', msg)
        self.assertIn('Gold 11 Nov · Silver 10 Nov', msg)
        original = format_investor_brief(GOLD, {}, NOW)
        self.assertNotIn('AI MARKET INSIGHTS', original)


if __name__ == '__main__':
    unittest.main()
