import api from './api'

const parseErrorPayload = async (response) => {
  try {
    const payload = await response.json()
    return payload?.message || payload?.error || `Request failed (${response.status})`
  } catch {
    return `Request failed (${response.status})`
  }
}

export const createStripePaymentIntent = async ({ order_id, amount, booking, customer }) => {
  const response = await api.authFetch('/payment', {
    method: 'POST',
    body: JSON.stringify({ order_id, amount, currency: 'usd', booking, customer }),
  })

  if (!response.ok) {
    throw new Error(await parseErrorPayload(response))
  }

  const data = await response.json()
  if (!data?.clientSecret || !data?.paymentIntentId) {
    throw new Error('Backend response is missing clientSecret or paymentIntentId.')
  }

  return {
    clientSecret: data.clientSecret,
    paymentIntentId: data.paymentIntentId,
  }
}
