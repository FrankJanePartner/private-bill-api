from rest_framework import serializers
from .models import Order, OrderHistory

class OrderHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderHistory
        fields = ['status', 'at', 'note']

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

    def get_recipient(self, obj):
        return {
            'country': obj.recipientCountry,
            'bank': obj.recipientBank,
            'accountNumber': obj.recipientAccountNumber,
            'accountName': obj.recipientAccountName,
        }
