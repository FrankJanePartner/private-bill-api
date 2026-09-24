from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0002_expand_payment_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="expectedAmount",
            field=models.DecimalField(decimal_places=8, default=Decimal("0.00000000"), max_digits=18),
        ),
        migrations.AddField(
            model_name="order",
            name="receivedAmount",
            field=models.DecimalField(decimal_places=8, default=Decimal("0.00000000"), max_digits=18),
        ),
        migrations.AddField(
            model_name="order",
            name="transactionHash",
            field=models.CharField(blank=True, max_length=255, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="order",
            name="blockNumber",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="confirmations",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="order",
            name="paymentDetectedAt",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="paymentConfirmedAt",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="completedAt",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
