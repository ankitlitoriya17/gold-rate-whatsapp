import io
import os
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import backup_rates
import owner_alert
import rate_history
import weekly_chart
from daily_message import build_daily_message, headline, jewellery_block, money
from datia_rates import extract_history_table
from tips import TIPS, tip_for

IST = ZoneInfo('Asia/Kolkata')
NOW = datetime(2026, 11, 19, 22, 0, tzinfo=IST)
TODAY = NOW.date()


def gold_table(rows, year=2026):
    body = ''.join(
        f'<tr> <td>{label}</td> <td class="gh-price">₹{g24:,}</td> <td>x</td> '
        f'<td class="gh-price">₹{g22:,}</td> <td>x</td> <td>₹1</td> <td>x</td> <td>₹1</td> <td>x</td> </tr>'
        for label, g24, g22 in rows)
    return (f'<div class="gh-table-wrapper"><table class="gh-table" aria-label="h"><thead><tr> '
            f'<th scope="col">Datia<br>{year}</th> </tr></thead><tbody>{body}</tbody></table></div>')


def quote(day=TODAY, g24=133250, g22=122140, kg=200900, d24=-2780, table=None, source='aajtak-datia'):
    return {'published': day, 'silver_published': day, 'gold24': Decimal(g24), 'gold22': Decimal(g22),
            'silverkg': Decimal(kg) if kg else None, 'delta24': Decimal(d24) if d24 is not None else None,
            'delta22': Decimal('-2550'), 'delta_silver': Decimal('-5000'), 'source': source,
            'gold_table': table or {}, 'silver_table': {}}


def history_from(prices, end=TODAY):
    """prices oldest->newest, one per day ending at `end`."""
    start = end - timedelta(days=len(prices) - 1)
    return {(start + timedelta(days=i)).isoformat():
            {'gold24': str(p), 'gold22': str(int(p * 0.9166)), 'silverkg': '200000',
             'source': 'aajtak-datia'} for i, p in enumerate(prices)}


class HistoryTableTest(unittest.TestCase):
    def test_parses_rows_and_skips_bad_ones(self):
        page = gold_table([('Nov 18', 136030, 124690), ('Nov 17', 136790, 125390), ('Total', 1, 1)])
        rows = extract_history_table(page, 'gold', date(2026, 11, 19))
        self.assertEqual(rows[date(2026, 11, 18)], {'gold24': Decimal(136030), 'gold22': Decimal(124690)})
        self.assertEqual(len(rows), 2)

    def test_december_rows_in_january_use_previous_year(self):
        page = gold_table([('Jan 02', 136030, 124690), ('Dec 31', 135000, 123700)], year=2027)
        rows = extract_history_table(page, 'gold', date(2027, 1, 3))
        self.assertIn(date(2026, 12, 31), rows)

    def test_no_table(self):
        self.assertEqual(extract_history_table('<html></html>', 'gold', NOW.date()), {})


class RateHistoryTest(unittest.TestCase):
    def test_merge_card_and_table_and_never_overwrite_with_backup(self):
        table = {date(2026, 11, 18): {'gold24': Decimal(136030), 'gold22': Decimal(124690)}}
        merged = rate_history.merge({}, quote(table=table))
        self.assertEqual(merged['2026-11-19']['gold24'], '133250')
        self.assertEqual(merged['2026-11-18']['gold24'], '136030')
        again = rate_history.merge(merged, quote(g24=130740, g22=119850, source='goodreturns-bhopal'))
        self.assertEqual(again['2026-11-19']['gold24'], '133250')

    def test_stats_low_streak_and_changes(self):
        prices = [140000] * 20 + [143570, 142000, 139000, 136790, 136030, 133250]
        st = rate_history.stats(history_from(prices), 'gold24', NOW.date())
        self.assertEqual(st['latest'], Decimal(133250))
        self.assertEqual(st['prev'], Decimal(136030))
        self.assertTrue(st['is_low'])
        self.assertEqual(st['streak'], 5)
        self.assertEqual(st['streak_dir'], -1)
        self.assertEqual(st['change_7d'], Decimal(133250 - 140000))
        self.assertEqual(st['window_days'], 26)

    def test_backup_rows_excluded_from_trend(self):
        hist = history_from([140000, 139000])
        hist['2026-11-19']['source'] = 'goodreturns-bhopal'
        self.assertIsNone(rate_history.stats(hist, 'gold24', NOW.date()))


