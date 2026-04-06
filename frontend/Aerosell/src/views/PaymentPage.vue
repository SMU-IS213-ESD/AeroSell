<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { loadStripe } from '@stripe/stripe-js'
import { useAppStore } from '../store/appStore'
import { bookDroneAPI } from '../services/api'

const router = useRouter()
const { state, completeStripePayment } = useAppStore()
const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || '')

const processing = ref(false)
const paymentMessage = ref('')
const stripe = ref(null)
const elements = ref(null)

// Get validation data from state
const validationData = computed(() => state.validationData || {})
const deliveryCost = computed(() => validationData.value.delivery_cost || 0)
const selectedDrone = computed(() => validationData.value.selected_drone || {})
const canPay = computed(() => Boolean(validationData.value.user_id && validationData.value.delivery_cost))

const pay = async () => {
  if (!canPay.value) {
    paymentMessage.value = 'Validation data is required. Please complete the booking form first.'
    return
  }

  processing.value = true
  paymentMessage.value = ''

  try {
    console.log('Processing payment and confirmation for booking validation')

    // Phase 2: Call confirm endpoint to process payment and create order
    const confirmationData = {
      user_id: validationData.value.user_id,
      drone_id: validationData.value.drone_id,
      pickup_location: validationData.value.pickup_location,
      dropoff_location: validationData.value.dropoff_location,
      timeslot: validationData.value.timeslot,
      delivery_cost: validationData.value.delivery_cost,
      payment_method: 'stripe',
      payment_details: {
        card_holder: cardHolderName.value,
        card_number: cardNumber.value,
        expiry: expiryDate.value,
        cvc: cvc.value
      },
      route_validation: validationData.value.route_validation
    }

    const response = await bookDroneAPI.confirmBooking(confirmationData)

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(errorData.error || `Payment failed: ${response.statusText}`)
    }

    const result = await response.json()
    console.log('Payment and booking confirmation successful:', result)

    if (result.success) {
      // Save confirmation details
      state.payment = {
        complete: true,
        provider: 'stripe',
        orderId: result.order_id || '',
        reference: result.payment_id || '',
        paidAt: new Date().toISOString(),
        bookingId: result.booking_id,
        confirmationData: result
      }

      // Update payment in store
      completeStripePayment(result.payment_id)

      // Navigate to confirmation page
      router.push('/confirmation')
    } else {
      throw new Error(result.error || 'Payment failed')
    }
  } catch (error) {
    console.error('Payment error:', error)
    paymentMessage.value = error instanceof Error ? error.message : 'Payment failed. Please try again.'
  } finally {
    processing.value = false
  }
}

// Payment form fields
const cardHolderName = ref('')
const cardNumber = ref('')
const expiryDate = ref('')
const cvc = ref('')

// Initialize page - verify validation exists
onMounted(() => {
  if (!validationData.value.user_id) {
    paymentMessage.value = 'No booking validation found. Please complete your booking first.'
  }
})
</script>

<template>
  <section class="panel payment-panel">
    <div>
      <h2>Payment</h2>
      <div class="payment-form">
        <label>
          Cardholder Name
          <input v-model="cardHolderName" type="text" placeholder="John Doe" required />
        </label>
        <label>
          Card Number
          <input v-model="cardNumber" type="text" placeholder="4242 4242 4242 4242" required />
        </label>
        <div class="inline-fields">
          <label>
            Expiration (MM/YY)
            <input v-model="expiryDate" type="text" placeholder="12/25" required />
          </label>
          <label>
            CVC
            <input v-model="cvc" type="text" placeholder="123" required />
          </label>
        </div>
      </div>
      <button class="btn btn-primary wide" :disabled="processing || !canPay" @click="pay">
        {{ processing ? 'Processing...' : `Pay $${deliveryCost.toFixed(2)}` }}
      </button>
      <p v-if="paymentMessage" class="warn">{{ paymentMessage }}</p>
    </div>

    <aside class="price-card">
      <h3>Booking Summary</h3>
      <div class="detail-row">
        <p><strong>From:</strong></p>
        <p>{{ state.booking.fromLocation || 'N/A' }}</p>
      </div>
      <div class="detail-row">
        <p><strong>To:</strong></p>
        <p>{{ state.booking.toLocation || 'N/A' }}</p>
      </div>
      <div class="detail-row">
        <p><strong>Date:</strong></p>
        <p>{{ state.booking.pickupDate }} at {{ state.booking.pickupTime }}</p>
      </div>
      <div class="detail-row">
        <p><strong>Drone:</strong></p>
        <p>Drone {{ selectedDrone.id || 'N/A' }}</p>
      </div>
      <div class="detail-row">
        <p><strong>Weight:</strong></p>
        <p>{{ state.booking.packageWeightKg }} kg</p>
      </div>
      <div class="detail-row">
        <p><strong>Size:</strong></p>
        <p>{{ state.booking.packageSize }}</p>
      </div>
      <p class="total">Total: ${{ deliveryCost.toFixed(2) }}</p>
      <p class="subtle">Payment processed via Stripe</p>
    </aside>
  </section>
</template>

<style scoped>
.detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.info {
  color: #666;
  margin-bottom: 1rem;
}

.payment-form label {
  display: block;
  margin-bottom: 1rem;
}

.payment-form input {
  width: 100%;
  padding: 0.5rem;
  margin-top: 0.25rem;
  border: 1px solid #ccc;
  border-radius: 4px;
}

.inline-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.total {
  font-weight: bold;
  font-size: 1.2rem;
  margin-top: 1rem;
  border-top: 2px solid #eee;
  padding-top: 1rem;
}

.subtle {
  color: #666;
  font-size: 0.9rem;
  margin-top: 1rem;
}

.warn {
  color: #e53e3e;
  margin-top: 0.5rem;
}

.wide {
  width: 100%;
}
</style>