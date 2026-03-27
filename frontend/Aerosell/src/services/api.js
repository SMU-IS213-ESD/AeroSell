import { useAppStore } from '../store/appStore'

const BASE = (import.meta.env.VITE_API_BASE_URL).replace(/\/$/, '')

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

export default {
  authFetch,
}
