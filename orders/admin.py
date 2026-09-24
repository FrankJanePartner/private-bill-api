from django.contrib import admin

from .models import Order, OrderHistory


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'status', 'currency', 'fiatAmount', 'zecAmount', 'expectedAmount',
        'receivedAmount', 'paymentAddress', 'transactionHash', 'confirmations', 'createdAt'
    )
    list_filter = ('status', 'currency', 'source')
    search_fields = ('id', 'paymentAddress', 'transactionHash', 'recipientAccountNumber', 'recipientAccountName')
    readonly_fields = (
        'createdAt', 'updatedAt', 'paymentDetectedAt', 'paymentConfirmedAt', 'completedAt'
    )


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = ('order', 'status', 'at', 'note')
    list_filter = ('status',)
    search_fields = ('order__id', 'note')
