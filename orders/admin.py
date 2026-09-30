from django import forms
from django.contrib import admin
from django.db import transaction
from django.utils import timezone

from .models import Order, OrderHistory


admin.site.site_header = 'ZOERDPay administration'
admin.site.site_title = 'ZOERDPay admin'
admin.site.index_title = 'Payment operations'


ADMIN_STATUS_TRANSITIONS = {
    'UNDERPAID': ('UNDERPAID', 'PAYOUT_PROCESSING'),
    'ZEC_CONFIRMED': ('ZEC_CONFIRMED', 'PAYOUT_PROCESSING'),
    'PAYOUT_PROCESSING': ('PAYOUT_PROCESSING', 'FIAT_SENT'),
    'FIAT_SENT': ('FIAT_SENT', 'COMPLETED'),
    'COMPLETED': ('COMPLETED',),
}


class OrderAdminForm(forms.ModelForm):
    status = forms.ChoiceField(
        choices=(),
        help_text='Advance only after verifying the current payout step. Payment detection and exception statuses are system-controlled.',
    )

    class Meta:
        model = Order
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current_status = self.instance.status or 'AWAITING_ZEC'
        allowed_statuses = ADMIN_STATUS_TRANSITIONS.get(current_status, (current_status,))
        self.fields['status'].choices = [
            (status, status.replace('_', ' ').title())
            for status in allowed_statuses
        ]


class OrderHistoryInline(admin.TabularInline):
    model = OrderHistory
    extra = 0
    can_delete = False
    readonly_fields = ('status', 'at', 'note')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    list_display = (
        'id', 'status', 'currency', 'fiatAmount', 'zecAmount', 'expectedAmount',
        'receivedAmount', 'paymentAddress', 'transactionHash', 'confirmations', 'createdAt', 'completedAt'
    )
    list_filter = ('status', 'currency', 'source')
    search_fields = ('id', 'paymentAddress', 'transactionHash', 'recipientAccountNumber', 'recipientAccountName')
    readonly_fields = (
        'createdAt', 'updatedAt', 'paymentDetectedAt', 'paymentConfirmedAt', 'completedAt'
    )
    inlines = (OrderHistoryInline,)

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = self.get_queryset(request).get(pk=obj.pk).status
        status_changed = previous_status is not None and previous_status != obj.status
        if status_changed:
            now = timezone.now()
            obj.updatedAt = now
            if obj.status == 'COMPLETED':
                obj.completedAt = now

        with transaction.atomic():
            super().save_model(request, obj, form, change)
            if status_changed:
                OrderHistory.objects.create(
                    order=obj,
                    status=obj.status,
                    note=f'Status changed by admin from {previous_status} to {obj.status}.',
                )


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = ('order', 'status', 'at', 'note')
    list_filter = ('status',)
    search_fields = ('order__id', 'note')
