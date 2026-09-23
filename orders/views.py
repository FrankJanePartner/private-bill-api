import uuid
from datetime import timedelta
import requests
from django.db import OperationalError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Order, OrderHistory
from .serializers import (
    CreateOrderRequestSerializer,
    OrderSerializer,
    PaymentStatusSerializer,
    QuoteRequestSerializer,
    QuoteSerializer,
)
from .wallet import WalletUnavailable, generate_wallet

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
    
    order_id = f"PB-{str(uuid.uuid4()).split('-')[0].upper()}-{str(timezone.now().timestamp()).split('.')[0][-4:]}"
    try:
        paymentAddress = generate_wallet(order_id, quote_data.get('zecAmount'))
    except WalletUnavailable:
        # Never create an order with a fake or transparent fallback address.
        return Response(
            {'error': 'Shielded Zcash address allocation is temporarily unavailable. Retry this order.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    
    try:
        with transaction.atomic():
            order = Order.objects.create(
                id=order_id,
                currency=quote_data.get('currency'),
                fiatAmount=quote_data.get('fiatAmount'),
                zecAmount=quote_data.get('zecAmount'),
                rate=quote_data.get('rate'),
                fee=quote_data.get('fee'),
                recipientCountry=recipient_data.get('country'),
                recipientBank=recipient_data.get('bank'),
                recipientAccountNumber=recipient_data.get('accountNumber'),
                recipientAccountName=recipient_data.get('accountName'),
                paymentAddress=paymentAddress,
                status='AWAITING_ZEC'
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
    
    serializer = OrderSerializer(order)
    return Response(serializer.data, status=status.HTTP_201_CREATED)

@extend_schema(responses={200: OrderSerializer})
@api_view(['GET'])
def get_order(request, orderId):
    try:
        order = Order.objects.get(id=orderId)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        
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
@api_view(['GET'])
def check_payment(request, orderId):
    try:
        order = Order.objects.get(id=orderId)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        
    return Response({
        'status': order.status,
        'receivedAmount': 0,
        'confirmations': 0
    })
