import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_brief import (
    ASSETS, IST, MarketQuoteError, fetch_market_quotes,
    format_investor_brief, parse_chart,
)


def chart(price=25299.35, previous=25100, symbol='nifty',
          stamp=None, currency='INR'):
    stamp = stamp or datetime(2026, 11, 12, 15, 31, tzinfo=IST).timestamp()
    return {'chart': {'result': [{
        'meta': {
            'regularMarketPrice': price,
            'chartPreviousClose': previous,
            'currency': currency,
            'regularMarketTime': int(stamp),
        }
    }]}}


NOW = datetime(2026, 11, 12, 21, 30, tzinfo=IST)
GOLD = {
    'published': date(2026, 11, 11),
    'silver_published': date(2026, 11, 10),
    'gold24': Decimal(142680),
    'gold22': Decimal(130790),
    'silverkg': Decimal(220900),
    'delta24': Decimal(-400),
    'delta22': Decimal(-380),
    'delta_silver': Decimal(0),
}


class InvestorBriefTest(unittest.TestCase):
    def test_parses_credible_index_quote_with_date_and_change(self):
        result = parse_chart(chart(), 'nifty', NOW)
        self.assertEqual(result['value'], Decimal('25299.35'))
        self.assertEqual(result['symbol'], '^NSEI')
        self.assertEqual(result['as_of'].date(), NOW.date())
        self.assertGreater(result['change_pct'], 0)

    def test_wrong_currency_and_bad_value_are_rejected(self):
        with self.assertRaisesRegex(MarketQuoteError, 'currency'):
            parse_chart(chart(currency='USD'), 'nifty', NOW)
        with self.assertRaisesRegex(MarketQuoteError, 'implausible'):
            parse_chart(chart(price=0.01), 'nifty', NOW)

    def test_future_or_very_old_quote_rejected(self):
        for shift in (timedelta(hours=2), -timedelta(days=9)):
            with self.subTest(shift=shift):
                with self.assertRaisesRegex(MarketQuoteError, 'too old'):
                    parse_chart(chart(stamp=(NOW + shift).timestamp()), 'nifty', NOW)

    def test_missing_data_and_implausible_change(self):
        self.assertRaises(MarketQuoteError, parse_chart, {'chart': {'result': []}}, 'nifty', NOW)
        result = parse_chart(chart(price=25000, previous=10000), 'nifty', NOW)
        self.assertIsNone(result['change_pct'])

    def test_malformed_missing_provider_never_blocks_gold_report(self):
        with patch('market_brief.fetch_chart', side_effect=MarketQuoteError('rate limited')):
            data = fetch_market_quotes(NOW)
        self.assertEqual(set(data), set(ASSETS))
        self.assertTrue(all(x is None for x in data.values()))
        message = format_investor_brief(GOLD, data, NOW)
        self.assertIn('Nifty 50: unavailable', message)
        self.assertIn('Brent futures: unavailable', message)
        self.assertIn('₹1,42,680/10g', message)
        self.assertIn('Gold 11 Nov · Silver 10 Nov', message)

    def test_compact_message_and_stale_dates_no_fake_movements(self):
        markets = {
            'nifty': parse_chart(chart(), 'nifty', NOW),
            'sensex': parse_chart(chart(81911.01, 81000, currency='INR'), 'sensex', NOW),
            'usdinr': parse_chart(chart(94.033, 94.45, currency='INR',
                stamp=datetime(2026, 11, 12, 20, 45, tzinfo=IST).timestamp()), 'usdinr', NOW),
            'brent': parse_chart(chart(93.58, 92.57, currency='USD',
                stamp=datetime(2026, 11, 12, 21, 10, tzinfo=IST).timestamp()), 'brent', NOW),
        }
        message = format_investor_brief(GOLD, markets, NOW)
        self.assertIn('9:30 PM IST', message)
        self.assertIn('₹1,42,680/10g', message)
        self.assertIn('₹1,30,790/10g', message)
        self.assertIn('₹2,20,900/kg', message)
        self.assertIn('Older published quotes', message)
        self.assertIn('Nifty 50: 25,299.35', message)
        self.assertIn('Sensex: 81,911.01', message)
        self.assertIn('USD/INR: ₹94.03/USD', message)
        self.assertIn('Brent futures: $93.58/bbl', message)
        self.assertIn('Indian indices higher', message)
        self.assertIn('INR stronger vs USD', message)
        self.assertLess(len(message), 1400)

    def test_fresh_rates_get_changes_only_when_current(self):
        gold = GOLD | {
            'published': NOW.date(), 'silver_published': NOW.date()
        }
        message = format_investor_brief(gold, {}, NOW)
        self.assertIn('↓ −₹400', message)
        self.assertIn('↓ −₹380', message)
        self.assertIn('→ Same', message)
        self.assertNotIn('Older published quotes', message)

    def test_missing_datia_source_still_returns_daily_brief(self):
        market = {key: None for key in ASSETS}
        message = format_investor_brief(None, market, NOW)
        self.assertIn('DATIA | DAILY INVESTOR BRIEF', message)
        self.assertIn('24K Gold: unavailable', message)
        self.assertIn('Silver 999: unavailable', message)
        self.assertIn('All price sources are temporarily unavailable', message)
        self.assertNotIn('₹1,42,680', message)
        self.assertIn('Report' if False else '12 Nov 2026', message)

    def test_snapshot_does_not_claim_forecast_or_recommendation(self):
        msg = format_investor_brief(GOLD, {}, NOW)
        self.assertIn('No investment recommendation', msg)
        self.assertNotIn('buy now', msg.lower())
        self.assertNotIn('guaranteed', msg.lower())


if __name__ == '__main__':
    unittest.main()
