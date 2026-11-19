import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

import gold_alert
from delivery_ledger import DeliveryLedger


class MemoryLedger(DeliveryLedger):
    def __init__(self):
        self.store = {}
        self.saves = 0

    def read(self):
        return deepcopy(self.store), "fake-sha" if self.saves else None

    def write(self, state, sha):
        self.store = deepcopy(state)
        self.saves += 1


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.ledger = MemoryLedger()
        self.day = '2026-11-07'
        self.chats = ('919876543210@c.us', '919999999999@c.us')

    def test_persistent_claim_prevents_duplicates(self):
        self.assertTrue(self.ledger.claim(self.day, self.chats[0]))
        self.assertFalse(self.ledger.claim(self.day, self.chats[0]))
        self.assertTrue(self.ledger.claim(self.day, self.chats[1]))
        self.assertTrue(self.ledger.claim('2026-11-08', self.chats[0]))
        self.assertEqual(self.ledger.saves, 3)

    def test_state_contains_no_recipient_phone_numbers(self):
        self.ledger.claim(self.day, self.chats[0])
        snapshot = json.dumps(self.ledger.store)
        self.assertNotIn('919876543210', snapshot)
        self.ledger.update(self.day, self.chats[0], 'queued', 'GREEN123')
        snapshot = json.dumps(self.ledger.store)
        self.assertEqual(self.ledger.store[self.day][self.ledger.key(self.chats[0])]['status'], 'queued')
        self.assertIn('GREEN123', snapshot)

    def test_ledger_requires_credentials(self):
        with self.assertRaises(ValueError):
            DeliveryLedger('owner/repo', '')
        with self.assertRaises(ValueError):
            DeliveryLedger('bad repo', 'fake')

    def _run_main(self, now, env, quote=None, quote_error=None):
        from datia_rates import PriceDataNotReady
        fetch_kwargs = {'side_effect': quote_error} if quote_error else {'return_value': quote}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(gold_alert, 'datetime') as dt, \
                patch.object(gold_alert, 'fetch_datia_quote', **fetch_kwargs) as fetch, \
                patch.object(gold_alert, 'fetch_backup_quote',
                             side_effect=PriceDataNotReady('backup down')), \
                patch.object(gold_alert, 'fetch_market_quotes', return_value={}) as markets, \
                patch.object(gold_alert, 'build_daily_message', return_value='daily text') as build, \
                patch.object(gold_alert, 'send_owner_alert') as alert, \
                patch.object(gold_alert, 'send') as send, \
                redirect_stdout(StringIO()):
            dt.now.return_value = now
            gold_alert.main(sleep=lambda s: None)
        return fetch, markets, build, alert, send

    def test_external_dispatch_sends_even_if_late(self):
        from datetime import date
        from decimal import Decimal
        late = datetime(2026, 11, 12, 22, 45, tzinfo=gold_alert.TZ)
        quote = {'published': late.date(), 'gold24': Decimal('133250'), 'gold22': Decimal('122140'),
                 'silverkg': Decimal('200900'), 'silver_published': late.date(),
                 'gold_table': {date(2026, 11, 11): {'gold24': Decimal('134000'),
                                                     'gold22': Decimal('122800')}}}
        fetch, markets, build, alert, send = self._run_main(
            late, {'SEND_ENABLED': 'true', 'DRY_RUN': 'false'}, quote=quote)
        fetch.assert_called_once_with(late.date())
        markets.assert_called_once_with(late)
        send.assert_called_once_with('daily text', now=late)
        trend = build.call_args.args[1]
        self.assertEqual(trend['prev'], Decimal('134000'))
        alert.assert_not_called()  # backup cross-check failing is not an owner alert

    def test_dry_run_never_sends_or_alerts(self):
        from decimal import Decimal
        now = datetime(2026, 11, 10, 23, 0, tzinfo=gold_alert.TZ)
        quote = {'published': now.date(), 'gold24': Decimal('133250'), 'gold22': Decimal('122140'),
                 'silverkg': Decimal('200900'), 'silver_published': now.date()}
        _, _, build, alert, send = self._run_main(now, {'DRY_RUN': 'true'}, quote=quote)
        build.assert_called_once()
        send.assert_not_called()
        alert.assert_not_called()

    def test_source_unavailable_holds_then_sends_and_alerts_owner(self):
        from datia_rates import PriceDataNotReady
        now = datetime(2026, 11, 12, 22, 0, tzinfo=gold_alert.TZ)
        fetch, _, build, alert, send = self._run_main(
            now, {'SEND_ENABLED': 'true', 'DRY_RUN': 'false', 'HOLD_MINUTES': '10'},
            quote_error=PriceDataNotReady('HTTP 403'))
        self.assertEqual(fetch.call_count, 2)  # first try + one retry after hold
        self.assertIsNone(build.call_args.args[0])
        send.assert_called_once_with('daily text', now=now)
        self.assertIn('bina gold rate', alert.call_args.args[0])

    def test_live_send_then_retry_skips_both(self):
        env = {'GREEN_API_INSTANCE_ID': '123456789',
               'GREEN_API_TOKEN': 'ABCDEF01234567890123',
               'RECIPIENT_1': '919876543210', 'RECIPIENT_2': '919999999999',
               'GROUP_CHAT_ID': '120363012345678901@g.us',
               'GREEN_API_BASE_URL': 'https://7107.api.greenapi.com'}
        sent = []
        def fake_api(url, payload=None):
            if payload is None:
                return {'stateInstance': 'authorized'}
            sent.append(payload['chatId'])
            return {'idMessage': f'queue{len(sent)}'}

        now = datetime(2026, 11, 7, 9, 17, tzinfo=gold_alert.TZ)
        with patch.dict(os.environ, env, clear=True), patch.object(gold_alert, 'call_api', side_effect=fake_api):
            # These are mocked API replies, not real WhatsApp deliveries.
            with redirect_stdout(StringIO()):
                gold_alert.send('Daily message', now=now, ledger=self.ledger)
                gold_alert.send('Daily message', now=now, ledger=self.ledger)
        self.assertEqual(sent, [self.chats[1], '120363012345678901@g.us'])
        self.assertNotIn(self.chats[0], sent)  # RECIPIENT_1 remains ignored

    def test_partial_failure_does_not_resend_first_or_ambiguous_second(self):
        env = {'GREEN_API_INSTANCE_ID': '123456789',
               'GREEN_API_TOKEN': 'ABCDEF01234567890123',
               'RECIPIENT_1': '919876543210', 'RECIPIENT_2': '919999999999',
               'GROUP_CHAT_ID': '120363012345678901@g.us',
               'GREEN_API_BASE_URL': 'https://7107.api.greenapi.com'}
        attempted = []
        def fake_api(url, payload=None):
            if payload is None:
                return {'stateInstance': 'authorized'}
            attempted.append(payload['chatId'])
            if len(attempted) == 2:
                raise RuntimeError('Ambiguous network failure')
            return {'idMessage': 'queued1'}

        now = datetime(2026, 11, 7, 9, 17, tzinfo=gold_alert.TZ)
        with patch.dict(os.environ, env, clear=True), patch.object(gold_alert, 'call_api', side_effect=fake_api):
            with redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'Ambiguous network failure'):
                    gold_alert.send('Daily message', now=now, ledger=self.ledger)
                gold_alert.send('Daily message', now=now, ledger=self.ledger)
        group = '120363012345678901@g.us'
        self.assertEqual(attempted, [self.chats[1], group])
        self.assertNotIn(self.chats[0], attempted)
        self.assertEqual(self.ledger.store[self.day][self.ledger.key(self.chats[1])]['status'], 'queued')
        self.assertEqual(self.ledger.store[self.day][self.ledger.key(group)]['status'], 'review')


if __name__ == '__main__':
    unittest.main()
