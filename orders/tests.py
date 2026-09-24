from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from .models import Order
from .wallet import WalletUnavailable, generate_wallet
from .payment import evaluate_payment_status, process_payment_receipt


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


class PaymentLifecycleTests(TestCase):
    def test_payment_is_validated_against_expected_amount_and_persisted(self):
        order = Order.objects.create(
            id="PB-100",
            currency="NGN",
            fiatAmount=5000,
            zecAmount=1.0,
            rate=5000,
            fee=0,
            recipientCountry="NG",
            recipientBank="Test Bank",
            recipientAccountNumber="123456",
            recipientAccountName="Jane Doe",
            paymentAddress="u1testaddress",
            status="AWAITING_ZEC",
        )

        result = process_payment_receipt(
            order,
            transaction_hash="tx-valid-1",
            amount_received=Decimal("1.0"),
            confirmations=3,
            block_number=101,
        )

        self.assertEqual(result["status"], "ZEC_CONFIRMED")
        self.assertEqual(order.status, "ZEC_CONFIRMED")
        self.assertEqual(order.transactionHash, "tx-valid-1")
        self.assertEqual(order.receivedAmount, Decimal("1.0"))
        self.assertEqual(order.expectedAmount, Decimal("1.0"))
        self.assertIsNotNone(order.paymentConfirmedAt)
        self.assertEqual(order.statusHistory.count(), 2)

    def test_underpayment_and_overpayment_states_are_preserved(self):
        order = Order.objects.create(
            id="PB-101",
            currency="NGN",
            fiatAmount=5000,
            zecAmount=1.0,
            rate=5000,
            fee=0,
            recipientCountry="NG",
            recipientBank="Test Bank",
            recipientAccountNumber="123456",
            recipientAccountName="Jane Doe",
            paymentAddress="u1testaddress",
            status="AWAITING_ZEC",
        )

        underpaid = process_payment_receipt(order, "tx-under", Decimal("0.50"), confirmations=1)
        self.assertEqual(underpaid["status"], "UNDERPAID")
        self.assertEqual(order.status, "UNDERPAID")

        second_order = Order.objects.create(
            id="PB-102",
            currency="NGN",
            fiatAmount=5000,
            zecAmount=1.0,
            rate=5000,
            fee=0,
            recipientCountry="NG",
            recipientBank="Test Bank",
            recipientAccountNumber="123456",
            recipientAccountName="Jane Doe",
            paymentAddress="u1testaddress2",
            status="AWAITING_ZEC",
        )

        overpaid = process_payment_receipt(second_order, "tx-over", Decimal("1.25"), confirmations=1)
        self.assertEqual(overpaid["status"], "OVERPAID")
        self.assertEqual(second_order.status, "OVERPAID")

    def test_duplicate_transaction_hash_is_rejected_and_not_processed_twice(self):
        order = Order.objects.create(
            id="PB-103",
            currency="NGN",
            fiatAmount=5000,
            zecAmount=1.0,
            rate=5000,
            fee=0,
            recipientCountry="NG",
            recipientBank="Test Bank",
            recipientAccountNumber="123456",
            recipientAccountName="Jane Doe",
            paymentAddress="u1testaddress",
            status="AWAITING_ZEC",
        )

        first = process_payment_receipt(order, "duplicate-tx", Decimal("1.0"), confirmations=3)
        self.assertEqual(first["status"], "ZEC_CONFIRMED")

        second = process_payment_receipt(order, "duplicate-tx", Decimal("1.0"), confirmations=3)
        self.assertFalse(second["processed"])
        self.assertEqual(Order.objects.filter(transactionHash="duplicate-tx").count(), 1)

    def test_seed_super_admin_creates_accessible_admin_account(self):
        User = get_user_model()
        username = "ZOERDHUB"
        email = "zoerdhub@gmail.com"
        password = "ZOERD@team1"

        user = User.objects.create_superuser(username=username, email=email, password=password)

        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.email, email)
