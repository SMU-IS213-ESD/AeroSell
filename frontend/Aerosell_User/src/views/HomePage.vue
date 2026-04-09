<script setup>
import { computed } from 'vue'
import { useAppStore } from '../store/appStore'

const { state } = useAppStore()

const userDisplayName = computed(() => {
  if (!state.user) return ''
  return state.user.name || state.user.fullName || state.user.username || state.user.email
})
</script>

<template>
  <section class="hero-shell">
    <div class="hero-card">
      <p class="eyebrow">Peer-to-Peer Drone Logistics</p>
      <h1>Deliver citywide in minutes with AeroSell.</h1>
      <p class="lede">
        Book same-day drone pickup between secure lockers, track every leg in real time,
        and verify release with a one-time PIN.
      </p>
      <div class="cta-row">
        <RouterLink class="btn btn-ghost" to="/status">Track Parcel</RouterLink>
      </div>
      <p v-if="state.user" class="signed-in">Signed in as {{ userDisplayName }}</p>
    </div>
    <div class="hero-metrics">
      <div>
        <span>Average Pickup Time</span>
        <strong>6 min</strong>
      </div>
      <div>
        <span>Active Drone Corridors</span>
        <strong>42</strong>
      </div>
      <div>
        <span>Service Reliability</span>
        <strong>99.1%</strong>
      </div>
    </div>
  </section>
</template>
