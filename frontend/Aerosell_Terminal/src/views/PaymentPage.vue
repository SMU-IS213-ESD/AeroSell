<script setup>
import { computed, ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { loadStripe } from "@stripe/stripe-js";
import { useAppStore } from "../store/appStore";
import { bookDroneAPI } from "../services/api";

const router = useRouter();
const { state, completeStripePayment } = useAppStore();
const stripePromise = loadStripe(
  import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY || "",
);

const processing = ref(false);
const paymentMessage = ref("");
const stripe = ref(null);
const elements = ref(null);
const cardElement = ref(null);

// Get validation data from state
const validationData = computed(() => state.validationData || {});
const deliveryCost = computed(() => validationData.value.delivery_cost || 0);
const selectedDrone = computed(() => validationData.value.selected_drone || {});
const canPay = computed(() =>
  Boolean(validationData.value.user_id && validationData.value.delivery_cost),
);

// Initialize Stripe Elements
const initializeStripe = async () => {
  stripe.value = await stripePromise;
  elements.value = stripe.value.elements();

  // Create and mount card element
  cardElement.value = elements.value.create("card", {
    style: {
      base: {
        fontSize: "16px",
        color: "#32325d",
        "::placeholder": {
          color: "#aab7c4",
        },
      },
      invalid: {
        color: "#fa755a",
        iconColor: "#fa755a",
      },
    },
  });

  cardElement.value.mount("#card-element");
};

const pay = async () => {
  if (!canPay.value) {
    paymentMessage.value =
      "Validation data is required. Please complete the booking form first.";
    return;
  }

  if (!stripe.value || !cardElement.value) {
    paymentMessage.value = "Payment system not initialized";
    return;
  }

  processing.value = true;
  paymentMessage.value = "";

  try {
    console.log("Processing payment and confirmation for booking validation");

    // Step 1: Confirm the payment using Stripe Elements
    const { error: stripeError, paymentIntent } =
      await stripe.value.confirmCardPayment(clientSecret.value, {
        payment_method: {
          card: cardElement.value,
          billing_details: {
            name: cardHolderName.value,
          },
        },
      });

    if (stripeError) {
      throw new Error(stripeError.message || "Card payment failed");
    }

    if (!paymentIntent) {
      throw new Error("Payment confirmation failed. No payment intent returned.");
    }

    // Payment initiated! Now poll for order creation
    paymentMessage.value = "Processing payment...";

    // Get payment_id from state or extract from paymentIntent
    const paymentId = state.payment?.payment_id;
    if (!paymentId) {
      throw new Error("Payment ID not found. Cannot verify payment status.");
    }

    // Poll payment endpoint to wait for order creation
    const maxRetries = 30; // 30 seconds max
    const retryDelay = 1000; // 1 second
    let orderDetails = null;

    for (let i = 0; i < maxRetries; i++) {
      const paymentResponse = await bookDroneAPI.getPayment(paymentId);

      if (!paymentResponse.ok) {
        console.warn(`Failed to fetch payment status: ${paymentResponse.status}`);
        await new Promise(resolve => setTimeout(resolve, retryDelay));
        continue;
      }

      const paymentData = await paymentResponse.json();

      // Check if order has been created (order_id will be populated after webhook processing)
      if (paymentData.order_id && paymentData.pickup_pin) {
        orderDetails = paymentData;
        break;
      }

      // Wait before next retry
      await new Promise(resolve => setTimeout(resolve, retryDelay));
    }

    if (!orderDetails) {
      throw new Error("Order creation timeout. Payment succeeded but order was not created.");
    }

    console.log("Payment and order creation successful:", orderDetails);

    // Save confirmation details
    state.payment = {
      complete: true,
      provider: "stripe",
      orderId: orderDetails.order_id,
      reference: orderDetails.transaction_id,
      paidAt: new Date().toISOString(),
      bookingId: orderDetails.id,
      confirmationData: orderDetails,
    };

    // Update payment in store
    completeStripePayment(orderDetails.id, orderDetails.pickup_pin);

    // Navigate to confirmation page
    router.push("/confirmation");
  } catch (error) {
    console.error("Payment error:", error);
    paymentMessage.value =
      error instanceof Error
        ? error.message
        : "Payment failed. Please try again.";
  } finally {
    processing.value = false;
  }
};

// Payment form fields - only cardholder name needed for billing details
const cardHolderName = ref("");

// Will hold the client secret from backend
const clientSecret = ref("");

// Initialize Stripe Elements and page
onMounted(async () => {
  // Initialize Stripe Elements first
  await initializeStripe();

  // Create payment intent to get client_secret
  try {
    // Prepare order data for webhook processing
    const orderData = {
      user_id: validationData.value.user_id,
      drone_id: validationData.value.drone_id,
      pickup_location: validationData.value.pickup_location,
      dropoff_location: validationData.value.dropoff_location,
      item_description: validationData.value.timeslot || `${state.booking.pickupDate} at ${state.booking.pickupTime}`,
      pickup_pin: validationData.value.pickup_pin
    };

    const response = await bookDroneAPI.createPaymentIntent(
      deliveryCost.value,
      "SGD",
      orderData
    );

    if (response.ok) {
      const result = await response.json();
      clientSecret.value = result.client_secret;
      state.payment = {
        payment_id: result.payment_id,
        client_secret: result.client_secret
      };
      console.log("PaymentIntent created, client_secret received");
    } else {
      paymentMessage.value = "Failed to initialize payment system";
    }
  } catch (error) {
    console.error("Error creating payment intent:", error);
    paymentMessage.value = "Error initializing payment";
  }

  // Then check validation
  if (!validationData.value.user_id) {
    paymentMessage.value =
      "No booking validation found. Please complete your booking first.";
  }
});
</script>

<template>
  <section class="panel payment-panel">
    <div class="payment-form">
      <h2>Payment</h2>
      <label>
        Cardholder Name
        <input
          v-model="cardHolderName"
          type="text"
          placeholder="John Doe"
          required
        />
      </label>
      <label>
        Card Details
        <div id="card-element" class="stripe-card-input"></div>
        <div id="card-errors" role="alert" class="stripe-error"></div>
      </label>
      <button
        class="btn btn-primary wide"
        :disabled="processing || !canPay"
        @click="pay"
      >
        {{ processing ? "Processing..." : `Pay $${deliveryCost.toFixed(2)}` }}
      </button>
      <p v-if="paymentMessage" class="warn">{{ paymentMessage }}</p>
    </div>

    <aside class="price-card">
      <h3>Booking Summary</h3>
      <div class="detail-row">
        <p><strong>From:</strong></p>
        <p>{{ state.booking.fromLocation || "N/A" }}</p>
      </div>
      <div class="detail-row">
        <p><strong>To:</strong></p>
        <p>{{ state.booking.toLocation || "N/A" }}</p>
      </div>
      <div class="detail-row">
        <p><strong>Date:</strong></p>
        <p>{{ state.booking.pickupDate }} at {{ state.booking.pickupTime }}</p>
      </div>
      <div class="detail-row">
        <p><strong>Drone:</strong></p>
        <p>Drone {{ selectedDrone.id || "N/A" }}</p>
      </div>
      <div class="detail-row">
        <p><strong>Weight:</strong></p>
        <p>{{ state.booking.packageWeightKg }} kg</p>
      </div>
      <div class="detail-row">
        <p><strong>Size:</strong></p>
        <p>{{ state.booking.packageSize }}</p>
      </div>
      <p class="total">Total: ${{ deliveryCost.toFixed(2) }}</p>
      <p class="subtle">Payment processed via Stripe</p>
    </aside>
  </section>
</template>

<style scoped>
.detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.info {
  color: #666;
  margin-bottom: 1rem;
}

.payment-form label {
  display: block;
  margin-bottom: 1rem;
}

.payment-form input {
  width: 100%;
  padding: 0.5rem;
  margin-top: 0.25rem;
  border: 1px solid #ccc;
  border-radius: 4px;
}

.inline-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.total {
  font-weight: bold;
  font-size: 1.2rem;
  margin-top: 1rem;
  border-top: 2px solid #eee;
  padding-top: 1rem;
}

.subtle {
  color: #666;
  font-size: 0.9rem;
  margin-top: 1rem;
}

.warn {
  color: #e53e3e;
  margin-top: 0.5rem;
}

.wide {
  width: 100%;
}

.stripe-card-input {
  padding: 0.5rem;
  border: 1px solid #ccc;
  border-radius: 4px;
  background: white;
  min-height: 38px;
}

.stripe-error {
  color: #e53e3e;
  margin-top: 0.5rem;
  font-size: 0.9rem;
}
</style>
