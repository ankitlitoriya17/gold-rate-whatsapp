import os
import unittest
from datetime import date
from unittest.mock import patch
from gold_alert import build_message, latest_common_close, recipient, rupees, send, api_base

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
            '916': feed('916', 13031.8, 12972.6, 13202.2)
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
        self.assertIn('+₹2,507',msg)
        self.assertIn('GST',msg)

    def test_stale_fails(self):
        with self.assertRaises(ValueError):
            latest_common_close(self.docs,date(2026,11,25))

    def test_recipient(self):
        self.assertEqual(recipient('+91 98765-43210'),'919876543210@c.us')
        with self.assertRaises(ValueError):
            recipient('invalid')

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
