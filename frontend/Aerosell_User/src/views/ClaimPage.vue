<script setup>
import { ref, computed, onMounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useAppStore } from "../store/appStore"

const route = useRoute()
const router = useRouter()
const { state } = useAppStore()

const trackingCode = route.params.trackingCode

const formData = ref({
  typeOfDamage: "",
  severity: "",
  description: "",
  contactEmail: state.user?.email || "",
  contactPhone: state.user?.phone || ""
})

const evidenceFile = ref(null)

const handleFileChange = (e) => {
  evidenceFile.value = e.target.files[0] || null
}

const errorMessage = ref("")
const successMessage = ref("")
const loading = ref(false)

const damageTypes = [
  { value: "product_damage", label: "Product Damage" },
  { value: "package_damage", label: "Package Damage" },
  { value: "delivery_delay", label: "Delivery Delay" },
  { value: "missing_items", label: "Missing Items" },
  { value: "wrong_item", label: "Wrong Item Delivered" },
  { value: "other", label: "Other" }
]

const severityOptions = [
  { value: "minor", label: "Minor" },
  { value: "moderate", label: "Moderate" },
  { value: "major", label: "Major" }
]

const order = computed(() => {
  return state.orders?.find(o => o.trackingCode === trackingCode)
})

const submitClaim = async () => {
  if (!formData.value.typeOfDamage || !formData.value.severity || !formData.value.description) {
    errorMessage.value = "Please fill in all required fields"
    return
  }

  if (!formData.value.contactEmail) {
    errorMessage.value = "Please provide a contact email"
    return
  }

  if (!evidenceFile.value) {
    errorMessage.value = "Please upload an evidence file"
    return
  }

  loading.value = true
  errorMessage.value = ""
  successMessage.value = ""

  try {
    // Extract numeric order ID from tracking code e.g. "AS-0001" → 1
    const numericOrderId = parseInt(trackingCode.replace(/^AS-0*/i, ""), 10)

    const payload = new FormData()
    payload.append("user_id", state.user?.id)
    payload.append("order_id", numericOrderId)
    payload.append("description", formData.value.description)
    payload.append("file", evidenceFile.value)

    const response = await fetch("http://localhost:8880/insurance-claim/submit", {
      method: "POST",
      body: payload
    })

    const result = await response.json()

    if (response.ok) {
      const claimResult = result.claim_result
      if (claimResult === "APPROVED") {
        successMessage.value = "Your insurance claim has been APPROVED. Redirecting in 5 seconds..."
      } else {
        errorMessage.value = "Your insurance claim has been REJECTED. Redirecting in 5 seconds..."
      }
      setTimeout(() => {
        router.push("/status")
      }, 5000)
    } else {
      errorMessage.value = result.detail || result.error || "Failed to submit claim. Please try again."
    }
  } catch (error) {
    console.error("Error submitting claim:", error)
    errorMessage.value = "An error occurred. Please try again."
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  router.push("/status")
}

onMounted(() => {
  if (!trackingCode) {
    errorMessage.value = "No tracking code provided"
  }
})
</script>

<template>
  <section class="panel claim-panel">
    <h2>Submit Insurance Claim</h2>

    <div v-if="errorMessage" class="error" style="margin-bottom: 16px;">
      {{ errorMessage }}
    </div>

    <div v-if="successMessage" class="success" style="margin-bottom: 16px; color: green;">
      {{ successMessage }}
    </div>

    <div v-if="order" style="margin-bottom: 24px;">
      <p><strong>Tracking:</strong> {{ order.trackingCode }}</p>
      <p><strong>Route:</strong> {{ order.fromLocation }} → {{ order.toLocation }}</p>
      <p><strong>Status:</strong> {{ order.status }}</p>
    </div>

    <form @submit.prevent="submitClaim" v-if="trackingCode">
      <div class="form-row">
        <label>Type of Damage <span class="required">*</span></label>
        <select v-model="formData.typeOfDamage" required>
          <option value="">Select damage type</option>
          <option v-for="type in damageTypes" :key="type.value" :value="type.value">
            {{ type.label }}
          </option>
        </select>
      </div>

      <div class="form-row">
        <label>Severity <span class="required">*</span></label>
        <select v-model="formData.severity" required>
          <option value="">Select severity</option>
          <option v-for="level in severityOptions" :key="level.value" :value="level.value">
            {{ level.label }}
          </option>
        </select>
      </div>

      <div class="form-row">
        <label>Description <span class="required">*</span></label>
        <textarea
          v-model="formData.description"
          placeholder="Please describe the damage or issue in detail..."
          rows="5"
          required
        ></textarea>
      </div>

      <div class="form-row">
        <label>Contact Email <span class="required">*</span></label>
        <input
          type="email"
          v-model="formData.contactEmail"
          placeholder="your@email.com"
          required
        >
      </div>

      <div class="form-row">
        <label>Contact Phone</label>
        <input
          type="tel"
          v-model="formData.contactPhone"
          placeholder="+65 1234 5678"
        >
      </div>

      <div class="form-row">
        <label>Evidence File <span class="required">*</span></label>
        <input
          type="file"
          accept="image/*,.pdf"
          @change="handleFileChange"
          required
        >
        <small style="color: #666; margin-top: 4px; display: block;">Upload a photo or PDF as evidence (required)</small>
      </div>

      <div class="form-buttons">
        <button
          type="button"
          class="btn btn-secondary"
          @click="goBack"
          :disabled="loading"
        >
          Cancel
        </button>
        <button
          type="submit"
          class="btn btn-primary"
          :disabled="loading"
        >
          {{ loading ? "Submitting..." : "Submit Claim" }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.claim-panel {
  max-width: 800px;
  margin: 0 auto;
}

.required {
  color: red;
}

.form-row {
  margin: 20px 0;
}

.form-row label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
}

.form-row input,
.form-row select,
.form-row textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 16px;
}

.form-row textarea {
  resize: vertical;
}

.form-buttons {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

.form-buttons button {
  flex: 1;
}

@media (max-width: 600px) {
  .form-buttons {
    flex-direction: column;
  }
}
</style>
