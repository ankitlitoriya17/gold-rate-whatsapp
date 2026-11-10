import os
import unittest
from datetime import date
from unittest.mock import patch
from gold_alert import build_message, latest_common_close, recipient, rupees, send, api_base, group_chat_id, destination_chats

def feed(purity, v1, v2, v3):
    return {'metal':'gold','purity':purity,'unit':'INR per gram','source':'IBJA','rows':[
        {'date':'2026-10-29','pm':v1},
        {'date':'2026-11-04','pm':v2},
        {'date':'2026-11-05','pm':v3},
        {'date':'2026-11-06','am':15000,'pm':None}
    ]}

class GoldTest(unittest.TestCase):
    def setUp(self):
        self.docs = {
            '999': feed('999', 14225.5, 14162.2, 14412.9),
            '916': feed('916', 13031.8, 12972.6, 13202.2),
            'silver': {'metal':'silver','purity':'999','unit':'INR per gram','source':'IBJA','rows':[
                {'date':'2026-10-29','close':180},
                {'date':'2026-11-04','close':181},
                {'date':'2026-11-05','close':182},
            ]}
        }

    def test_latest_pm_and_week(self):
        latest, previous, week, _ = latest_common_close(self.docs,date(2026,11,6))
        self.assertEqual((latest,previous,week),
                         (date(2026,11,5),date(2026,11,4),date(2026,10,29)))

    def test_message(self):
        msg=build_message(self.docs,date(2026,11,6))
        self.assertIn('05 Nov 2026',msg)
        self.assertIn('₹1,44,129',msg)
        self.assertIn('₹1,32,022',msg)
        self.assertIn('Silver (999)',msg)
        self.assertIn('₹1,82,000',msg)
        self.assertIn('🔺',msg)
        self.assertNotIn('7-day change',msg)
        self.assertIn('GST',msg)

    def test_old_rates_are_labelled_not_new_daily_falls(self):
        msg = build_message(self.docs, date(2026, 11, 10))
        self.assertIn('Report: 10 Nov 2026', msg)
        self.assertIn('Latest IBJA rate: *05 Nov 2026 (PM)*', msg)
        self.assertIn('Naya IBJA rate abhi available nahi hai', msg)
        self.assertIn('₹1,44,129', msg)
        self.assertNotIn('🔺', msg)
        self.assertNotIn('🔻', msg)
        self.assertNotIn('Change vs pichhle published', msg)

    def test_weekend_uses_friday_without_fake_daily_move(self):
        from copy import deepcopy
        docs = deepcopy(self.docs)
        for purity in ('999', '916'):
            docs[purity]['rows'].append({'date': '2026-11-06', 'pm': 14300})
        docs['silver']['rows'].append({'date': '2026-11-06', 'pm': 185})
        msg = build_message(docs, date(2026, 11, 8))
        self.assertIn('Report: 08 Nov 2026', msg)
        self.assertIn('Latest IBJA rate: *06 Nov 2026 (PM)*', msg)
        self.assertIn('Weekend', msg)
        self.assertNotIn('🔺', msg)
        self.assertNotIn('🔻', msg)

    def test_stale_fails(self):
        with self.assertRaises(ValueError):
            latest_common_close(self.docs,date(2026,11,25))

    def test_recipient(self):
        self.assertEqual(recipient('+91 98765-43210'),'919876543210@c.us')
        with self.assertRaises(ValueError):
            recipient('invalid')

    def test_group_chat_id(self):
        self.assertEqual(group_chat_id('120363012345678901@g.us'),
                         '120363012345678901@g.us')
        with self.assertRaises(ValueError):
            group_chat_id('919876543210@c.us')
        with self.assertRaises(ValueError):
            group_chat_id('bad@g.us')

    def test_destinations_optional_group(self):
        env = {'RECIPIENT_1': '919876543210',
               'RECIPIENT_2': '919999999999'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(len(destination_chats()), 2)
        env['GROUP_CHAT_ID'] = '120363012345678901@g.us'
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(len(destination_chats()), 3)

    def test_currency(self):
        self.assertEqual(rupees('1234567.5'),'₹12,34,568')

    def test_missing_secrets(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'Missing GitHub Actions secrets'):
                send('test')

    def test_api_base_host(self):
        with patch.dict(os.environ,{'GREEN_API_BASE_URL':'https://7107.api.greenapi.com'}):
            self.assertEqual(api_base(),'https://7107.api.greenapi.com')
        with patch.dict(os.environ,{'GREEN_API_BASE_URL':'https://bad.example.com'}):
            with self.assertRaises(ValueError):
                api_base()

if __name__=='__main__':
    unittest.main()
