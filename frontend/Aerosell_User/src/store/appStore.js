import { reactive, watch } from 'vue'

const STORAGE_KEY = 'aerosell-store-v1'

const makeDefaultState = () => ({
  user: null,
  auth: {
    token: '',
  },
  booking: {
    pickupDate: '',
    pickupTime: '',
    fromLocation: '',
    toLocation: '',
    distanceKm: 8,
    packageWeightKg: 1,
    packageSize: 'medium',
    fragile: false,
    priority: false,
    recipientName: '',
    recipientEmail: '',
    recipientPhone: '',
    specialNotes: '',
  },
  quote: null,
  payment: {
    complete: false,
    provider: 'stripe',
    orderId: '',
    reference: '',
    paidAt: '',
  },
  orders: [],
  delivery: {
    ownerEmail: '',
    trackingCode: '',
    pickupPin: '',
    status: 'not_started',
    milestones: [],
  },
  validationData: null, // Temporary data for validation between booking and payment
})

const cloneState = (value) => JSON.parse(JSON.stringify(value))

const loadState = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return makeDefaultState()
    }

    const parsed = JSON.parse(raw)
    return {
      ...makeDefaultState(),
      ...parsed,
      booking: {
        ...makeDefaultState().booking,
        ...(parsed.booking || {}),
      },
      payment: {
        ...makeDefaultState().payment,
        ...(parsed.payment || {}),
      },
      orders: Array.isArray(parsed.orders) ? parsed.orders : [],
      delivery: {
        ...makeDefaultState().delivery,
        ...(parsed.delivery || {}),
      },
      validationData: parsed.validationData || null, // Persist and restore validationData
    }
  } catch {
    return makeDefaultState()
  }
}

const state = reactive(loadState())
let watching = false

const sizeMultiplier = {
  small: 1,
  medium: 1.22,
  large: 1.48,
}

const statusTemplate = [
  {
    key: 'scheduled',
    label: 'Scheduled',
    details: 'Delivery slot reserved and pickup locker prepared.',
  },
  {
    key: 'picked_up',
    label: 'Picked Up',
    details: 'Package collected from source locker.',
  },
  {
    key: 'in_flight',
    label: 'In Flight',
    details: 'Drone is en route to destination hub.',
  },
  {
    key: 'delivered',
    label: 'Delivered',
    details: 'Recipient confirmed package retrieval.',
  },
]

const statusTargets = {
  scheduled: 1,
  picked_up: 2,
  in_flight: 3,
  delivered: 4,
}

const initPersistence = () => {
  if (watching) return
  watch(
    state,
    () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(cloneState(state)))
    },
    { deep: true },
  )
  watching = true
}

const calculateQuote = (booking) => {
  const baseFare = 12
  const distanceFee = Number(booking.distanceKm || 0) * 0.95
  const weightFee = Number(booking.packageWeightKg || 0) * 2.1
  const packageFactor = sizeMultiplier[booking.packageSize] || sizeMultiplier.medium
  const handlingFee = booking.fragile ? 8 : 0
  const priorityFee = booking.priority ? 15 : 0

  const subtotal = (baseFare + distanceFee + weightFee + handlingFee + priorityFee) * packageFactor
  const platformFee = subtotal * 0.06
  const total = subtotal + platformFee

  return {
    baseFare,
    distanceFee,
    weightFee,
    packageFactor,
    handlingFee,
    priorityFee,
    platformFee,
    total: Number(total.toFixed(2)),
  }
}

const formatTrackingCode = (bookingId) => {
  // Format booking ID as AS-0001, AS-0002, etc.
  const paddedId = String(bookingId).padStart(4, '0')
  return `AS-${paddedId}`
}

const cloneMilestones = (milestones) => milestones.map((item) => ({ ...item }))

