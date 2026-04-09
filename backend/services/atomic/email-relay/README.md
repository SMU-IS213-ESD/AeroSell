# Email Relay Service (Atomic)

Consumes AMQP messages from `notifications` queue and forwards them to an OutSystems HTTP endpoint.

Expected message payload:

```json
{
  "emailAddress": "user@example.com",
  "emailSubject": "Subject",
  "emailBody": "Body text"
}
```

## Environment Variables

- `RABBITMQ_URL` (required)
- `NOTIFICATIONS_QUEUE` (default: `notifications`)
- `OUTSYSTEM_ENDPOINT` (required)
- `OUTSYSTEM_TIMEOUT_SECONDS` (default: `10`)
- `RELAY_MAX_RETRIES` (default: `5`)
- `RELAY_BACKOFF_SECONDS` (default: `2`)
- `RELAY_LOG_PAYLOAD` (default: `false`)


## Run

Create an environment file first:

```bash
cp .env.example .env
```

Then start from the backend root compose (this service does not ship its own compose stack):

```bash
cd backend
docker compose up --build email-relay
```

## Testing

### Prerequisites

Install pika for the test script:

```bash
pip install pika
```

### Publish a test message

To publish a sample notification to the queue:

```bash
# From the backend root directory
python services/atomic/email-relay/tests/publish_test_message.py
```

This will publish a test message with:
- Email: `test@example.com`
- Subject: `Test Notification`
- Body: `This is a test notification message from email-relay test script.`

The email-relay consumer will immediately pick it up (if running) and forward to your OutSystems endpoint.
