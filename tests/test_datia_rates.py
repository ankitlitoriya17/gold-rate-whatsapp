import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from datia_rates import (
    GOLD_URL, SILVER_URL, PriceDataNotReady,
    extract_price_card, fetch_datia_quote, format_datia_message,
)


def page(metal, day, rows, location="Datia"):
    cards = []
    for label, rate, delta in rows:
        direction = "up" if delta > 0 else ("down" if delta < 0 else "neutral")
        cards.append(
            '<div class="gs-karat-cell"><div class="gs-karat-cell__top">'
            f'<span class="gs-karat-cell__label">{label}</span>'
            f'<span class="gs-karat-cell__badge gs-karat-cell__badge--{direction}"'
            f' aria-label="Price up by ₹{abs(delta)}">₹{abs(delta)}</span>'
            '</div><div class="gs-karat-cell__price-row">'
            f'<span class="gs-karat-cell__price">₹{rate:,}</span>'
            '<span class="gs-karat-cell__unit">/10 ग्राम</span></div></div>'
        )
    return (
        '<html><meta name="description" content="Gold in other cities ₹99,99,999">'
        f'<p class="gs-info__last-updated">Last Updated @ {day}</p>'
        '<div class="gs-price-card"><div class="gs-price-card__header">'
        f'<h3 class="gs-price-card__heading">{metal} Price</h3>'
        f'<div class="gs-price-card__location" aria-label="Location: {location}"></div>'
        '</div><div class="gs-karat-grid">'
        + ''.join(cards) + '</div></div></html>'
    )


class DatiaSourceTest(unittest.TestCase):
    def setUp(self):
        self.gold = page('Gold', '10/11/2026', [
            ('22 Karat', 132560, 970), ('24 Karat', 144610, 1050)
        ])
        self.silver = page('Silver', '10/11/2026', [
            ('1 gram', 221, 0), ('1 kg', 220900, 0)
        ])

    def test_price_date_and_card(self):
        day, rates = extract_price_card(self.gold, 'Gold')
        self.assertEqual(day, date(2026, 11, 10))
        self.assertEqual(rates['24 Karat'], (Decimal(144610), Decimal(1050)))
        self.assertEqual(rates['22 Karat'], (Decimal(132560), Decimal(970)))
        day, rates = extract_price_card(self.silver, 'Silver')
        self.assertEqual(rates['1 kg'], (Decimal(220900), Decimal(0)))

    def test_local_message(self):
        with patch('datia_rates.fetch_html', side_effect=[self.gold, self.silver]) as fetch:
            rates = fetch_datia_quote(date(2026, 11, 10))
        self.assertEqual(fetch.call_count, 2)
        msg = format_datia_message(rates)
        self.assertIn('10 Nov 2026 | Datia City Quote', msg)
        self.assertIn('₹1,44,610', msg)  # normalized Indian commas checked in other test
        self.assertIn('₹1,32,560', msg)
        self.assertIn('₹2,20,900', msg)
        self.assertIn('🔺 +₹1,050', msg)
        self.assertIn('↔️ Same', msg)
        self.assertIn('Aaj Tak', msg)
        self.assertNotIn('IBJA', msg)

    def test_stale_gold_refuses_to_send(self):
        outdated = self.gold.replace('10/11/2026', '09/11/2026')
        with patch('datia_rates.fetch_html', side_effect=[outdated, self.silver]):
            with self.assertRaisesRegex(PriceDataNotReady, 'not yet updated'):
                fetch_datia_quote(date(2026, 11, 10))

    def test_stale_silver_refuses_to_send(self):
        outdated = self.silver.replace('10/11/2026', '09/11/2026')
        with patch('datia_rates.fetch_html', side_effect=[self.gold, outdated]):
            with self.assertRaisesRegex(PriceDataNotReady, 'not yet updated'):
                fetch_datia_quote(date(2026, 11, 10))

    def test_bad_location_rejected(self):
        with self.assertRaisesRegex(PriceDataNotReady, 'not Datia'):
            extract_price_card(self.gold.replace('Location: Datia','Location: Gwalior'), 'Gold')

    def test_missing_or_duplicated_published_date_rejected(self):
        with self.assertRaises(PriceDataNotReady):
            extract_price_card(self.gold.replace('Last Updated @ 10/11/2026',''), 'Gold')
        with self.assertRaises(PriceDataNotReady):
            extract_price_card(self.gold.replace('</html>', '<p class="gs-info__last-updated">Last Updated @ 09/11/2026</p></html>'), 'Gold')

    def test_wrong_type_rejected(self):
        with self.assertRaises(PriceDataNotReady):
            extract_price_card(self.silver, 'Gold')

    def test_inconsistent_or_implausible_rates_rejected(self):
        bad = self.gold.replace('₹1,44,610', '₹90,000')
        with patch('datia_rates.fetch_html', side_effect=[bad, self.silver]):
            with self.assertRaisesRegex(PriceDataNotReady,'Implausible'):
                fetch_datia_quote(date(2026, 11, 10))


if __name__ == '__main__':
    unittest.main()
