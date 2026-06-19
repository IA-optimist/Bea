# Stripe Plugin

Stripe payment integration plugin for Bea - provides payment processing, subscription management, and billing operations.

## Installation

The plugin is automatically registered when Bea starts. Configure the following environment variables:

```bash
STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxxxxxxxxxxx
STRIPE_DEFAULT_CURRENCY=usd
```

## Usage

### Create Payment Intent

```python
from plugins.plugin_registry import get_plugin_registry

registry = get_plugin_registry()
stripe_plugin = registry.get("stripe")

result = await stripe_plugin.invoke(
    "create_payment_intent",
    {
        "amount": 1000,  # Amount in cents
        "currency": "usd",
        "customer_id": "cus_1234567890",
        "metadata": {"order_id": "order_123"}
    },
    {}
)
```

### Confirm Payment

```python
result = await stripe_plugin.invoke(
    "confirm_payment",
    {
        "payment_intent_id": "pi_1234567890",
        "payment_method_id": "pm_1234567890"
    },
    {}
)
```

### Create Customer

```python
result = await stripe_plugin.invoke(
    "create_customer",
    {
        "email": "customer@example.com",
        "name": "John Doe",
        "metadata": {"user_id": "user_123"}
    },
    {}
)
```

### Create Subscription

```python
result = await stripe_plugin.invoke(
    "create_subscription",
    {
        "customer_id": "cus_1234567890",
        "price_id": "price_1234567890",
        "quantity": 1
    },
    {}
)
```

### Cancel Subscription

```python
result = await stripe_plugin.invoke(
    "cancel_subscription",
    {
        "subscription_id": "sub_1234567890",
        "at_period_end": True
    },
    {}
)
```

### Get Invoice

```python
result = await stripe_plugin.invoke(
    "get_invoice",
    {
        "invoice_id": "in_1234567890"
    },
    {}
)
```

## Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `create_payment_intent` | `amount`, `currency`, `customer_id`, `metadata` | Create a payment intent |
| `confirm_payment` | `payment_intent_id`, `payment_method_id` | Confirm a payment |
| `create_customer` | `email`, `name`, `metadata` | Create a customer |
| `create_subscription` | `customer_id`, `price_id`, `quantity` | Create a subscription |
| `cancel_subscription` | `subscription_id`, `at_period_end` | Cancel a subscription |
| `get_invoice` | `invoice_id` | Get invoice details |

## Permissions

The plugin requires the following permissions:
- **Secret**: `STRIPE_SECRET_KEY` - Stripe secret API key
- **Secret**: `STRIPE_PUBLISHABLE_KEY` - Stripe publishable API key
- **Config**: `STRIPE_DEFAULT_CURRENCY` - Default currency for payments

## Risk Level

**High** - This plugin handles financial transactions and payment processing. Ensure proper Stripe API key permissions are configured and implement additional security measures for production use.

## Manifest

```json
{
  "plugin_id": "stripe",
  "name": "Stripe Payment Integration",
  "version": "1.0.0",
  "description": "Stripe payment processing, subscription management, and billing operations",
  "author": "Bea Team",
  "risk_level": "high",
  "required_secrets": ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY"],
  "required_configs": ["STRIPE_DEFAULT_CURRENCY"]
}
```
