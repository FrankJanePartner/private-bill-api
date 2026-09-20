import uuid
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Order, OrderHistory
from .serializers import OrderSerializer
from .wallet import generate_wallet

@api_view(['POST'])
def quote(request):
    currency = request.data.get('currency')
    fiatAmount = request.data.get('fiatAmount', 0)
    
    rate = 1000 if currency == 'NGN' else 10
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

@api_view(['POST'])
def create_order(request):
    quote_data = request.data.get('quote', {})
    recipient_data = request.data.get('recipient', {})
    
    order_id = f"PB-{str(uuid.uuid4()).split('-')[0].upper()}-{str(timezone.now().timestamp()).split('.')[0][-4:]}"
    paymentAddress = generate_wallet(order_id)
    
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
    
    serializer = OrderSerializer(order)
    return Response(serializer.data, status=status.HTTP_201_CREATED)

@api_view(['GET'])
def get_order(request, orderId):
    try:
        order = Order.objects.get(id=orderId)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        
    serializer = OrderSerializer(order)
    return Response(serializer.data)

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
