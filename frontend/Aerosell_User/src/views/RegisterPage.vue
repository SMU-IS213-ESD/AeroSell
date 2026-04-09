<script setup>
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAppStore } from "../store/appStore";

const router = useRouter();
const route = useRoute();
const { setUser, setAuth } = useAppStore();
const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8880").replace(/\/$/, "");

const form = reactive({
  name: "",
  email: "",
  password: "",
  phone: "",
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
    const res = await fetch(
      `${API_BASE}/user/register`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          email: form.email,
          phone: form.phone,
          password: form.password,
        }),
      },
    );

    if (!res.ok) {
      const msg = await extractErrorMessage(res);
      throw new Error(msg);
    }

    const payload = await res.json();

    // Expect backend to return { user: {...}, token: '...' } or { id, email, ... }
    const user = payload.user || payload;
    const token = payload.token || payload.authToken || "";

    setUser(user);
    if (token) setAuth(token);

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
    <h2>Create account</h2>
    <p class="subtle">
      Join AeroSell and start scheduling drone deliveries instantly.
    </p>
    <form class="form-grid" @submit.prevent="submit">
      <label>
        Full Name
        <input v-model="form.name" type="text" required />
      </label>
      <label>
        Email
        <input v-model="form.email" type="email" required />
      </label>
      <label>
        Phone Number
        <input v-model="form.phone" type="tel" required />
      </label>
      <label>
        Password
        <input v-model="form.password" type="password" minlength="6" required />
      </label>
      <button class="btn btn-primary" type="submit" :disabled="loading">
        {{ loading ? "Creating..." : "Register" }}
      </button>
      <p v-if="error" class="warn">{{ error }}</p>
    </form>
  </section>
</template>
