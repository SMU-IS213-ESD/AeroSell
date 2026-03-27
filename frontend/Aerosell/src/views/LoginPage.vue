<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '../store/appStore'

const router = useRouter()
const route = useRoute()
const { setUser, setAuth } = useAppStore()

const form = reactive({
  email: '',
  password: '',
})

const loading = ref(false)
const error = ref('')

const submit = async () => {
  error.value = ''
  loading.value = true
  try {
    const res = await fetch(`${import.meta.env.VITE_API_BASE_URL}/user/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: form.email, password: form.password }),
    })

    if (!res.ok) {
      // Try to parse structured JSON error first, fall back to plain text
      let msg = `Request failed: ${res.status}`
      try {
        const payload = await res.json()
        msg = payload?.message || payload?.error || JSON.stringify(payload)
      } catch (e) {
        const txt = await res.text()
        try {
          const parsed = JSON.parse(txt)
          msg = parsed?.message || parsed?.error || txt
        } catch {
          msg = txt || msg
        }
      }
      throw new Error(msg)
    }

    const payload = await res.json()
    const user = payload.user || payload
    const token = payload.token || payload.authToken || ''

    setUser(user)
    if (token) setAuth(token)

    const redirectPath = typeof route.query.redirect === 'string' ? route.query.redirect : '/book'
    router.push(redirectPath)
  } catch (err) {
    const raw = err instanceof Error ? err.message : String(err)
    error.value = `Error: ${raw}`
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="panel small-panel">
    <h2>Login</h2>
    <p class="subtle">Access your AeroSell dashboard and current deliveries.</p>
    <form class="form-grid" @submit.prevent="submit">
      <label>
        Email
        <input v-model="form.email" type="email" required />
      </label>
      <label>
        Password
        <input v-model="form.password" type="password" minlength="6" required />
      </label>
      <button class="btn btn-primary" type="submit" :disabled="loading">
        {{ loading ? 'Signing in...' : 'Login' }}
      </button>
      <p v-if="error" class="warn">{{ error }}</p>
    </form>
  </section>
</template>
