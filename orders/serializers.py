from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .models import Order, OrderHistory

class OrderHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderHistory
        fields = ['status', 'at', 'note']

class RecipientSerializer(serializers.Serializer):
    country = serializers.ChoiceField(choices=['NG', 'GH'])
    bank = serializers.CharField()
    accountNumber = serializers.CharField()
    accountName = serializers.CharField()

class OrderSerializer(serializers.ModelSerializer):
    statusHistory = OrderHistorySerializer(many=True, read_only=True)
    recipient = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'currency', 'fiatAmount', 'zecAmount', 'rate', 'fee',
            'recipient', 'paymentAddress', 'status', 'createdAt', 
            'updatedAt', 'statusHistory', 'source'
        ]

    @extend_schema_field(RecipientSerializer)
    def get_recipient(self, obj):
        return {
            'country': obj.recipientCountry,
            'bank': obj.recipientBank,
            'accountNumber': obj.recipientAccountNumber,
            'accountName': obj.recipientAccountName,
        }

class QuoteRequestSerializer(serializers.Serializer):
    currency = serializers.ChoiceField(choices=['NGN', 'GHS'])
    fiatAmount = serializers.FloatField()

class QuoteSerializer(serializers.Serializer):
    currency = serializers.ChoiceField(choices=['NGN', 'GHS'])
    fiatAmount = serializers.FloatField()
    zecAmount = serializers.FloatField()
    rate = serializers.FloatField()
    fee = serializers.FloatField()
    expiresAt = serializers.CharField()
    source = serializers.ChoiceField(choices=['backend', 'live'])

class CreateOrderRequestSerializer(serializers.Serializer):
    quote = QuoteSerializer()
    recipient = RecipientSerializer()

class PaymentStatusSerializer(serializers.Serializer):
    status = serializers.CharField()
    receivedAmount = serializers.FloatField()
    confirmations = serializers.IntegerField()
