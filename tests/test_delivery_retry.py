import json
import os
import unittest
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

    def test_window(self):
        from zoneinfo import ZoneInfo
        z = ZoneInfo('Asia/Kolkata')
        self.assertFalse(gold_alert.in_delivery_window(datetime(2026, 11, 7, 8, 59, tzinfo=z)))
        self.assertTrue(gold_alert.in_delivery_window(datetime(2026, 11, 7, 9, 17, tzinfo=z)))
        self.assertTrue(gold_alert.in_delivery_window(datetime(2026, 11, 7, 10, 8, tzinfo=z)))
        self.assertTrue(gold_alert.in_delivery_window(datetime(2026, 11, 7, 10, 21, tzinfo=z)))
        self.assertTrue(gold_alert.in_delivery_window(datetime(2026, 11, 7, 11, 0, tzinfo=z)))
        self.assertTrue(gold_alert.in_delivery_window(datetime(2026, 11, 7, 11, 20, tzinfo=z)))
        self.assertFalse(gold_alert.in_delivery_window(datetime(2026, 11, 7, 11, 21, tzinfo=z)))

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
            with self.assertRaisesRegex(RuntimeError, 'Ambiguous network failure'):
                gold_alert.send('Daily message', now=now, ledger=self.ledger)
            gold_alert.send('Daily message', now=now, ledger=self.ledger)
        self.assertEqual(attempted, list(self.chats))
        self.assertEqual(self.ledger.store[self.day][self.ledger.key(self.chats[0])]['status'], 'queued')
        self.assertEqual(self.ledger.store[self.day][self.ledger.key(self.chats[1])]['status'], 'review')


if __name__ == '__main__':
    unittest.main()
