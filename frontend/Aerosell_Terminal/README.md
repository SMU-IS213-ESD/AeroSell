# AeroSell Terminal

Booking and payment UI for the operator side of AeroSell.
It covers login, booking validation, Stripe checkout, and the final confirmation screen.

## Setup

1. Install dependencies:

```bash
npm install
```

2. Create your environment file:

```bash
cp .env.example .env
```

3. Configure:
- `VITE_API_BASE_URL`: Kong gateway base URL, usually `http://localhost:8880`.
- `VITE_STRIPE_PUBLISHABLE_KEY`: your Stripe publishable key.

4. Run the app:

```bash
npm run dev
```

## Backend Contract

The terminal app talks to the gateway-backed composite services:

- `POST /user/login`
- `POST /user/register`
- `POST /book-drone/validate`
- `POST /book-drone/create-payment-intent`
- `POST /book-drone/confirm`
- `GET /book-drone/payments/:paymentId`
- `GET /flight/routes/pickup-points`
- `POST /flight/routes/validate-by-ids`

The payment intent response used by the payment page should look like this:

```json
{
  "success": true,
  "client_secret": "pi_xxx_secret_xxx",
  "payment_id": 123,
  "transaction_id": "pi_xxx"
}
```

## Auth Guards

Routes for booking, payment, and confirmation require login.
Unauthenticated users are redirected to login and returned to their original route after sign-in.
