<script setup>
import { computed, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../store/appStore'

const router = useRouter()
const { state, calculateQuote, saveBooking, setPaymentOrderId } = useAppStore()

const booking = reactive({ ...state.booking })
const quote = computed(() => calculateQuote(booking))

watch(
  booking,
  (value) => {
    state.booking = { ...state.booking, ...value }
    state.quote = quote.value
  },
  { deep: true },
)

const submit = async () => {
  // Save locally first
  saveBooking(booking)
  setPaymentOrderId(-1)

  // Try to create order on backend (requires backend order API)
  try {
    const res = await fetch(`${import.meta.env.VITE_API_BASE_URL}/order`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ booking }),
    })

    if (res.ok) {
      const payload = await res.json()
      const createdOrder = payload?.order || payload || {}
      const orderId = createdOrder.order_id || createdOrder.id || payload?.order_id || payload?.id
      if (orderId) {
        setPaymentOrderId(String(orderId))
      }

      // backend may return order info; merge it into local booking
      if (payload?.booking || payload?.order) {
        saveBooking(payload.booking || payload.order)
      }

      router.push('/payment')
    } else {
      console.error('Failed to create order:', res.status, res.statusText)
    }
  } catch (e) {
    console.warn('Order creation failed', e)
  }
}
</script>

<template>
  <section class="panel booking-layout">
    <form class="form-grid booking-form" @submit.prevent="submit">
      <h2>Book a Delivery</h2>
      <label>
        Pickup Date
        <input v-model="booking.pickupDate" type="date" required />
      </label>
      <label>
        Pickup Time
        <input v-model="booking.pickupTime" type="time" required />
      </label>
      <label>
        From Location
        <input v-model="booking.fromLocation" type="text" placeholder="Source locker or address" required />
      </label>
      <label>
        To Location
        <input v-model="booking.toLocation" type="text" placeholder="Destination locker or address" required />
      </label>
      <label>
        Package Weight (kg)
        <input v-model.number="booking.packageWeightKg" type="number" min="0.1" max="10" step="0.1" required />
      </label>
      <label>
        Package Size
        <select v-model="booking.packageSize" required>
          <option value="small">Small (up to 20 x 20 x 10 cm)</option>
          <option value="medium">Medium (up to 35 x 25 x 20 cm)</option>
          <option value="large">Large (up to 50 x 40 x 30 cm)</option>
        </select>
      </label>
      <label>
        Recipient Name
        <input v-model="booking.recipientName" type="text" required />
      </label>
      <label>
        Recipient Email
        <input v-model="booking.recipientEmail" type="email" required />
      </label>
      <label>
        Recipient Contact Number
        <input v-model="booking.recipientPhone" type="tel" required />
      </label>
      <label class="wide">
        Special Notes
        <textarea
          v-model="booking.specialNotes"
          rows="3"
          placeholder="Access instructions, building details, or handling instructions"
        />
      </label>
      <label class="checkbox">
        <input v-model="booking.fragile" type="checkbox" />
        Fragile handling required
      </label>
      <label class="checkbox">
        <input v-model="booking.priority" type="checkbox" />
        Priority route (faster but premium)
      </label>
      <button class="btn btn-primary wide" type="submit">Continue to Stripe Payment</button>
    </form>

    <aside class="price-card">
      <h3>Live Price Estimate</h3>
      <dl>
        <div><dt>Base Fare</dt><dd>${{ quote.baseFare.toFixed(2) }}</dd></div>
        <div><dt>Distance</dt><dd>${{ quote.distanceFee.toFixed(2) }}</dd></div>
        <div><dt>Weight</dt><dd>${{ quote.weightFee.toFixed(2) }}</dd></div>
        <div><dt>Fragile Handling</dt><dd>${{ quote.handlingFee.toFixed(2) }}</dd></div>
        <div><dt>Priority</dt><dd>${{ quote.priorityFee.toFixed(2) }}</dd></div>
        <div><dt>Platform Fee</dt><dd>${{ quote.platformFee.toFixed(2) }}</dd></div>
      </dl>
      <p class="factor">Size multiplier: x{{ quote.packageFactor.toFixed(2) }}</p>
      <p class="total">Total: ${{ quote.total.toFixed(2) }}</p>
      <p class="subtle">Price finalization happens on Stripe payment page.</p>
    </aside>
  </section>
</template>
