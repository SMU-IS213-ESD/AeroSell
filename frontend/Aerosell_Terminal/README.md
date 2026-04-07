# AeroSell Frontend (Vue + Vite)

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
- `VITE_STRIPE_PUBLISHABLE_KEY`: your Stripe publishable key.
- `VITE_API_BASE_URL`: backend base URL that exposes `POST /payments/create-intent`.

4. Run app:

```bash
npm run dev
```

## Stripe PaymentIntent API contract

Frontend sends:

```json
{
	"amount": 4599,
	"currency": "usd",
	"booking": { "...": "booking fields" },
	"customer": { "email": "user@example.com", "name": "User" }
}
```

Backend should respond with:

```json
{
	"clientSecret": "pi_xxx_secret_xxx",
	"paymentIntentId": "pi_xxx"
}
```

## Auth guards

Routes for booking, payment, confirmation, and status require login.
Unauthenticated users are redirected to login and then returned to their original target route.
