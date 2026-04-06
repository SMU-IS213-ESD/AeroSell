<script setup>
import { computed, reactive, watch, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../store/appStore'
import { bookDroneAPI, flightPlanningAPI } from '../services/api'

const router = useRouter()
const { state, calculateQuote, saveBooking, setUser } = useAppStore()

const booking = reactive({ ...state.booking })
const quote = computed(() => calculateQuote(booking))
const isSubmitting = ref(false)
const errorMessage = ref('')
const isLoadingPickupPoints = ref(true)

const pickupPoints = ref([])

// Internal state for selected pickup points with their coordinates
const selectedPoints = reactive({
  fromPoint: null,
  toPoint: null
})

watch(
  booking,
  (value) => {
    state.booking = { ...state.booking, ...value }
    state.quote = quote.value
  },
  { deep: true },
)

// Fetch pickup points from API
const fetchPickupPoints = async () => {
  isLoadingPickupPoints.value = true
  try {
    const response = await flightPlanningAPI.getPickupPoints()
    if (response.ok) {
      pickupPoints.value = await response.json()
      // If booking already has locations, find matching points
      if (booking.fromLocation) {
        const fromPoint = pickupPoints.value.find(p => p.name === booking.fromLocation)
        if (fromPoint) selectedPoints.fromPoint = fromPoint
      }
      if (booking.toLocation) {
        const toPoint = pickupPoints.value.find(p => p.name === booking.toLocation)
        if (toPoint) selectedPoints.toPoint = toPoint
      }
    } else {
      console.error('Failed to fetch pickup points')
    }
  } catch (error) {
    console.error('Error fetching pickup points:', error)
  } finally {
    isLoadingPickupPoints.value = false
  }
}

// Handle pickup point selection
const handleFromLocationChange = (event) => {
  const pointId = parseInt(event.target.value)
  const point = pointId ? pickupPoints.value.find(p => p.id === pointId) : null
  selectedPoints.fromPoint = point
  if (point) {
    booking.fromLocation = point.name
  } else {
    booking.fromLocation = ''
  }
}

const handleToLocationChange = (event) => {
  const pointId = parseInt(event.target.value)
  const point = pointId ? pickupPoints.value.find(p => p.id === pointId) : null
  selectedPoints.toPoint = point
  if (point) {
    booking.toLocation = point.name
  } else {
    booking.toLocation = ''
  }
}

// Load pickup points on component mount
onMounted(() => {
  fetchPickupPoints()
})

const submit = async () => {
  isSubmitting.value = true
  errorMessage.value = ''

  try {
    // Validate that pickup points are selected
    if (!selectedPoints.fromPoint || !selectedPoints.toPoint) {
      errorMessage.value = 'Please select valid From and To locations'
      isSubmitting.value = false
      return
    }

    // Save locally first
    saveBooking(booking)

    // Combine date and time into ISO timestamp
    const pickupDateTime = new Date(`${booking.pickupDate}T${booking.pickupTime}`)
    const timeslot = pickupDateTime.toISOString()

    // Prepare booking data for book-drone composite service
    const bookingData = {
      user_id: state.user?.id || 1, // Use logged-in user ID or default
      pickup_location: booking.fromLocation,
      dropoff_location: booking.toLocation,
      pickup_coordinates: {
        lat: selectedPoints.fromPoint.latitude,
        lon: selectedPoints.fromPoint.longitude
      },
      dropoff_coordinates: {
        lat: selectedPoints.toPoint.latitude,
        lon: selectedPoints.toPoint.longitude
      },
      pickup_point_id: selectedPoints.fromPoint.id,
      dropoff_point_id: selectedPoints.toPoint.id,
      timeslot: timeslot,
      payment_method: 'stripe',
      package_details: {
        weight_kg: booking.packageWeightKg,
        size: booking.packageSize,
        fragile: booking.fragile,
        priority: booking.priority
      }
    }

    console.log('Submitting booking to book-drone service:', bookingData)

    // Call book-drone composite service
    const response = await bookDroneAPI.createBooking(bookingData)

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(errorData.error || `Booking failed: ${response.statusText}`)
    }

    const result = await response.json()
    console.log('Booking successful:', result)

    // Save booking and payment details to state
    if (result.success) {
      state.payment = {
        complete: false, // Will be completed on payment page
        provider: 'stripe',
        orderId: result.order_id || '',
        reference: result.payment_id || '',
        paidAt: '',
        bookingId: result.booking_id
      }

      // Navigate to payment page
      router.push('/payment')
    } else {
      throw new Error(result.error || 'Booking failed')
    }
  } catch (error) {
    console.error('Booking error:', error)
    errorMessage.value = error.message || 'Failed to create booking. Please try again.'
  } finally {
    isSubmitting.value = false
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
<select
:disabled="isLoadingPickupPoints"
@change="handleFromLocationChange"
:value="selectedPoints.fromPoint?.id || ''"
required
>
<option value="" disabled>
{{ isLoadingPickupPoints ? 'Loading pickup points...' : 'Select source location' }}
</option>
<option
v-for="point in pickupPoints"
:key="point.id"
:value="point.id"
>
{{ point.name }}
</option>
</select>
</label>
<label>
To Location
<select
:disabled="isLoadingPickupPoints"
@change="handleToLocationChange"
:value="selectedPoints.toPoint?.id || ''"
required
>
<option value="" disabled>
{{ isLoadingPickupPoints ? 'Loading pickup points...' : 'Select destination location' }}
</option>
<option
v-for="point in pickupPoints"
:key="point.id"
:value="point.id"
>
{{ point.name }}
</option>
</select>
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
