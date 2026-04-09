<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useAppStore } from "../store/appStore";

const router = useRouter();
const { state } = useAppStore();

const hasConfirmation = computed(
  () => state.payment.complete && state.delivery.pickupPin,
);

if (!hasConfirmation.value) {
  router.replace("/book");
}
</script>

<template>
  <section class="panel confirmation-panel" v-if="hasConfirmation">
    <h2>Payment Confirmed</h2>
    <p class="subtle">
      Use this one-time code at the pickup machine to release the package.
    </p>
    <div class="pin-box">{{ state.delivery.pickupPin }}</div>
    <p>
      Tracking Code:
      <strong>{{ state.delivery.trackingCode }}</strong>
    </p>
    <div class="cta-row">
      <RouterLink class="btn btn-primary" to="/status"
        >Check Delivery Status</RouterLink
      >
      <RouterLink class="btn btn-ghost" to="/book">Book Another</RouterLink>
    </div>
  </section>
</template>
