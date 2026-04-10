# AeroSell User

Customer-facing UI for AeroSell.
It handles account access, delivery status tracking, and insurance claim submission.

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

4. Run the app:

```bash
npm run dev
```

## Backend Contract

The user app uses these backend routes:

- `POST /user/login`
- `POST /user/register`
- `POST /insurance-claim/submit`
- `GET /insurance-claim/claims/:claimId`
- `GET /insurance-claim/user/:userId`

The claim form submits multipart form data with `user_id`, `order_id`, `description`, and `file`.

## Auth Guards

Routes for delivery status and insurance claim submission require login.
Unauthenticated users are redirected to login and then returned to their original target route.
