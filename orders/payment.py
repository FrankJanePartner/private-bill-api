import os
from decimal import Decimal, InvalidOperation
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Order, OrderHistory


DEFAULT_TOLERANCE_PERCENT = Decimal(os.environ.get("PAYMENT_TOLERANCE_PERCENT", "0.005"))


def get_payment_tolerance_percent():
    raw = os.environ.get("PAYMENT_TOLERANCE_PERCENT", str(DEFAULT_TOLERANCE_PERCENT))
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return DEFAULT_TOLERANCE_PERCENT


def evaluate_payment_status(expected_amount, actual_amount, tolerance_percent=None):
    try:
        expected = Decimal(str(expected_amount))
        actual = Decimal(str(actual_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Payment amounts must be valid decimal values.")

    tolerance = (expected * (tolerance_percent if tolerance_percent is not None else get_payment_tolerance_percent()))
    if actual < (expected - tolerance):
        return {
            "status": "UNDERPAID",
            "difference": expected - actual,
            "expectedAmount": expected,
            "receivedAmount": actual,
            "tolerance": tolerance,
        }
    if actual > (expected + tolerance):
        return {
            "status": "OVERPAID",
            "difference": actual - expected,
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

    if order.transactionHash and order.transactionHash == transaction_hash:
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

    expected_amount = Decimal(str(order.expectedAmount or order.zecAmount))
    evaluation = evaluate_payment_status(expected_amount, amount_received)
    now = timezone.now()

    order.transactionHash = transaction_hash
    order.blockNumber = block_number
    order.confirmations = int(confirmations)
    order.paymentDetectedAt = order.paymentDetectedAt or now
    order.receivedAmount = Decimal(str(evaluation["receivedAmount"]))
    order.expectedAmount = Decimal(str(evaluation["expectedAmount"]))
    order.updatedAt = now

    if payment_address:
        order.paymentAddress = payment_address

    if evaluation["status"] == "ZEC_CONFIRMED":
        order.status = "ZEC_CONFIRMED"
        order.paymentConfirmedAt = order.paymentConfirmedAt or now
        order.completedAt = order.completedAt or (now if int(confirmations) >= 1 else None)
        note = (
            f"Payment confirmed: {evaluation['receivedAmount']} ZEC received against "
            f"{evaluation['expectedAmount']} ZEC expected."
        )
    elif evaluation["status"] == "UNDERPAID":
        order.status = "UNDERPAID"
        order.paymentConfirmedAt = order.paymentConfirmedAt or None
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

    _append_order_history(order, order.status, note)

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
