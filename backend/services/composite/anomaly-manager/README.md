# Anomaly Manager - Composite Service

Orchestrates the complete drone anomaly recovery workflow.

## Responsibilities

1. **Consumes Drone Anomalies**: Listens to `drone.anomaly` messages from RabbitMQ
2. **Orchestrates Recovery**:
   - Fetches affected orders from Order Service
   - Fetches available support staff from Operations-Support Service
   - Assigns staff to repair the drone
   - Updates order statuses to "DELAYED"
3. **Publishes Notifications**:
   - Staff notifications for repair assignments
   - Customer notifications for delivery delays
4. **Handles Retries**:
   - NACK messages on failure for Dead Letter Exchange (DLX) retry logic
   - 30-second delay before retry through RabbitMQ

## Workflow

```
Drone Anomaly (error=true)
    ↓
[Anomaly Manager]
    ↓
1. Get orders for drone (Order Service)
2. Get available staff (Operations-Support Service)
3. Assign staff → Create assignment
4. Update orders → Status: DELAYED
5. Publish notifications → Staff & Customer
    ↓
[END] or [DLX Retry if failed]
```

## Environment Variables

- `RABBITMQ_URL`: RabbitMQ connection URL (default: `amqp://admin:58nczhxy@localhost:5672/`)
- `ORDER_SERVICE_URL`: Order Service endpoint (default: `http://order:5000`)
- `SUPPORT_SERVICE_URL`: Operations-Support Service endpoint (default: `http://operations-support:5000`)

## AMQP Configuration

**Exchanges:**
- `drone_anomaly` (topic): Source of drone anomaly messages
- `notification_exchange` (topic): Publishes staff and customer notifications for external consumption

**Queues:**
- `anomaly_recovery_queue`: Consumer queue (binds to `drone_anomaly` with `drone.anomaly` routing key)

## Notifications

Notifications are published to `notification_exchange` and are intended for consumption by external services (e.g., OutSystems).

**Staff Notifications** (routing_key: `notification.staff`):
```json
{
  "staff_id": "UUID",
  "drone_id": 1,
  "location": {"latitude": 37.7749, "longitude": -122.4194},
  "timestamp": "2026-04-08T07:38:14",
  "type": "drone_repair_assignment"
}
```

**Customer Notifications** (routing_key: `notification.customer`):
```json
{
  "user_id": "UUID",
  "order_id": "UUID",
  "message": "Your delivery has been delayed due to drone maintenance...",
  "timestamp": "2026-04-08T07:38:14",
  "type": "delivery_delay"
}
```

**Retry Logic:**
- Dead Letter Exchange: `repair_dlx`
- Retry Queue: `repair_queue` (30s TTL, requeued to `repair_dlx`)
