"""ZPay address allocation client.

Private Bill never creates Zcash addresses itself.  It asks ZPay to allocate an
address for each order, and ZPay's Rust wallet service derives the actual
Unified Address from the merchant wallet.  This keeps all wallet keys out of
Private Bill.
"""

import os
from decimal import Decimal, InvalidOperation, ROUND_DOWN

import requests


class WalletUnavailable(Exception):
    """ZPay cannot currently allocate a safe receiving address."""


ZATOSHIS_PER_ZEC = Decimal("100000000")


def _amount_to_zatoshis(zec_amount) -> str:
    """Convert a positive ZEC amount to an exact integer zatoshi string."""
    try:
        value = Decimal(str(zec_amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WalletUnavailable("Order has an invalid ZEC amount") from exc

    zatoshis = (value * ZATOSHIS_PER_ZEC).to_integral_value(rounding=ROUND_DOWN)
    if value <= 0 or zatoshis <= 0:
        raise WalletUnavailable("Order ZEC amount must be positive")
    return str(zatoshis)


def generate_wallet(order_id: str, zec_amount) -> str:
    """Allocate a real mainnet Unified Address through the ZPay API.

    Required environment variables:
    - ZPAY_API_BASE_URL, for example https://api.zpay.example
    - ZPAY_API_KEY, a ZPay merchant API key (kept server-side only)

    The order ID is used as the Idempotency-Key, so a retry cannot allocate a
    different address for the same order.
    """
    api_base_url = os.environ.get("ZPAY_API_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("ZPAY_API_KEY", "")
    if not api_base_url or not api_key:
        raise WalletUnavailable("ZPay is not configured")

    try:
        response = requests.post(
            f"{api_base_url}/api/v1/payment-requests/",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Idempotency-Key": order_id,
                "Content-Type": "application/json",
            },
            json={
                "reference": order_id,
                "amount_zatoshis": _amount_to_zatoshis(zec_amount),
                "ttl_seconds": 1800,
            },
            timeout=20,
        )
        response.raise_for_status()
        address = response.json().get("address")
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise WalletUnavailable("ZPay address allocation failed") from exc

    # A ZPay receiving address for this integration must be a mainnet Unified
    # Address. Transparent addresses begin with t1/t3 and are never accepted.
    if not isinstance(address, str) or not address.startswith("u1"):
        raise WalletUnavailable("ZPay did not return a shielded Unified Address")
    return address
