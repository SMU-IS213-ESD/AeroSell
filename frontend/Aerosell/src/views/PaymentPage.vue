<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { loadStripe } from '@stripe/stripe-js'
import { useAppStore } from '../store/appStore'
import { createStripePaymentIntent } from '../services/stripeApi'
import { bookDroneAPI } from '../services/api'

const router = useRouter()
const { state, completeStripePayment } = useAppStore()

const processing = ref(false)
const paymentMessage = ref('')

const total = computed(() => state.quote?.total ?? 0)
const canPay = computed(() => Boolean(state.quote && state.payment?.orderId && state.payment?.bookingId))
const bookingId = computed(() => state.payment?.bookingId || '')

const pay = async () => {
  if (!canPay.value) {
    paymentMessage.value = 'Booking information is required. Please complete the booking form first.'
    return
  }

  processing.value = true
  paymentMessage.value = ''

  try {
    // For demonstration with book-drone composite service, we'll simulate the payment
    // In a real implementation, you'd integrate Stripe payment element here
    const key = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || ''
    if (!key) {
      throw new Error('Missing VITE_STRIPE_PUBLISHABLE_KEY in environment settings.')
    }

    console.log('Processing payment for booking:', bookingId.value)

    // The book-drone composite service has already handled payment processing
    // This step would integrate with Stripe Elements in a real implementation
    const stripe = await loadStripe(key)
    if (!stripe) {
      throw new Error('Stripe failed to initialize.')
    }

    // Simulate payment completion (in real app, use Stripe Elements)
    await new Promise((resolve) => setTimeout(resolve, 2000))

    // Update payment status as complete
    completeStripePayment(state.payment.reference)

    // Navigate to confirmation page
    router.push('/confirmation')
  } catch (error) {
    console.error('Payment error:', error)
    paymentMessage.value = error instanceof Error ? error.message : 'Payment failed. Please try again.'
  } finally {
    processing.value = false
  }
}

// Initialize page - verify booking exists
if (!state.payment?.bookingId) {
  paymentMessage.value = 'No booking found. Please complete your booking first.'
}
</script>

<template>
  <section class="panel payment-panel">
    <div>
      <h2>Stripe Payment</h2>
      <div class="stripe-card">
        <label>
          Cardholder Name
          <input type="text" placeholder="Name on card" required />
        </label>
        <label>
          Card Number
          <input type="text" placeholder="4242 4242 4242 4242" required />
        </label>
        <div class="inline-fields">
          <label>
            Expiration
            <input type="text" placeholder="MM / YY" required />
          </label>
          <label>
            CVC
            <input type="text" placeholder="123" required />
          </label>
        </div>
      </div>
      <button class="btn btn-primary" :disabled="processing" @click="pay">
        {{ processing ? 'Processing...' : `Pay with Stripe - $${total.toFixed(2)}` }}
      </button>
      <p v-if="paymentMessage" class="warn">{{ paymentMessage }}</p>
    </div>

    <aside class="price-card">
      <h3>Order Summary</h3>
      <p><strong>From:</strong> {{ state.booking.fromLocation }}</p>
      <p><strong>To:</strong> {{ state.booking.toLocation }}</p>
      <p><strong>Date:</strong> {{ state.booking.pickupDate }} at {{ state.booking.pickupTime }}</p>
      <p><strong>Weight:</strong> {{ state.booking.packageWeightKg }} kg</p>
      <p><strong>Size:</strong> {{ state.booking.packageSize }}</p>
      <p class="total">Charge: ${{ total.toFixed(2) }}</p>
    </aside>
  </section>
</template>
