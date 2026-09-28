from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from .models import Order, OrderHistory


admin.site.site_header = 'ZOERDPay administration'
admin.site.site_title = 'ZOERDPay admin'
admin.site.index_title = 'Payment operations'


class OrderHistoryInline(admin.TabularInline):
    model = OrderHistory
    extra = 0
    can_delete = False
    readonly_fields = ('status', 'at', 'note')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'status', 'currency', 'fiatAmount', 'zecAmount', 'expectedAmount',
        'receivedAmount', 'paymentAddress', 'transactionHash', 'confirmations', 'createdAt', 'completedAt'
    )
    list_filter = ('status', 'currency', 'source')
    search_fields = ('id', 'paymentAddress', 'transactionHash', 'recipientAccountNumber', 'recipientAccountName')
    readonly_fields = (
        'status', 'createdAt', 'updatedAt', 'paymentDetectedAt', 'paymentConfirmedAt', 'completedAt'
    )
    inlines = (OrderHistoryInline,)
    actions = ('mark_payout_completed',)

    @admin.action(description='Mark selected eligible orders as payout complete')
    def mark_payout_completed(self, request, queryset):
        eligible_orders = queryset.filter(status__in=('ZEC_CONFIRMED', 'PAYOUT_PROCESSING', 'FIAT_SENT'))
        completed_count = eligible_orders.count()
        skipped_count = queryset.count() - completed_count
        now = timezone.now()

        with transaction.atomic():
            for order in eligible_orders:
                order.status = 'COMPLETED'
                order.completedAt = now
                order.updatedAt = now
                order.save(update_fields=('status', 'completedAt', 'updatedAt'))
                OrderHistory.objects.create(
                    order=order,
                    status='COMPLETED',
                    note='Payout marked complete by admin.',
                )

        if completed_count:
            self.message_user(
                request,
                f'{completed_count} order(s) marked as payout complete.',
                messages.SUCCESS,
            )
        if skipped_count:
            self.message_user(
                request,
                f'{skipped_count} order(s) were skipped because payment is not confirmed or the order is terminal.',
                messages.WARNING,
            )


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = ('order', 'status', 'at', 'note')
    list_filter = ('status',)
    search_fields = ('order__id', 'note')
