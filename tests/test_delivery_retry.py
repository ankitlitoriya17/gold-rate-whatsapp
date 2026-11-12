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

    def test_external_dispatch_sends_even_if_late(self):
        from zoneinfo import ZoneInfo
        late = datetime(2026, 11, 12, 22, 45, tzinfo=ZoneInfo('Asia/Kolkata'))
        quote = {'published': late.date()}
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch',
                                      'ENFORCE_DELIVERY_WINDOW': 'true',
                                      'SEND_ENABLED': 'true',
                                      'DRY_RUN': 'false'}, clear=True):
            with patch.object(gold_alert, 'datetime') as dt, patch.object(
                    gold_alert, 'fetch_datia_quote', return_value=quote) as fetch, patch.object(
                    gold_alert, 'format_datia_message', return_value='latest dated rates'), patch.object(
                    gold_alert, 'send') as send:
                dt.now.return_value = late
                gold_alert.main()
                fetch.assert_called_once_with(late.date())
                send.assert_called_once_with('latest dated rates', now=late)

    def test_unrestricted_manual_dry_run_still_allowed(self):
        from zoneinfo import ZoneInfo
        late = datetime(2026, 11, 10, 23, 0, tzinfo=ZoneInfo('Asia/Kolkata'))
        quote = {'published':late.date()}
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch',
                                      'DRY_RUN': 'true',
                                      'ENFORCE_DELIVERY_WINDOW': 'false'}, clear=True):
            with patch.object(gold_alert, 'datetime') as dt, patch.object(
                    gold_alert, 'fetch_datia_quote', return_value=quote) as fetch, patch.object(
                    gold_alert, 'format_datia_message', return_value='preview only') as msg, patch.object(
                    gold_alert, 'send') as send:
                dt.now.return_value = late
                gold_alert.main()
                fetch.assert_called_once_with(late.date())
                msg.assert_called_once_with(quote)
                send.assert_not_called()

    def test_source_unavailable_skips_without_ledger_claim(self):
        from datia_rates import PriceDataNotReady
        now = datetime(2026, 11, 12, 20, 17, tzinfo=gold_alert.TZ)
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch',
                                      'SEND_ENABLED': 'true'}, clear=True):
            with patch.object(gold_alert, 'datetime') as dt, patch.object(
                    gold_alert, 'fetch_datia_quote',
                    side_effect=PriceDataNotReady('unavailable')), patch.object(
                    gold_alert, 'send') as send:
                dt.now.return_value = now
                gold_alert.main()
                send.assert_not_called()

    def test_live_send_then_retry_skips_both(self):
        env = {'GREEN_API_INSTANCE_ID': '123456789',
               'GREEN_API_TOKEN': 'ABCDEF01234567890123',
               'RECIPIENT_1': '919876543210', 'RECIPIENT_2': '919999999999',
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
        self.assertEqual(sent, list(self.chats))

    def test_partial_failure_does_not_resend_first_or_ambiguous_second(self):
        env = {'GREEN_API_INSTANCE_ID': '123456789',
               'GREEN_API_TOKEN': 'ABCDEF01234567890123',
               'RECIPIENT_1': '919876543210', 'RECIPIENT_2': '919999999999',
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
        self.assertEqual(attempted, list(self.chats))
        self.assertEqual(self.ledger.store[self.day][self.ledger.key(self.chats[0])]['status'], 'queued')
        self.assertEqual(self.ledger.store[self.day][self.ledger.key(self.chats[1])]['status'], 'review')


if __name__ == '__main__':
    unittest.main()
