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
    'insight': 'Datia 24K gold Rs 2,780 neeche aaya; rupee mazboot aur crude -2.26% hone par aksar '
               'gold par dabaav dikhta hai, khareedne walon ke liye rate thoda narm hua.',
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
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertNotIn('dummy-test-token', request.data.decode())

    def test_falls_back_to_small_model(self):
        err = HTTPError('https://api.groq.com', 503, 'busy', {}, io.BytesIO(b''))
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen',
                       side_effect=[err, err, DummyResponse(reply(SAFE))]) as call:
                self.assertEqual(generate_ai_insights(GOLD, MARKETS, NOW), SAFE)
        models = [json.loads(c.args[0].data)['model'] for c in call.call_args_list]
        self.assertEqual(models, ['openai/gpt-oss-120b', 'openai/gpt-oss-120b', 'openai/gpt-oss-20b'])

    def test_json_wrapped_in_code_fence_is_accepted(self):
        fenced = {'choices': [{'message': {'content': '```json\n' + json.dumps(SAFE) + '\n```'}}]}
        self.assertEqual(parse_ai_response(fenced, FACTS), SAFE)

    def test_rejects_invented_numbers(self):
        for field, text in (
            ('insight', 'Nifty 50 ka agla level 26,000 ho sakta hai, momentum strong lag raha hai.'),
            ('insight', 'Gold Rs 1,30,000 tak aa sakta hai agar rupee aur mazboot hota hai to.'),
            ('watch', 'Kal 2.5% ki movement possible hai, isliye USD/INR par nazar rakhein.'),
        ):
            with self.subTest(field=field):
                self.assertIsNone(parse_ai_response(reply(dict(SAFE, **{field: text})), FACTS))

    def test_allows_rounded_supplied_percent(self):
        ok = dict(SAFE, insight='Nifty 50 lagbhag 1.5% aur Sensex 1.75% upar; equities mein '
                                'aaj positive mood raha.')
        self.assertEqual(parse_ai_response(reply(ok), FACTS)['insight'], ok['insight'])

    def test_reject_advice_urls_and_empty(self):
        for invalid in (
            dict(SAFE, insight='Abhi gold kharido, ye guaranteed profit wala mauka hai sabke liye.'),
            dict(SAFE, watch='Kal ke liye details https://bad.example.com par dekhein zaroor.'),
            dict(SAFE, insight=''),
            dict(SAFE, insight='Gold 7 din mein neeche aaya, jewellery wale logon ke liye ye buying chance ho sakta hai.'),
            dict(SAFE, insight='Gold neeche aaya kyunki rupee aur crude saste hue, equities upar rahe aaj.'),
        ):
            with self.subTest(invalid=invalid):
                self.assertIsNone(parse_ai_response(reply(invalid), FACTS))

    def test_all_failures_fall_back_without_raise(self):
        err = HTTPError('https://api.groq.com', 429, 'too many', {}, io.BytesIO(b'quota'))
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen', side_effect=[err, err, err]):
                self.assertIsNone(generate_ai_insights(GOLD, MARKETS, NOW))

    def test_weak_data_skips_ai_even_with_key(self):
        weak = {k: None for k in MARKETS}
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy-test-token'}, clear=True):
            with patch('ai_market_insights.urlopen') as call:
                self.assertIsNone(generate_ai_insights(None, weak, NOW))
                call.assert_not_called()

    def test_trend_facts_are_added_and_numbers_allowed(self):
        trend = {'as_of': GOLD['published'], 'change_7d': Decimal('-10320'), 'pct_7d': Decimal('-7.19'),
                 'window_points': 10, 'window_days': 11, 'low': Decimal('133250'),
                 'high': Decimal('143570'), 'is_low': True, 'streak': 3, 'streak_dir': -1}
        facts = market_observations(GOLD, MARKETS, NOW.date(), trend)
        joined = '\n'.join(facts)
        self.assertIn('7 din mein: down Rs 10,320 (-7.19%)', joined)
        self.assertIn('aaj is range ka sabse kam', joined)
        self.assertIn('lagataar 3 din se gir raha hai', joined)
        ok = dict(SAFE, insight='Gold 7 din mein Rs 10,320 sasta hua aur lagataar 3 din se gir raha hai, '
                                'yaani 11 din ka sabse kam level.')
        self.assertIsNotNone(parse_ai_response(reply(ok), facts))

    def test_backup_source_without_silver(self):
        backup = dict(GOLD, silverkg=None, source='goodreturns-bhopal')
        facts = market_observations(backup, MARKETS, NOW.date())
        self.assertIn('Silver: unavailable', facts)
        self.assertTrue(any('Bhopal' in f for f in facts))


if __name__ == '__main__':
    unittest.main()