class BackupSourceTest(unittest.TestCase):
    GOLD = ('<title>Todays Gold Rate in Bhopal, 18, 22 & 24 Carat Gold Price on 19 November 2026 - '
            'Goodreturns</title><span id="24K-price">&#x20b9;13,074</span> '
            '<span id="22K-price">&#x20b9;11,985</span>')
    SILVER = ('<title>Todays Silver Rate in Bhopal, Silver Price on 19 November 2026 - Goodreturns</title>'
              '<span id="silver-1kg-price">&#x20b9;1,80,000</span>')

    def test_parse_per_gram_to_10g(self):
        self.assertEqual(backup_rates.parse_gold(self.GOLD),
                         (date(2026, 11, 19), Decimal(130740), Decimal(119850)))
        self.assertEqual(backup_rates.parse_silver(self.SILVER), (date(2026, 11, 19), Decimal(180000)))

    def test_fetch_backup_quote_shape(self):
        with patch('backup_rates._get', side_effect=[self.GOLD, self.SILVER]):
            q = backup_rates.fetch_backup_quote(NOW.date())
        self.assertEqual(q['source'], 'goodreturns-bhopal')
        self.assertIsNone(q['delta24'])

    def test_cross_check(self):
        b = quote(g24=130740, g22=119850, source='goodreturns-bhopal')
        self.assertIsNone(backup_rates.cross_check(quote(), b))  # 1.9% gap is normal
        self.assertIn('fark', backup_rates.cross_check(quote(g24=150000, g22=137000), b))


class DailyMessageTest(unittest.TestCase):
    def test_headline_variants(self):
        trend = rate_history.stats(history_from([140000] * 8 + [136030, 133250]), 'gold24', NOW.date())
        self.assertIn('₹2,780 sasta — 10 din ka sabse kam rate', headline(quote(), trend, NOW))
        self.assertIn('nahi mil paya', headline(None, None, NOW))
        old = quote(day=date(2026, 11, 18))
        self.assertIn('18 Nov ka rate', headline(old, None, NOW))
        self.assertIn('sthir', headline(quote(d24=0), None, NOW))
        self.assertIn('bada move', headline(quote(d24=-2780), None, NOW))

    def test_full_message(self):
        hist = history_from([140000] * 25 + [136030, 133250])
        trend = rate_history.stats(hist, 'gold24', NOW.date())
        market = {'nifty': {'value': Decimal('25514.30'), 'change_pct': Decimal('1.47')},
                  'usdinr': {'value': Decimal('93.28'), 'change_pct': Decimal('-0.80')}}
        msg = build_daily_message(quote(), trend, market, NOW,
                                  ai_insights={'insight': 'AI line', 'watch': 'Watch line'},
                                  tip='Tip line')
        for text in ('🪙 *Datia Gold Update* · 19 Nov, Thu', '🟡 *24K:* ₹1,33,250/10g  (−₹2,780)',
                     '1 gram: 24K ₹13,325 · 22K ₹12,214', '⚪ *Chandi:* ₹2,00,900/kg  (−₹5,000) · ₹2,009/10g',
                     '📊 *Trend · 24K*', '7 din: −₹6,750 (−4.8%)', '💍 *10g 22K jewellery ka andaaza*',
                     '📈 Nifty 25,514 ▲1.47%', '$1 = ₹93.28 ▼0.80%', '🧠 *AI ki nazar se*',
                     '💡 *Kaam ki baat:* Tip line', 'Investment salah nahi'):
            self.assertIn(text, msg)
        self.assertNotIn('Sensex', msg)  # unavailable items are skipped, not shown as gaps

    def test_unavailable_message_has_no_numbers_for_gold(self):
        msg = build_daily_message(None, None, {}, NOW)
        self.assertIn('unavailable', msg)
        self.assertNotIn('jewellery', msg)

    def test_jewellery_estimate(self):
        lines = jewellery_block(quote())
        # 122140 * 1.08 * 1.03 = 135,868 -> 1,35,900 ; * 1.15 * 1.03 = 1,44,672 -> 1,44,700
        self.assertIn('₹1,35,900 – ₹1,44,700', lines[1])

    def test_money(self):
        self.assertEqual(money(Decimal('12214.0')), '₹12,214')


class TipsTest(unittest.TestCase):
    def test_tip_days_and_rotation(self):
        monday = date(2026, 11, 16)
        self.assertIsNotNone(tip_for(monday))
        self.assertIsNone(tip_for(monday + timedelta(days=1)))
        seen = {tip_for(monday + timedelta(days=7 * w + o)) for w in range(4) for o in (0, 2, 4)}
        self.assertEqual(len(seen), len(TIPS))


