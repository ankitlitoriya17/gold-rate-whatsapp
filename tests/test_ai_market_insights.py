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
NOW = datetime(2026, 11, 19, 22, 0, tzinfo=IST)
GOLD = {
    'published': date(2026, 11, 19),
    'silver_published': date(2026, 11, 19),
    'gold24': Decimal('133250'),
    'gold22': Decimal('122140'),
    'silverkg': Decimal('200900'),
    'delta24': Decimal('-2780'),
    'delta22': Decimal('-2550'),
    'delta_silver': Decimal('-5000'),
}
MARKETS = {
    'nifty': {'value': Decimal('25514.30'), 'change_pct': Decimal('1.47')},
    'sensex': {'value': Decimal('83021.75'), 'change_pct': Decimal('1.75')},
    'usdinr': {'value': Decimal('93.28'), 'change_pct': Decimal('-0.80')},
    'brent': {'value': Decimal('90.35'), 'change_pct': Decimal('-2.26')},
}
FACTS = market_observations(GOLD, MARKETS, NOW.date())
SAFE = {
    'summary': 'Equities mein aaj strong buying dikhi, Nifty 50 +1.47% aur Sensex +1.75% upar band hue, '
               'saath hi rupee mazboot hua.',
    'gold': 'Datia 24K gold Rs 1,33,250 par Rs 2,780 neeche aaya; rupee mazboot aur crude -2.26% '
            'hone par aksar gold par dabaav dikhta hai.',
    'watch': 'Kal USD/INR aur Brent crude ki direction dekhein, rupee ka trend gold ke rate par asar daal sakta hai.',
}


def reply(content):
    return {'choices': [{'message': {'content': json.dumps(content)}}]}


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

    def test_observations_carry_verified_numbers(self):
        joined = '\n'.join(FACTS)
        self.assertIn('Rs 1,33,250', joined)
        self.assertIn('down Rs 2,780 (-2.04%)', joined)
        self.assertIn('Nifty 50: 25,514.30, +1.47%', joined)
        self.assertIn('USD/INR: 93.28', joined)
        self.assertIn('rupee MAZBOOT', joined)
        self.assertIn('crude sasta', joined)

    def test_stale_metal_is_labelled_without_change(self):
        old = dict(GOLD, published=date(2026, 11, 18))
        facts = market_observations(old, MARKETS, NOW.date())
        self.assertTrue(any('24K gold' in f and 'stale' in f for f in facts))
        self.assertFalse(any('2,780' in f for f in facts))

    def test_valid_response_uses_big_model_first(self):
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen', return_value=DummyResponse(reply(SAFE))) as call:
                result = generate_ai_insights(GOLD, MARKETS, NOW)
        self.assertEqual(result, SAFE)
        request = call.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload['model'], 'openai/gpt-oss-120b')
        self.assertTrue(payload['response_format']['json_schema']['strict'])
        self.assertNotIn('dummy-test-token', request.data.decode())

    def test_falls_back_to_small_model(self):
        err = HTTPError('https://api.groq.com', 503, 'busy', {}, io.BytesIO(b''))
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen',
                       side_effect=[err, DummyResponse(reply(SAFE))]) as call:
                self.assertEqual(generate_ai_insights(GOLD, MARKETS, NOW), SAFE)
        models = [json.loads(c.args[0].data)['model'] for c in call.call_args_list]
        self.assertEqual(models, ['openai/gpt-oss-120b', 'openai/gpt-oss-20b'])

    def test_rejects_invented_numbers(self):
        for field, text in (
            ('summary', 'Nifty 50 ka agla level 26,000 ho sakta hai, momentum strong lag raha hai.'),
            ('gold', 'Gold Rs 1,30,000 tak aa sakta hai agar rupee aur mazboot hota hai to.'),
            ('watch', 'Kal 2.5% ki movement possible hai, isliye USD/INR par nazar rakhein.'),
        ):
            with self.subTest(field=field):
                self.assertIsNone(parse_ai_response(reply(dict(SAFE, **{field: text})), FACTS))

    def test_allows_rounded_supplied_percent(self):
        ok = dict(SAFE, summary='Nifty 50 lagbhag 1.5% aur Sensex 1.75% upar; equities mein '
                                'aaj positive mood raha.')
        self.assertEqual(parse_ai_response(reply(ok), FACTS)['summary'], ok['summary'])

    def test_reject_advice_urls_and_empty(self):
        for invalid in (
            dict(SAFE, summary='Abhi gold kharido, ye guaranteed profit wala mauka hai sabke liye.'),
            dict(SAFE, watch='Kal ke liye details https://bad.example.com par dekhein zaroor.'),
            dict(SAFE, gold=''),
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(parse_ai_response(reply(invalid), FACTS))

    def test_all_failures_fall_back_without_raise(self):
        err = HTTPError('https://api.groq.com', 429, 'too many', {}, io.BytesIO(b'quota'))
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen', side_effect=[err, err]):
                self.assertIsNone(generate_ai_insights(GOLD, MARKETS, NOW))

    def test_weak_data_skips_ai_even_with_key(self):
        weak = {k: None for k in MARKETS}
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen') as call:
                self.assertIsNone(generate_ai_insights(None, weak, NOW))
                call.assert_not_called()

    def test_format_appends_three_lines_without_altering_rates(self):
        msg = format_investor_brief(GOLD, {}, NOW, ai_insights=SAFE)
        self.assertIn('AI MARKET INSIGHTS', msg)
        for text in SAFE.values():
            self.assertIn(text, msg)
        self.assertIn('₹1,33,250', msg)
        self.assertNotIn('AI MARKET INSIGHTS', format_investor_brief(GOLD, {}, NOW))


if __name__ == '__main__':
    unittest.main()
