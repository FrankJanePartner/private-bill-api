from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .wallet import WalletUnavailable, generate_wallet


class ZPayAddressAllocationTests(SimpleTestCase):
    @patch.dict("os.environ", {
        "ZPAY_API_BASE_URL": "https://zpay.example",
        "ZPAY_API_KEY": "test-key",
    }, clear=True)
    @patch("orders.wallet.requests.post")
    def test_requests_a_unified_address_from_zpay(self, post):
        address = "u1" + "a" * 180
        response = Mock()
        response.json.return_value = {"address": address}
        post.return_value = response

        self.assertEqual(generate_wallet("PB-TEST-1234", "0.01234567"), address)
        _, kwargs = post.call_args
        self.assertEqual(kwargs["json"]["amount_zatoshis"], "1234567")
        self.assertEqual(kwargs["headers"]["Idempotency-Key"], "PB-TEST-1234")

    @patch.dict("os.environ", {
        "ZPAY_API_BASE_URL": "https://zpay.example",
        "ZPAY_API_KEY": "test-key",
    }, clear=True)
    @patch("orders.wallet.requests.post")
    def test_rejects_transparent_address(self, post):
        response = Mock()
        response.json.return_value = {"address": "t1not-a-shielded-address"}
        post.return_value = response

        with self.assertRaises(WalletUnavailable):
            generate_wallet("PB-TEST-1234", "1")