class WeeklyTest(unittest.TestCase):
    def test_caption_and_chart(self):
        sunday = date(2026, 11, 22)
        hist = history_from([140000, 139000, 138000, 137000, 136000, 135000, 134000, 133000, 133500], sunday)
        caption = weekly_chart.weekly_caption(hist, sunday)
        self.assertIn('Hafte ka hisaab* · 16 Nov – 22 Nov', caption)
        self.assertIn('₹1,39,000 → ₹1,33,500', caption)
        png = weekly_chart.render_chart(hist, sunday)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertTrue(weekly_chart.is_weekly_day(sunday))

    def test_media_base(self):
        self.assertEqual(weekly_chart.media_base('https://7103.api.greenapi.com'),
                         'https://7103.media.greenapi.com')
        self.assertEqual(weekly_chart.media_base('https://api.green-api.com'),
                         'https://media.green-api.com')

    def test_upload_falls_back_to_api_host_only_on_network_error(self):
        calls = []
        def fake(url, *a):
            calls.append(url)
            if 'media' in url:
                raise RuntimeError('GREEN-API upload network failure (dns)')
            return {'idMessage': 'ok'}
        with patch('weekly_chart.upload_file', side_effect=fake), redirect_stdout(io.StringIO()):
            out = weekly_chart.upload_with_fallback('https://7107.api.greenapi.com', '1', 't',
                                                    'x@c.us', 'c', 'a.png', b'p')
        self.assertEqual(out['idMessage'], 'ok')
        self.assertEqual([u.split('/waInstance')[0] for u in calls],
                         ['https://7107.media.greenapi.com', 'https://7107.api.greenapi.com'])
        with patch('weekly_chart.upload_file', side_effect=RuntimeError('GREEN-API upload returned HTTP 500')) as up:
            with self.assertRaises(RuntimeError):
                weekly_chart.upload_with_fallback('https://7107.api.greenapi.com', '1', 't',
                                                  'x@c.us', 'c', 'a.png', b'p')
        self.assertEqual(up.call_count, 1)

    def test_upload_builds_multipart(self):
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return b'{"idMessage": "X1"}'
        with patch('weekly_chart.urlopen', return_value=R()) as call:
            out = weekly_chart.upload_file('https://1.media.greenapi.com/waInstance1/sendFileByUpload/t',
                                           '1203@g.us', 'cap', 'a.png', b'\x89PNG')
        self.assertEqual(out['idMessage'], 'X1')
        data = call.call_args.args[0].data
        self.assertIn(b'name="chatId"\r\n\r\n1203@g.us', data)
        self.assertIn(b'filename="a.png"', data)


class OwnerAlertTest(unittest.TestCase):
    def test_dry_run_only_prints(self):
        out = io.StringIO()
        with patch.dict(os.environ, {'DRY_RUN': 'true'}, clear=True), redirect_stdout(out):
            self.assertFalse(owner_alert.send_owner_alert('test', NOW))
        self.assertIn('not sent', out.getvalue())

    def test_group_id_never_used_for_alerts(self):
        with patch.dict(os.environ, {'RECIPIENT_2': '120363012345678901@g.us'}, clear=True):
            with self.assertRaises(ValueError):
                owner_alert.owner_chat()

    def test_sends_to_owner_number(self):
        env = {'SEND_ENABLED': 'true', 'RECIPIENT_1': '120363012345678901@g.us', 'RECIPIENT_2': '919876543210', 'GREEN_API_INSTANCE_ID': '123',
               'GREEN_API_TOKEN': 'ABCDEF01234567890123', 'GREEN_API_BASE_URL': 'https://7107.api.greenapi.com'}
        with patch.dict(os.environ, env, clear=True), patch('gold_alert.call_api',
                                                             return_value={'idMessage': 'A'}) as api, \
                redirect_stdout(io.StringIO()):
            self.assertTrue(owner_alert.send_owner_alert('Datia fail', NOW))
        self.assertEqual(api.call_args.args[1]['chatId'], '919876543210@c.us')
        self.assertIn('Datia fail', api.call_args.args[1]['message'])

    def test_watchdog_alerts_on_missing_send(self):
        from test_delivery_retry import MemoryLedger
        ledger = MemoryLedger()
        env = {'RECIPIENT_2': '919999999999', 'GROUP_CHAT_ID': '120363012345678901@g.us'}
        with patch.dict(os.environ, env, clear=True), \
                patch('owner_alert.send_owner_alert') as alert, redirect_stdout(io.StringIO()):
            ledger.claim(NOW.date().isoformat(), '919999999999@c.us')
            ledger.update(NOW.date().isoformat(), '919999999999@c.us', 'queued', 'm1')
            self.assertFalse(owner_alert.watchdog(NOW, ledger))
        text = alert.call_args.args[0]
        self.assertIn('Group: not attempted', text)
        self.assertNotIn('RECIPIENT_2', text)


