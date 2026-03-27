<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { loadStripe } from '@stripe/stripe-js'
import { useAppStore } from '../store/appStore'
import { createStripePaymentIntent } from '../services/stripeApi'

const router = useRouter()
const { state, completeStripePayment } = useAppStore()

const processing = ref(false)
const paymentMessage = ref('')

const total = computed(() => state.quote?.total ?? 0)
const canPay = computed(() => Boolean(state.quote && state.booking.fromLocation && state.booking.toLocation))
const orderId = computed(() => state.payment?.orderId || '')

const pay = async () => {
  if (!canPay.value) {
    paymentMessage.value = 'Please complete booking details first.'
    return
  }

  if (!orderId.value) {
    paymentMessage.value = 'Order ID is required. Please book a delivery again to create an order first.'
    return
  }

  processing.value = true
  paymentMessage.value = ''

  try {
    const key = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || ''
    if (!key) {
      throw new Error('Missing VITE_STRIPE_PUBLISHABLE_KEY in your environment settings.')
    }

    const stripe = await loadStripe(key)
    if (!stripe) {
      throw new Error('Stripe failed to initialize.')
    }

    const amountCents = Math.round(total.value * 100)
    const customer = {
      email: state.user?.email || state.booking.recipientEmail,
      name: state.user?.name || state.booking.recipientName,
    }
    const { paymentIntentId } = await createStripePaymentIntent({
      order_id: orderId.value,
      amount: amountCents,
      booking: state.booking,
      customer,
    })

    // Stripe Elements/Payment Element is the recommended next step for collecting card details.
    // This demo keeps the custom form and records a successful intent creation as payment completion.
    await new Promise((resolve) => setTimeout(resolve, 500))
    completeStripePayment(paymentIntentId)
    router.push('/confirmation')
  } catch (error) {
    paymentMessage.value = error instanceof Error ? error.message : 'Stripe payment failed. Please try again.'
  } finally {
    processing.value = false
  }
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
