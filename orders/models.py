from django.db import models
from django.utils import timezone

class Order(models.Model):
    id = models.CharField(max_length=50, primary_key=True)
    currency = models.CharField(max_length=10)
    fiatAmount = models.FloatField()
    zecAmount = models.FloatField()
    rate = models.FloatField()
    fee = models.FloatField()
    recipientCountry = models.CharField(max_length=10)
    recipientBank = models.CharField(max_length=100)
    recipientAccountNumber = models.CharField(max_length=50)
    recipientAccountName = models.CharField(max_length=100)
    # Mainnet Unified Addresses are much longer than transparent addresses.
    paymentAddress = models.CharField(max_length=1024)
    status = models.CharField(max_length=50, default='AWAITING_ZEC')
    createdAt = models.DateTimeField(default=timezone.now)
    updatedAt = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=20, default='backend')

    def __str__(self):
        return self.id

class OrderHistory(models.Model):
    order = models.ForeignKey(Order, related_name='statusHistory', on_delete=models.CASCADE)
    status = models.CharField(max_length=50)
    at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255)

    class Meta:
        ordering = ['at']
