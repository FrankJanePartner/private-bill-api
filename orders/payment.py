import os
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Order, OrderHistory


DEFAULT_TOLERANCE_PERCENT = Decimal(os.environ.get("PAYMENT_TOLERANCE_PERCENT", "0.01"))
DEFAULT_TOLERANCE_ZEC = Decimal(os.environ.get("PAYMENT_TOLERANCE_ZEC", "0.000001"))


def get_payment_tolerance_percent():
    raw = os.environ.get("PAYMENT_TOLERANCE_PERCENT", str(DEFAULT_TOLERANCE_PERCENT))
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return DEFAULT_TOLERANCE_PERCENT


def get_payment_tolerance_zec():
    raw = os.environ.get("PAYMENT_TOLERANCE_ZEC", str(DEFAULT_TOLERANCE_ZEC))
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return DEFAULT_TOLERANCE_ZEC


def evaluate_payment_status(expected_amount, actual_amount, tolerance_percent=None):
    try:
        expected = Decimal(str(expected_amount))
        actual = Decimal(str(actual_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Payment amounts must be valid decimal values.")

    percent_tolerance = expected * (tolerance_percent if tolerance_percent is not None else get_payment_tolerance_percent())
    tolerance = max(percent_tolerance, get_payment_tolerance_zec())
    if actual < (expected - tolerance):
        return {
            "status": "UNDERPAID",
            "difference": expected - actual,
            "expectedAmount": expected,
            "receivedAmount": actual,
            "tolerance": tolerance,
        }
    return {
        "status": "ZEC_CONFIRMED",
        "difference": actual - expected,
        "expectedAmount": expected,
        "receivedAmount": actual,
        "tolerance": tolerance,
    }


def _append_order_history(order, status, note):
    OrderHistory.objects.create(order=order, status=status, note=note)


@transaction.atomic
def process_payment_receipt(order, transaction_hash, amount_received, confirmations=0, block_number=None, payment_address=None):
    if not transaction_hash:
        raise ValueError("transactionHash is required.")

    if isinstance(order, str):
        order = Order.objects.get(id=order)

    if not order.statusHistory.exists():
        OrderHistory.objects.create(
            order=order,
            status=order.status,
            note='Order created; waiting for ZEC payment.',
        )

    if Order.objects.filter(transactionHash=transaction_hash).exclude(id=order.id).exists():
        return {
            "processed": False,
            "status": "DUPLICATE_TRANSACTION",
            "message": "This blockchain transaction hash has already been processed for another order.",
            "expectedAmount": order.expectedAmount or order.zecAmount,
            "receivedAmount": Decimal(str(amount_received)),
            "transactionHash": transaction_hash,
            "confirmations": int(confirmations),
            "difference": Decimal("0"),
        }

    if order.transactionHash == transaction_hash and order.status in ("PAYOUT_PROCESSING", "FIAT_SENT", "COMPLETED"):
        return {
            "processed": False,
            "status": order.status,
            "message": "This blockchain transaction has already been processed for this order.",
            "expectedAmount": order.expectedAmount or order.zecAmount,
            "receivedAmount": order.receivedAmount or Decimal("0"),
            "transactionHash": order.transactionHash,
            "confirmations": order.confirmations,
            "difference": Decimal("0"),
        }

    expected_amount = Decimal(str(order.expectedAmount or order.zecAmount))
    incoming_amount = Decimal(str(amount_received))
    is_new_receipt = transaction_hash != order.transactionHash
    total_received = (Decimal(str(order.receivedAmount or 0)) + incoming_amount) if is_new_receipt else incoming_amount
    if not is_new_receipt:
        # Recheck confirmations without adding the same receipt twice.
        total_received = Decimal(str(order.receivedAmount or 0))
    evaluation = evaluate_payment_status(expected_amount, total_received)
    now = timezone.now()

    # Retain the first receipt hash on the order while allowing additional
    # payment receipts to be accumulated against its unique deposit address.
    if not order.transactionHash:
        order.transactionHash = transaction_hash
    order.blockNumber = block_number
    order.confirmations = int(confirmations)
    order.paymentDetectedAt = order.paymentDetectedAt or now
    order.receivedAmount = Decimal(str(evaluation["receivedAmount"]))
    order.expectedAmount = Decimal(str(evaluation["expectedAmount"]))
    order.updatedAt = now

    if payment_address:
        order.paymentAddress = payment_address

    confirmed = int(confirmations) >= int(os.environ.get("ZEC_CONFIRMATION_THRESHOLD", "1"))

    if evaluation["status"] == "ZEC_CONFIRMED" and confirmed:
        order.status = "ZEC_CONFIRMED"
        order.paymentConfirmedAt = order.paymentConfirmedAt or now
        note = (
            f"Payment confirmed: {evaluation['receivedAmount']} ZEC received against "
            f"{evaluation['expectedAmount']} ZEC expected."
        )
    elif evaluation["status"] == "ZEC_CONFIRMED":
        order.status = "ZEC_DETECTED" if int(confirmations) == 0 else "CONFIRMING"
        order.paymentConfirmedAt = None
        note = (
            f"Payment detected: {evaluation['receivedAmount']} ZEC received against "
            f"{evaluation['expectedAmount']} ZEC expected; awaiting confirmations."
        )
    elif evaluation["status"] == "UNDERPAID":
        order.status = "UNDERPAID" if confirmed else ("CONFIRMING" if int(confirmations) > 0 else "ZEC_DETECTED")
        order.paymentConfirmedAt = None
        note = (
            f"Underpaid: {evaluation['receivedAmount']} ZEC received against "
            f"{evaluation['expectedAmount']} ZEC expected. Shortfall: {evaluation['difference']} ZEC."
        )
    else:
        order.status = "OVERPAID"
        order.paymentConfirmedAt = order.paymentConfirmedAt or None
        note = (
            f"Overpaid: {evaluation['receivedAmount']} ZEC received against "
            f"{evaluation['expectedAmount']} ZEC expected. Excess: {evaluation['difference']} ZEC."
        )

    try:
        order.save()
    except IntegrityError:
        existing = Order.objects.get(transactionHash=transaction_hash)
        return {
            "processed": False,
            "status": existing.status,
            "message": "The blockchain transaction was already saved; duplicate processing was prevented.",
            "expectedAmount": existing.expectedAmount or existing.zecAmount,
            "receivedAmount": existing.receivedAmount or Decimal("0"),
            "transactionHash": existing.transactionHash,
            "confirmations": existing.confirmations,
            "difference": Decimal("0"),
        }

    history_note = note if is_new_receipt else f"Payment update: {note}"
    _append_order_history(order, order.status, history_note)

    return {
        "processed": True,
        "status": order.status,
        "message": note,
        "expectedAmount": order.expectedAmount,
        "receivedAmount": order.receivedAmount,
        "transactionHash": order.transactionHash,
        "confirmations": order.confirmations,
        "difference": evaluation["difference"],
    }
