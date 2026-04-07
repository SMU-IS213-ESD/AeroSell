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
  validationData: null,  // Temporary data for validation between booking and payment
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
      validationData: parsed.validationData || null,  // Persist and restore validationData
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

const randomEightDigitPin = () => Math.floor(10000000 + Math.random() * 90000000).toString()

const randomTrackingCode = () => {
  const stamp = Date.now().toString().slice(-6)
  const rand = Math.floor(Math.random() * 900 + 100)
  return `AS-${stamp}-${rand}`
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
      trackingCode: randomTrackingCode(),
      pickupPin: backendPickupPin || randomEightDigitPin(),
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
        status: deliveryRecord.status,
        milestones: cloneMilestones(deliveryRecord.milestones),
        createdAt: now,
      },
      ...state.orders,
    ]
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
  }
}
