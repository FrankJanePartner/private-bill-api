from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from .admin import OrderAdmin, OrderAdminForm
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
    def test_admin_status_dropdown_exposes_only_the_next_payout_state(self):
        order = Order.objects.create(
            id="PB-104",
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
            status="ZEC_CONFIRMED",
        )
        form = OrderAdminForm(instance=order)
        self.assertEqual(
            list(form.fields['status'].choices),
            [('ZEC_CONFIRMED', 'Zec Confirmed'), ('PAYOUT_PROCESSING', 'Payout Processing')],
        )

    def test_admin_status_change_updates_order_and_records_history(self):
        order = Order.objects.create(
            id="PB-106",
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
            status="FIAT_SENT",
        )
        order.status = 'COMPLETED'
        order_admin = OrderAdmin(Order, AdminSite())
        request = RequestFactory().post('/admin/orders/order/')
        request.user = SimpleNamespace(username='operator')

        order_admin.save_model(request, order, form=None, change=True)

        order.refresh_from_db()
        self.assertEqual(order.status, 'COMPLETED')
        self.assertIsNotNone(order.completedAt)
        self.assertEqual(order.statusHistory.latest('at').status, 'COMPLETED')
        self.assertEqual(
            order.statusHistory.latest('at').note,
            'Status changed by admin from FIAT_SENT to COMPLETED.',
        )

    def test_admin_cannot_advance_underpaid_order_from_dropdown(self):
        order = Order.objects.create(
            id="PB-105",
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
            status="UNDERPAID",
        )
        form = OrderAdminForm(instance=order)
        self.assertEqual(
            list(form.fields['status'].choices),
            [('UNDERPAID', 'Underpaid'), ('PAYOUT_PROCESSING', 'Payout Processing')],
        )

    def test_payment_tolerance_accepts_boundary_and_marks_amounts_outside_it(self):
        self.assertEqual(evaluate_payment_status(Decimal('1'), Decimal('0.99'))['status'], 'ZEC_CONFIRMED')
        self.assertEqual(evaluate_payment_status(Decimal('1'), Decimal('1.01'))['status'], 'ZEC_CONFIRMED')
        self.assertEqual(evaluate_payment_status(Decimal('1'), Decimal('0.989'))['status'], 'UNDERPAID')
        self.assertEqual(evaluate_payment_status(Decimal('1'), Decimal('1.011'))['status'], 'OVERPAID')

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

    def test_partial_receipts_accumulate_and_advance_after_confirmations(self):
        order = Order.objects.create(
            id="PB-PARTIAL",
            currency="NGN",
            fiatAmount=5000,
            zecAmount=1.0,
            expectedAmount=Decimal("1.0"),
            rate=5000,
            fee=0,
            recipientCountry="NG",
            recipientBank="Test Bank",
            recipientAccountNumber="123456",
            recipientAccountName="Jane Doe",
            paymentAddress="u1partialaddress",
            status="AWAITING_ZEC",
        )

        first = process_payment_receipt(order, "tx-partial-1", Decimal("0.60"), confirmations=2)
        self.assertEqual(first["status"], "UNDERPAID")
        self.assertEqual(order.receivedAmount, Decimal("0.60"))

        second = process_payment_receipt(order, "tx-partial-2", Decimal("0.395"), confirmations=2)
        self.assertEqual(second["status"], "ZEC_CONFIRMED")
        order.refresh_from_db()
        self.assertEqual(order.receivedAmount, Decimal("0.995"))
        self.assertEqual(order.transactionHash, "tx-partial-2")
        self.assertEqual(order.statusHistory.count(), 3)

    def test_detected_payment_stays_detected_until_confirmation_threshold(self):
        order = Order.objects.create(
            id="PB-CONFIRMING",
            currency="NGN",
            fiatAmount=5000,
            zecAmount=1.0,
            rate=5000,
            fee=0,
            recipientCountry="NG",
            recipientBank="Test Bank",
            recipientAccountNumber="123456",
            recipientAccountName="Jane Doe",
            paymentAddress="u1confirmingaddress",
            status="AWAITING_ZEC",
        )

        result = process_payment_receipt(order, "tx-confirming", Decimal("1.0"), confirmations=0)
        self.assertEqual(result["status"], "ZEC_DETECTED")
        self.assertIsNone(order.paymentConfirmedAt)

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
