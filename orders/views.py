import os
import uuid
from urllib.parse import quote as url_quote
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import requests
from django.db import OperationalError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Order, OrderHistory
from .payment import evaluate_payment_status, process_payment_receipt
from .serializers import (
    CreateOrderRequestSerializer,
    OrderSerializer,
    PaymentStatusSerializer,
    QuoteRequestSerializer,
    QuoteSerializer,
)
from .wallet import WalletUnavailable, generate_payment_request

@extend_schema(
    request=QuoteRequestSerializer,
    responses={200: QuoteSerializer},
)
@api_view(['POST'])
def quote(request):
    currency = request.data.get('currency')
    try:
        fiatAmount = float(request.data.get('fiatAmount', 0))
    except (TypeError, ValueError):
        return Response({'error': 'fiatAmount must be a number.'}, status=status.HTTP_400_BAD_REQUEST)

    if currency not in ('NGN', 'GHS') or fiatAmount < 0:
        return Response({'error': 'currency must be NGN or GHS and fiatAmount must not be negative.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        rates_response = requests.get(
            'https://api.coinbase.com/v2/exchange-rates',
            params={'currency': 'ZEC'},
            headers={'Accept': 'application/json'},
            timeout=10,
        )
        rates_response.raise_for_status()
        rate = float(rates_response.json()['data']['rates'][currency])
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return Response({'error': 'Live ZEC pricing is temporarily unavailable.'}, status=status.HTTP_502_BAD_GATEWAY)

    fee = 0 if fiatAmount == 0 else max(fiatAmount * 0.0125, 75 if currency == 'NGN' else 0.5)
    zecAmount = round((fiatAmount + fee) / rate, 8)
    expiresAt = (timezone.now() + timedelta(minutes=10)).isoformat()
    
    return Response({
        'currency': currency,
        'fiatAmount': fiatAmount,
        'zecAmount': zecAmount,
        'rate': rate,
        'fee': fee,
        'expiresAt': expiresAt,
        'source': 'backend'
    })

@extend_schema(
    request=CreateOrderRequestSerializer,
    responses={201: OrderSerializer},
)
@api_view(['POST'])
def create_order(request):
    quote_data = request.data.get('quote', {})
    recipient_data = request.data.get('recipient', {})
    
    reference = f"PB-{str(uuid.uuid4()).split('-')[0].upper()}-{str(timezone.now().timestamp()).split('.')[0][-4:]}"
    try:
        payment_request = generate_payment_request(reference, quote_data.get('zecAmount'))
    except WalletUnavailable:
        # Never create an order with a fake or transparent fallback address.
        return Response(
            {'error': 'Shielded Zcash address allocation is temporarily unavailable. Retry this order.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    
    try:
        with transaction.atomic():
            order = Order.objects.create(
                id=payment_request['id'],
                currency=quote_data.get('currency'),
                fiatAmount=quote_data.get('fiatAmount'),
                zecAmount=quote_data.get('zecAmount'),
                expectedAmount=Decimal(str(quote_data.get('zecAmount', 0))),
                receivedAmount=Decimal('0.00000000'),
                rate=quote_data.get('rate'),
                fee=quote_data.get('fee'),
                recipientCountry=recipient_data.get('country'),
                recipientBank=recipient_data.get('bank'),
                recipientAccountNumber=recipient_data.get('accountNumber'),
                recipientAccountName=recipient_data.get('accountName'),
                paymentAddress=payment_request['address'],
                status='AWAITING_ZEC',
                source='zpay'
            )

            OrderHistory.objects.create(
                order=order,
                status='AWAITING_ZEC',
                note='Order created; waiting for ZEC payment.'
            )
    except OperationalError:
        return Response(
            {'error': 'Order storage is unavailable. Configure the backend database before creating orders.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except (KeyError, TypeError, ValueError):
        return Response({'error': 'ZPay returned an incomplete payment request.'}, status=status.HTTP_502_BAD_GATEWAY)
    
    serializer = OrderSerializer(order)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


def refresh_zpay_order(order):
    if order.source != 'zpay' or order.status not in ('AWAITING_ZEC', 'ZEC_DETECTED', 'CONFIRMING', 'UNDERPAID', 'OVERPAID'):
        return order
    api_base = os.environ.get('ZPAY_API_BASE_URL', '').rstrip('/')
    api_key = os.environ.get('ZPAY_API_KEY', '')
    if not api_base or not api_key:
        return order
    try:
        upstream = requests.get(
            f"{api_base}/api/v1/payment-requests/{url_quote(order.id, safe='')}/",
            headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'},
            timeout=15,
        )
        upstream.raise_for_status()
        payment_request = upstream.json()
        if payment_request.get('address') != order.paymentAddress:
            return order
        expected = order.expectedAmount or Decimal(str(order.zecAmount))
        received = Decimal(str(payment_request.get('received_zatoshis', '0'))) / Decimal('100000000')
    except (requests.RequestException, ValueError, TypeError, InvalidOperation):
        return order

    evaluation = evaluate_payment_status(expected, received)
    funding_status = str(payment_request.get('funding_status', '')).lower()
    paid = funding_status in ('paid', 'fully_paid', 'overpaid') or str(payment_request.get('status', '')).lower() == 'completed'
    now = timezone.now()
    previous_status = order.status
    previous_received = order.receivedAmount
    order.receivedAmount = received
    order.updatedAt = now
    if evaluation['status'] == 'OVERPAID':
        order.status = 'OVERPAID'
    elif evaluation['status'] == 'UNDERPAID':
        order.status = 'UNDERPAID' if paid else ('ZEC_DETECTED' if received > 0 else 'AWAITING_ZEC')
    elif evaluation['status'] == 'ZEC_CONFIRMED':
        # The configured absolute tolerance is authoritative. ZPay may still
        # label a payment partially_paid/underpaid while the amount is within
        # our accepted slippage, so requiring its exact funding label here
        # would leave a valid payment at ZEC_DETECTED indefinitely.
        order.status = 'PAYOUT_PROCESSING'
        order.confirmations = max(1, order.confirmations)
        order.paymentDetectedAt = order.paymentDetectedAt or now
        order.paymentConfirmedAt = order.paymentConfirmedAt or now
    else:
        order.status = 'ZEC_DETECTED' if received > 0 else 'AWAITING_ZEC'

    if previous_status != order.status:
        order.save()
        if order.status == 'PAYOUT_PROCESSING':
            OrderHistory.objects.create(order=order, status='ZEC_CONFIRMED', at=now, note=f'ZPay confirmed {received} ZEC within allowed slippage.')
        OrderHistory.objects.create(order=order, status=order.status, at=now, note=(
            'Payout processing started after ZEC confirmation.' if order.status == 'PAYOUT_PROCESSING'
            else f'ZPay payment status updated: {order.status.replace("_", " ").lower()}.'
        ))
    elif previous_received != received:
        order.save(update_fields=['receivedAmount', 'updatedAt'])
    return order

@extend_schema(responses={200: OrderSerializer})
@api_view(['GET'])
def get_order(request, orderId):
    try:
        order = Order.objects.get(id=orderId)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        
    order = refresh_zpay_order(order)
    serializer = OrderSerializer(order)
    return Response(serializer.data)

@extend_schema(request=None, responses={200: OrderSerializer})
@api_view(['POST'])
def cancel_order(request, orderId):
    try:
        order = Order.objects.get(id=orderId)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        
    if order.status in ['COMPLETED', 'CANCELLED', 'EXPIRED', 'PAYOUT_FAILED']:
        return Response({'error': 'Order cannot be cancelled in its current state'}, status=status.HTTP_400_BAD_REQUEST)
        
    order.status = 'CANCELLED'
    order.updatedAt = timezone.now()
    order.save()
    
    OrderHistory.objects.create(
        order=order,
        status='CANCELLED',
        note='Cancelled by user.'
    )
    
    serializer = OrderSerializer(order)
    return Response(serializer.data)

@extend_schema(responses={200: PaymentStatusSerializer})
@api_view(['GET', 'POST'])
def check_payment(request, orderId):
    try:
        order = Order.objects.get(id=orderId)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'POST':
        transaction_hash = request.data.get('transactionHash') or request.data.get('hash')
        amount_received = request.data.get('amountReceived') or request.data.get('amount') or request.data.get('receivedAmount')
        confirmations = request.data.get('confirmations', 0)
        block_number = request.data.get('blockNumber')
        payment_address = request.data.get('paymentAddress') or order.paymentAddress

        if not transaction_hash:
            return Response({'error': 'transactionHash is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if amount_received is None:
                raise ValueError('amountReceived is required')
            received_amount = Decimal(str(amount_received))
        except (InvalidOperation, TypeError, ValueError):
            return Response({'error': 'amountReceived must be a valid decimal value'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = process_payment_receipt(
                order,
                transaction_hash=transaction_hash,
                amount_received=received_amount,
                confirmations=int(confirmations),
                block_number=block_number,
                payment_address=payment_address,
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not result['processed']:
            return Response({
                'status': result['status'],
                'processed': False,
                'message': result['message'],
                'expectedAmount': str(result['expectedAmount']),
                'receivedAmount': str(result['receivedAmount']),
                'transactionHash': result['transactionHash'],
            }, status=status.HTTP_200_OK)

        return Response({
            'status': result['status'],
            'processed': True,
            'expectedAmount': str(result['expectedAmount']),
            'receivedAmount': str(result['receivedAmount']),
            'confirmations': result['confirmations'],
            'transactionHash': result['transactionHash'],
            'difference': str(result['difference']),
        }, status=status.HTTP_200_OK)

    return Response({
        'status': order.status,
        'expectedAmount': str(order.expectedAmount or order.zecAmount),
        'receivedAmount': str(order.receivedAmount or 0),
        'confirmations': order.confirmations,
        'transactionHash': order.transactionHash,
    })
