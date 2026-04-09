<script setup>
import { computed, ref } from "vue";
import { useAppStore } from "../store/appStore";
import { useRouter } from "vue-router";

const router = useRouter();
const { state, advanceStatus, fetchUserOrders } = useAppStore();

const query = ref("");
const loading = ref(false);

const userOrders = computed(() => {
  const userId = state.user?.id || "";
  if (!userId) {
    console.log('No userId, returning empty array');
    return [];
  }
  return state.orders;
});

const refreshData = async () => {
  if (!state.user?.id) return;
  loading.value = true;
  try {
    await fetchUserOrders(state.user.id);
  } catch (error) {
    console.error('Failed to refresh orders:', error);
  } finally {
    loading.value = false;
  }
};

const visibleOrders = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return userOrders.value;
  return userOrders.value.filter((item) =>
    (item.trackingCode || "").toLowerCase().includes(q),
  );
});

const formatStatus = (value) => String(value || "").replace("_", " ");

const navigateToClaim = (trackingCode) => {
  router.push({ name: "claim", params: { trackingCode } });
};
</script>

<template>
  <section class="panel status-panel">
    <h2>Delivery Status</h2>
    <div style="display: flex; gap: 8px; margin-bottom: 16px;">
      <button
        class="btn btn-secondary"
        @click="refreshData"
        :disabled="loading || !state.user?.id"
        style="margin: 0;"
      >
        {{ loading ? "Refreshing..." : "Refresh" }}
      </button>
    </div>

    <div v-if="!state.user?.email" class="warn">
      Please login to view your delivery statuses.
    </div>

    <div v-else-if="visibleOrders.length" class="timeline">
      <article
        v-for="delivery in visibleOrders"
        :key="delivery.trackingCode"
        class="status-card"
      >
        <p><strong>Tracking:</strong> {{ delivery.trackingCode }}</p>
      <p><strong>Pickup Pin:</strong> {{ delivery.pickupPin }}</p>
        <p>
          <strong>Route:</strong> {{ delivery.fromLocation }} ->
          {{ delivery.toLocation }}
        </p>
        <p>
          <strong>Current Status:</strong> {{ formatStatus(delivery.status) }}
        </p>
        <button
          v-if="delivery.status !== 'refunded'"
          class="btn btn-secondary"
          @click="navigateToClaim(delivery.trackingCode)"
          style="margin-top: 12px"
        >
          Claim damage
        </button>
        <!-- <button
          class="btn btn-primary"
          :disabled="delivery.status === 'delivered'"
          @click="advanceStatus(delivery.trackingCode)"
        >
          {{
            delivery.status === "delivered" ? "Delivered" : "Simulate Next Step"
          }}
        </button> -->
      </article>
    </div>

    <p v-else-if="query" class="warn">
      No matching order found for your account.
    </p>
    <p v-else class="warn">No orders found for your account yet.</p>
  </section>
</template>
