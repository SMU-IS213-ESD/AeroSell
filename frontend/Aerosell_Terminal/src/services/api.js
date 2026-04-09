import { useAppStore } from '../store/appStore'

const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8880').replace(/\/$/, '')

const defaultHeaders = (token) => {
  const h = { 'Content-Type': 'application/json' }
  if (token) h.Authorization = `Bearer ${token}`
  return h
}

export const authFetch = async (path, opts = {}) => {
  const { state } = useAppStore()
  const token = state?.auth?.token || ''
  const url = path.startsWith('http') ? path : `${BASE}${path.startsWith('/') ? '' : '/'}${path}`

  const headers = { ...(opts.headers || {}), ...defaultHeaders(token) }
  const response = await fetch(url, { ...opts, headers })
  return response
}

// Book-Drone Composite Service API
export const bookDroneAPI = {
  // Validate booking data (Phase 1)
  validateBooking: async (bookingData) => {
    const response = await authFetch('/book-drone/validate', {
      method: 'POST',
      body: JSON.stringify(bookingData)
    })
    return response
  },

  // Confirm booking and process payment (Phase 2)
  confirmBooking: async (confirmationData) => {
    const response = await authFetch('/book-drone/confirm', {
      method: 'POST',
      body: JSON.stringify(confirmationData)
    })
    return response
  },

  // Legacy: Create a new booking (all-in-one, deprecated)
  createBooking: async (bookingData) => {
    const response = await authFetch('/book-drone/book', {
      method: 'POST',
      body: JSON.stringify(bookingData)
    })
    return response
  },

  // Get available drones for a timeslot
  getAvailableDrones: async (timeslot) => {
    const response = await authFetch(`/book-drone/available-drones?timeslot=${encodeURIComponent(timeslot)}`)
    return response
  },

  // Validate route and get cost estimate
  validateRoute: async (pickupLocation, dropoffLocation) => {
    const response = await authFetch('/book-drone/validate-route', {
      method: 'POST',
      body: JSON.stringify({
        pickup_location: pickupLocation,
        dropoff_location: dropoffLocation
      })
    })
    return response
  },

  // Get booking by ID
  getBooking: async (bookingId) => {
    const response = await authFetch(`/book-drone/bookings/${bookingId}`)
    return response
  },

  // Get user bookings
  getUserBookings: async (userId) => {
    const response = await authFetch(`/book-drone/bookings/user/${userId}`)
    return response
  },

  // Create payment intent for Stripe Elements
  createPaymentIntent: async (amount, currency = "SGD", orderData = null) => {
    const response = await authFetch("/book-drone/create-payment-intent", {
      method: "POST",
      body: JSON.stringify({ amount, currency, order_data: orderData })
    })
    return response
  },

  // Get payment details by ID
  getPayment: async (paymentId) => {
    const response = await authFetch(`/book-drone/payments/${paymentId}`)
    return response
  }
}

// Flight-Planning Service API (for pickup points)
export const flightPlanningAPI = {
  // Get all pickup points
  getPickupPoints: async () => {
    const response = await authFetch('/flight/routes/pickup-points')
    return response
  },

  // Validate route using pickup point IDs
  validateRouteWithIds: async (orderId, pickupPointId, dropoffPointId) => {
    const response = await authFetch('/flight/routes/validate-by-ids', {
      method: 'POST',
      body: JSON.stringify({
        orderId,
        pickupPointId,
        dropoffPointId
      })
    })
    return response
  }
}

export default {
  authFetch,
  bookDroneAPI,
}