class WeeklySendSlotTest(unittest.TestCase):
    def test_weekly_slot_uses_separate_claim_and_upload(self):
        import gold_alert
        from test_delivery_retry import MemoryLedger
        ledger = MemoryLedger()
        env = {'GREEN_API_INSTANCE_ID': '123456789', 'GREEN_API_TOKEN': 'ABCDEF01234567890123',
               'RECIPIENT_2': '919999999999', 'GREEN_API_BASE_URL': 'https://7107.api.greenapi.com'}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(gold_alert, 'call_api', side_effect=lambda u, p=None:
                             {'stateInstance': 'authorized'} if p is None else {'idMessage': 'd1'}), \
                patch('weekly_chart.upload_file', return_value={'idMessage': 'w1'}) as up, \
                redirect_stdout(io.StringIO()):
            gold_alert.send('daily', now=NOW, ledger=ledger)
            gold_alert.send('cap', now=NOW, ledger=ledger, image=b'png', slot='weekly')
            gold_alert.send('cap', now=NOW, ledger=ledger, image=b'png', slot='weekly')
        self.assertEqual(up.call_count, 1)
        self.assertTrue(up.call_args.args[0].startswith('https://7107.media.greenapi.com/waInstance123456789/'))
        self.assertEqual(len(ledger.store[NOW.date().isoformat()]), 2)


if __name__ == '__main__':
    unittest.main()


class InvestmentAndEighteenKTest(unittest.TestCase):
    def test_18k_from_history_table(self):
        page = ('<table class="gh-table"><thead><tr><th scope="col">Datia<br>2026</th></tr></thead><tbody>'
                '<tr> <td>Nov 18</td> <td>₹1,36,030</td> <td>x</td> <td>₹1,24,690</td> <td>x</td> '
                '<td>₹1,02,022</td> <td>x</td> <td>₹79,351</td> <td>x</td> </tr></tbody></table>')
        rows = extract_history_table(page, 'gold', TODAY)
        self.assertEqual(rows[date(2026, 11, 18)]['gold18'], Decimal(102022))

    def test_18k_shown_with_per_gram(self):
        q = dict(quote(), gold18=Decimal(99937), delta18=Decimal(-2085))
        msg = build_daily_message(q, None, {}, NOW)
        self.assertIn('🟡 *18K:* ₹99,937/10g  (−₹2,085)', msg)
        self.assertIn('· 18K ₹9,994', msg)
        self.assertNotIn('18K', build_daily_message(quote(), None, {}, NOW))

    def test_investment_facts_and_block(self):
        hist = history_from([142680, 140000, 139000, 138000, 137000, 136030, 135000, 133250])
        hist['2026-11-12']['nifty'] = '25000'
        hist['2026-11-12']['silverkg'] = '220900'
        q = quote()
        info = rate_history.investment(hist, q, {'nifty': {'value': Decimal('25514.30')}})
        self.assertAlmostEqual(float(info['grams_per_lakh']), 7.505, places=3)
        self.assertAlmostEqual(float(info['grams_per_lakh_7d']), 7.009, places=3)
        self.assertAlmostEqual(float(info['ratio']), 66.33, places=2)
        self.assertAlmostEqual(float(info['nifty_pct_7d']), 2.057, places=2)
        from daily_message import investment_block
        block = '\n'.join(investment_block(info))
        self.assertIn('₹1 lakh = 7.50g 24K sona (7 din pehle 7.01g)', block)
        self.assertIn('Gold:Silver ratio 66.3 (7 din pehle 64.6)', block)
        self.assertIn('7 din: Gold −6.6% · Nifty +2.1%', block)

    def test_market_snapshot_only_on_primary_row(self):
        hist = history_from([133250])
        out = rate_history.merge_market(hist, {'nifty': {'value': Decimal('25514.3')},
                                               'goldusd': None}, TODAY)
        self.assertEqual(out[TODAY.isoformat()]['nifty'], '25514.3')
        self.assertNotIn('gold_usd', out[TODAY.isoformat()])
        self.assertEqual(rate_history.merge_market({}, {'nifty': {'value': 1}}, TODAY), {})

    def test_intl_gold_and_etf_line(self):
        from daily_message import market_block
        lines = market_block({'goldusd': {'value': Decimal('4051.2'), 'change_pct': Decimal('-1.2')},
                              'goldbees': {'value': Decimal('112.45'), 'change_pct': Decimal('-2.0')}})
        self.assertEqual(lines, ['🥇 Intl gold $4,051/oz ▼1.20% · GoldBees ETF ₹112.45 ▼2.00%'])
