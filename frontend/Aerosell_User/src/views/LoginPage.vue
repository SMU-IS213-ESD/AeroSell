<script setup>
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAppStore } from "../store/appStore";

const router = useRouter();
const route = useRoute();
const { setUser, setAuth, fetchUserOrders } = useAppStore();
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8880").replace(/\/$/, "");

const form = reactive({
  email: "",
  password: "",
});

const loading = ref(false);
const error = ref("");

const extractErrorMessage = async (res) => {
  let msg = `Request failed: ${res.status}`;
  const text = await res.text();
  if (!text) return msg;
  try {
    const payload = JSON.parse(text);
    return payload?.message || payload?.error || text;
  } catch {
    return text;
  }
};

const submit = async () => {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch(`${API_BASE}/user/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: form.email, password: form.password }),
    });

    if (!res.ok) {
      const msg = await extractErrorMessage(res);
      throw new Error(msg);
    }

    const payload = await res.json();
    const user = payload.user || payload;
    const token = payload.token || payload.authToken || "";

    setUser(user);
    if (token) setAuth(token);

    // Fetch user orders after successful login
    await fetchUserOrders(user.id || user.email);

    const redirectPath =
      typeof route.query.redirect === "string" ? route.query.redirect : "/status";
    router.push(redirectPath);
  } catch (err) {
    const raw = err instanceof Error ? err.message : String(err);
    error.value = `Error: ${raw}`;
  } finally {
    loading.value = false;
  }
};
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
      <p class="muted small" style="margin-top: 4px">
        Don't have an account? <RouterLink to="/register">Register</RouterLink>
      </p>
      <button class="btn btn-primary" type="submit" :disabled="loading">
        {{ loading ? "Signing in..." : "Login" }}
      </button>
      <p v-if="error" class="warn">{{ error }}</p>
    </form>
  </section>
</template>
