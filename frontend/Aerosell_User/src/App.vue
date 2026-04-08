<script setup>
import { useRouter } from 'vue-router'
import { useAppStore } from './store/appStore'

const router = useRouter()
const { state, setUser, setAuth } = useAppStore()

const logout = () => {
  setUser(null)
  setAuth('')
  router.push('/')
}
</script>

<template>
  <div class="site-frame">
    <header class="topbar">
      <RouterLink class="brand" to="/">
        <span class="brand-mark">AS</span>
        <span>
          <strong>AeroSell</strong>
          <small>P2P Drone Delivery</small>
        </span>
      </RouterLink>
      <nav class="nav">
        <RouterLink to="/">Home</RouterLink>
        <RouterLink v-if="state.user" to="/status">Status</RouterLink>
        <RouterLink v-if="!state.user" to="/login">Login</RouterLink>
        <button v-if="state.user" type="button" class="nav-logout" @click="logout">Logout</button>
      </nav>

    </header>

    <main class="page-shell">
      <RouterView />
    </main>
  </div>
</template>