export const useAppStore = () => {
  initPersistence()

  const setUser = (user) => {
    state.user = user
  }

  const saveBooking = (booking) => {
    state.booking = { ...state.booking, ...booking }
    state.quote = calculateQuote(state.booking)
    state.payment = {
      complete: false,
      provider: 'stripe',
      orderId: '',
      reference: '',
      paidAt: '',
    }
    state.delivery = {
      ownerEmail: '',
      trackingCode: '',
      pickupPin: '',
      status: 'not_started',
      milestones: [],
    }
  }

  const completeStripePayment = (paymentReference = '', backendPickupPin = null) => {
    const now = new Date().toISOString()
    const milestones = statusTemplate.map((item, index) => ({
      ...item,
      reachedAt: index === 0 ? now : '',
      complete: index === 0,
    }))

    state.payment = {
      complete: true,
      provider: 'stripe',
      orderId: state.payment.orderId || '',
      reference: paymentReference || `pi_demo_${Date.now()}`,
      paidAt: now,
    }

    const deliveryRecord = {
      ownerEmail: state.user?.email || state.booking.recipientEmail || '',
      trackingCode: formatTrackingCode(paymentReference || '1'),
      pickupPin: backendPickupPin,
      status: 'scheduled',
      milestones,
    }

    state.delivery = deliveryRecord
    state.orders = [
      {
        trackingCode: deliveryRecord.trackingCode,
        ownerEmail: deliveryRecord.ownerEmail,
        fromLocation: state.booking.fromLocation,
        toLocation: state.booking.toLocation,
        pickupDate: state.booking.pickupDate,
        pickupTime: state.booking.pickupTime,
        pickupPin: deliveryRecord.pickupPin,
        status: deliveryRecord.status,
        milestones: cloneMilestones(deliveryRecord.milestones),
        createdAt: now,
      },
      ...state.orders,
    ]
  }

  const fetchUserOrders = async (userId) => {
    try {
      const res = await fetch(
        `${import.meta.env.VITE_BOOK_DRONE_API_URL || 'http://localhost:8880'}/book-drone/status`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_id: userId })
        }
      )

      if (!res.ok) {
        const errorData = await res.json()
        throw new Error(`Failed to fetch orders: ${errorData.message || res.status}`)
      }

      const result = await res.json()
      console.log('Fetched orders:', result)
      if (result.success && result.data.orders) {
        state.orders = result.data.orders.map((order) => ({
          trackingCode: `AS-${String(order.order_id).padStart(4, '0')}`,
          userId: order.user_id,
          pickupPin: order.pickup_pin,
          fromLocation: order.pickup_location || 'Unknown',
          toLocation: order.dropoff_location || 'Unknown',
          status: order.status.toLowerCase(),
          createdAt: order.created,
          milestones: (Array.isArray(order.milestones) && order.milestones.length)
            ? order.milestones.map((m) => {
                const template = statusTemplate.find((t) => t.key === m.key) || {}
                return {
                  key: m.key,
                  label: m.label || template.label || '',
                  details: m.details || template.details || '',
                  complete: !!m.complete,
                  reachedAt: m.reachedAt || '',
                }
              })
            : statusTemplate.map((item, index) => {
                const targetStatusIndex = statusTargets[order.status?.toLowerCase()]
                const isCompleted = index <= (targetStatusIndex === undefined ? -1 : targetStatusIndex - 1)
                if (item.key === order.status?.toLowerCase()) {
                  return {
                    ...item,
                    complete: true,
                    reachedAt: order.created,
                    details: item.details + ` (${order.status})`,
                  }
                }
                return {
                  ...item,
                  complete: isCompleted,
                  reachedAt: isCompleted ? order.created : '',
                }
              })
        }))
      }
    } catch (error) {
      console.error('Error fetching orders:', error)
      state.orders = []
    }
  }

  const advanceStatus = (trackingCode = state.delivery.trackingCode) => {
    const order = ['scheduled', 'picked_up', 'in_flight', 'delivered']
    const target = state.orders.find((item) => item.trackingCode === trackingCode)
    if (!target) return

    const currentIndex = order.findIndex((item) => item === target.status)
    if (currentIndex < 0 || currentIndex === order.length - 1) return

    const nextStatus = order[currentIndex + 1]
    const nextMilestones = target.milestones.map((item) => {
      if (item.key === nextStatus) {
        return { ...item, complete: true, reachedAt: new Date().toISOString() }
      }
      return item
    })

    target.status = nextStatus
    target.milestones = nextMilestones

    if (state.delivery.trackingCode === trackingCode) {
      state.delivery.status = nextStatus
      state.delivery.milestones = cloneMilestones(nextMilestones)
    }
  }

  return {
    state,
    statusTemplate,
    calculateQuote,
    setUser,
    setAuth: (token) => {
      state.auth.token = token
    },
    setPaymentOrderId: (orderId) => {
      state.payment.orderId = orderId || ''
    },
    saveBooking,
    completeStripePayment,
    advanceStatus,
    fetchUserOrders,
  }
}
