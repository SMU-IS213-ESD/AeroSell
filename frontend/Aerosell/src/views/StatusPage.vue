<script setup>
import { computed, ref } from 'vue'
import { useAppStore } from '../store/appStore'

const { state, advanceStatus } = useAppStore()

const query = ref('')

const userOrders = computed(() => {
  const email = state.user?.email?.toLowerCase?.() || ''
  if (!email) return []

  return state.orders.filter((item) => (item.ownerEmail || '').toLowerCase() === email)
})

const visibleOrders = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return userOrders.value
  return userOrders.value.filter((item) => (item.trackingCode || '').toLowerCase().includes(q))
})

const formatStatus = (value) => String(value || '').replace('_', ' ')
</script>

<template>
  <section class="panel status-panel">
    <h2>Delivery Status</h2>

    <div v-if="!state.user?.email" class="warn">Please login to view your delivery statuses.</div>

    <div v-else-if="visibleOrders.length" class="timeline">
      <article v-for="delivery in visibleOrders" :key="delivery.trackingCode" class="status-card">
        <p><strong>Tracking:</strong> {{ delivery.trackingCode }}</p>
        <p><strong>Route:</strong> {{ delivery.fromLocation }} -> {{ delivery.toLocation }}</p>
        <p><strong>Current Status:</strong> {{ formatStatus(delivery.status) }}</p>
        <ul>
          <li v-for="item in delivery.milestones" :key="item.key" :class="{ done: item.complete }">
            <div>
              <strong>{{ item.label }}</strong>
              <p>{{ item.details }}</p>
            </div>
            <span>{{ item.complete ? 'Done' : 'Pending' }}</span>
          </li>
        </ul>
        <button
          class="btn btn-primary"
          :disabled="delivery.status === 'delivered'"
          @click="advanceStatus(delivery.trackingCode)"
        >
          {{ delivery.status === 'delivered' ? 'Delivered' : 'Simulate Next Step' }}
        </button>
      </article>
    </div>

    <p v-else-if="query" class="warn">No matching order found for your account.</p>
    <p v-else class="warn">No orders found for your account yet.</p>
  </section>
</template>
