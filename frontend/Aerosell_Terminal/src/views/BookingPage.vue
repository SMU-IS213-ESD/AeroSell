<script setup>
import { computed, reactive, watch, ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { useAppStore } from "../store/appStore";
import { bookDroneAPI, flightPlanningAPI } from "../services/api";

const router = useRouter();
const { state, calculateQuote, saveBooking, setUser } = useAppStore();

const booking = reactive({ ...state.booking });
const quote = computed(() => calculateQuote(booking));
const isSubmitting = ref(false);
const errorMessage = ref("");
const isLoadingPickupPoints = ref(true);

const pickupPoints = ref([]);
const selectedPointIds = reactive({
  fromId: "",
  toId: "",
});

// Internal state for selected pickup points with their coordinates
const selectedPoints = reactive({
  fromPoint: null,
  toPoint: null,
});

watch(
  booking,
  (value) => {
    state.booking = { ...state.booking, ...value };
    state.quote = quote.value;
  },
  { deep: true },
);

// Fetch pickup points from API
const fetchPickupPoints = async () => {
  isLoadingPickupPoints.value = true;
  try {
    const response = await flightPlanningAPI.getPickupPoints();
    if (response.ok) {
      pickupPoints.value = await response.json();
      if (!Array.isArray(pickupPoints.value) || pickupPoints.value.length === 0) {
        errorMessage.value =
          "No pickup points are available right now. Please try again later.";
      }
      // If booking already has locations, find matching points
      if (booking.fromLocation) {
        const fromPoint = pickupPoints.value.find(
          (p) => p.name === booking.fromLocation,
        );
        if (fromPoint) {
          selectedPoints.fromPoint = fromPoint;
          selectedPointIds.fromId = fromPoint.id;
        }
      }
      if (booking.toLocation) {
        const toPoint = pickupPoints.value.find(
          (p) => p.name === booking.toLocation,
        );
        if (toPoint) {
          selectedPoints.toPoint = toPoint;
          selectedPointIds.toId = toPoint.id;
        }
      }
    } else {
      errorMessage.value =
        "Unable to load pickup points. Please refresh and try again.";
      console.error("Failed to fetch pickup points");
    }
  } catch (error) {
    errorMessage.value =
      "Unable to load pickup points. Please refresh and try again.";
    console.error("Error fetching pickup points:", error);
  } finally {
    isLoadingPickupPoints.value = false;
  }
};

watch(
  () => selectedPointIds.fromId,
  (pointId) => {
    const point = pickupPoints.value.find((p) => p.id === pointId) || null;
    selectedPoints.fromPoint = point;
    booking.fromLocation = point ? point.name : "";
  },
);

watch(
  () => selectedPointIds.toId,
  (pointId) => {
    const point = pickupPoints.value.find((p) => p.id === pointId) || null;
    selectedPoints.toPoint = point;
    booking.toLocation = point ? point.name : "";
  },
);

// Load pickup points on component mount
onMounted(() => {
  fetchPickupPoints();
});

const submit = async () => {
  if (isSubmitting.value) return;

  isSubmitting.value = true;
  errorMessage.value = "";

  try {
    // Validate that pickup points are selected
    if (!selectedPoints.fromPoint || !selectedPoints.toPoint) {
      errorMessage.value = "Please select valid From and To locations";
      isSubmitting.value = false;
      return;
    }

    if (selectedPoints.fromPoint.id === selectedPoints.toPoint.id) {
      errorMessage.value = "From and To locations must be different";
      isSubmitting.value = false;
      return;
    }

    // Save locally first
    saveBooking(booking);

    // Combine date and time into ISO timestamp
    const pickupDateTime = new Date(
      `${booking.pickupDate}T${booking.pickupTime}`,
    );
    const timeslot = pickupDateTime.toISOString();

    // Prepare validation data for book-drone composite service (Phase 1)
    const bookingData = {
      user_id: state.user?.id || 1, // Use logged-in user ID or default
      pickup_location: booking.fromLocation,
      dropoff_location: booking.toLocation,
      pickup_coordinates: {
        lat: selectedPoints.fromPoint.latitude,
        lon: selectedPoints.fromPoint.longitude,
      },
      dropoff_coordinates: {
        lat: selectedPoints.toPoint.latitude,
        lon: selectedPoints.toPoint.longitude,
      },
      pickup_point_id: selectedPoints.fromPoint.id,
      dropoff_point_id: selectedPoints.toPoint.id,
      timeslot: timeslot,
      payment_method: "stripe", // We'll use this later
      package_weight_kg: booking.packageWeightKg,
      package_size: booking.packageSize,
      fragile: booking.fragile,
      priority: booking.priority,
    };

    console.log("Validating booking with book-drone service:", bookingData);

    // Phase 1: Call validate endpoint to check user, drones, and route
    const response = await bookDroneAPI.validateBooking(bookingData);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(
        errorData.error || `Validation failed: ${response.statusText}`,
      );
    }

    const result = await response.json();
    console.log("Validation successful:", result);

    // Save validation and booking details to state for payment page
    if (result.success) {
      // Store all validation data that will be needed by payment page
      state.validationData = {
        user_id: bookingData.user_id,
        drone_id: result.selected_drone.id, // Add drone_id for confirm endpoint
        user: result.user,
        selectedDrone: result.selected_drone,
        availableDrones: result.available_drones,
        routeValidation: result.route_validation,
        pickup_location: bookingData.pickup_location, // For backend /confirm endpoint
        dropoff_location: bookingData.dropoff_location,
        pickupLocation: bookingData.pickup_location, // Keep camelCase for frontend
        dropoffLocation: bookingData.dropoff_location,
        timeslot: bookingData.timeslot,
        delivery_cost: result.delivery_cost, // For backend /confirm endpoint
        pickupCoordinates: bookingData.pickup_coordinates,
        dropoffCoordinates: bookingData.dropoff_coordinates,
        pickupPointId: bookingData.pickup_point_id,
        dropoffPointId: bookingData.dropoff_point_id,
        deliveryCost: result.delivery_cost,
        paymentMethod: "stripe",
      };

      // Save booking details
      state.payment = {
        complete: false, // To be completed on payment page
        provider: "stripe",
        orderId: null, // Will be set after order creation
        reference: null, // Will be set after payment
        paidAt: "",
        bookingId: null, // Will be set after confirmation
        estimatedCost: result.delivery_cost,
      };

      // Navigate to payment page with validation data
      router.push("/payment");
    } else {
      throw new Error(result.error || "Validation failed");
    }
  } catch (error) {
    console.error("Validation error:", error);
    errorMessage.value =
      error.message || "Failed to validate booking. Please try again.";
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <section class="panel booking-layout">
    <form class="form-grid booking-form" @submit.prevent="submit">
      <h2>Book a Delivery</h2>
      <label>
        Pickup Date
        <input v-model="booking.pickupDate" type="date" required />
      </label>
      <label>
        Pickup Time
        <!-- <input v-model="booking.pickupTime" type="time" step="1800" required /> -->
        <input v-model="booking.pickupTime" type="time" required />
      </label>
      <label>
        From Location
        <select
          v-model="selectedPointIds.fromId"
          :disabled="isLoadingPickupPoints"
          required
        >
          <option value="" disabled>
            {{
              isLoadingPickupPoints
                ? "Loading pickup points..."
                : "Select source location"
            }}
          </option>
          <option
            v-for="point in pickupPoints"
            :key="point.id"
            :value="point.id"
          >
            {{ point.name }}
          </option>
        </select>
      </label>
      <label>
        To Location
        <select
          v-model="selectedPointIds.toId"
          :disabled="isLoadingPickupPoints"
          required
        >
          <option value="" disabled>
            {{
              isLoadingPickupPoints
                ? "Loading pickup points..."
                : "Select destination location"
            }}
          </option>
          <option
            v-for="point in pickupPoints"
            :key="point.id"
            :value="point.id"
          >
            {{ point.name }}
          </option>
        </select>
      </label>
      <label>
        Package Weight (kg)
        <input
          v-model.number="booking.packageWeightKg"
          type="number"
          min="0.1"
          max="10"
          step="0.1"
          required
        />
      </label>
      <label>
        Package Size
        <select v-model="booking.packageSize" required>
          <option value="small">Small (up to 20 x 20 x 10 cm)</option>
          <option value="medium">Medium (up to 35 x 25 x 20 cm)</option>
          <option value="large">Large (up to 50 x 40 x 30 cm)</option>
        </select>
      </label>
      <label>
        Recipient Name
        <input v-model="booking.recipientName" type="text" required />
      </label>
      <label>
        Recipient Email
        <input v-model="booking.recipientEmail" type="email" required />
      </label>
      <label>
        Recipient Contact Number
        <input v-model="booking.recipientPhone" type="tel" required />
      </label>
      <label class="wide">
        Special Notes
        <textarea
          v-model="booking.specialNotes"
          rows="3"
          placeholder="Access instructions, building details, or handling instructions"
        />
      </label>
      <label class="checkbox">
        <input v-model="booking.fragile" type="checkbox" />
        Fragile handling required
      </label>
      <label class="checkbox">
        <input v-model="booking.priority" type="checkbox" />
        Priority route (faster but premium)
      </label>
      <p v-if="errorMessage" class="warn wide">{{ errorMessage }}</p>
      <button class="btn btn-primary wide" type="submit" :disabled="isSubmitting">
        {{ isSubmitting ? "Validating booking..." : "Continue to Stripe Payment" }}
      </button>
    </form>

    <aside class="price-card">
      <h3>Live Price Estimate</h3>
      <dl>
        <div>
          <dt>Base Fare</dt>
          <dd>${{ quote.baseFare.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>Distance</dt>
          <dd>${{ quote.distanceFee.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>Weight</dt>
          <dd>${{ quote.weightFee.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>Fragile Handling</dt>
          <dd>${{ quote.handlingFee.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>Priority</dt>
          <dd>${{ quote.priorityFee.toFixed(2) }}</dd>
        </div>
        <div>
          <dt>Platform Fee</dt>
          <dd>${{ quote.platformFee.toFixed(2) }}</dd>
        </div>
      </dl>
      <p class="factor">
        Size multiplier: x{{ quote.packageFactor.toFixed(2) }}
      </p>
      <p class="total">Total: ${{ quote.total.toFixed(2) }}</p>
      <p class="subtle">Price finalization happens on Stripe payment page.</p>
    </aside>
  </section>
</template>
