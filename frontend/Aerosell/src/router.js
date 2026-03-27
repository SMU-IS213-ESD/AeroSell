import { createRouter, createWebHistory } from 'vue-router'
import HomePage from './views/HomePage.vue'
import LoginPage from './views/LoginPage.vue'
import RegisterPage from './views/RegisterPage.vue'
import BookingPage from './views/BookingPage.vue'
import PaymentPage from './views/PaymentPage.vue'
import ConfirmationPage from './views/ConfirmationPage.vue'
import StatusPage from './views/StatusPage.vue'
import { useAppStore } from './store/appStore'

const routes = [
  { path: '/', name: 'home', component: HomePage },
  { path: '/login', name: 'login', component: LoginPage },
  { path: '/register', name: 'register', component: RegisterPage },
  { path: '/book', name: 'book', component: BookingPage, meta: { requiresAuth: true } },
  { path: '/payment', name: 'payment', component: PaymentPage, meta: { requiresAuth: true } },
  {
    path: '/confirmation',
    name: 'confirmation',
    component: ConfirmationPage,
    meta: { requiresAuth: true },
  },
  { path: '/status', name: 'status', component: StatusPage, meta: { requiresAuth: true } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0, behavior: 'smooth' }
  },
})

router.beforeEach((to) => {
  const { state } = useAppStore()
  const isAuthed = Boolean(state.user?.email)

  if (to.meta.requiresAuth && !isAuthed) {
    return {
      name: 'login',
      query: { redirect: to.fullPath },
    }
  }

  if (to.name === 'payment' && !state.quote) {
    return { name: 'book' }
  }

  if (to.name === 'confirmation' && !state.payment.complete) {
    return { name: 'payment' }
  }

  return true
})

export default router
