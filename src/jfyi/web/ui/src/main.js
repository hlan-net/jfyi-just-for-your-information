import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'

// Import views
import Login from './views/Login.vue'
import Dashboard from './views/Dashboard.vue'
import Profile from './views/Profile.vue'
import Settings from './views/Settings.vue'
import Admin from './views/Admin.vue'

const routes = [
  { path: '/login', name: 'Login', component: Login },
  { path: '/', name: 'Dashboard', component: Dashboard, meta: { requiresAuth: true } },
  { path: '/profile', name: 'Profile', component: Profile, meta: { requiresAuth: true } },
  { path: '/settings', name: 'Settings', component: Settings, meta: { requiresAuth: true } },
  { path: '/admin', name: 'Admin', component: Admin, meta: { requiresAuth: true, requiresAdmin: true } }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Navigation Guard
router.beforeEach(async (to, from, next) => {
  if (to.name === 'Login') {
    // Check if system initialized
    try {
      const res = await fetch('/api/system/status')
      const data = await res.json()
      if (data.is_ready) {
        // system is initialized, let user try to login
        next()
      } else {
        // System not fully initialized, Login page handles wizard
        next()
      }
    } catch {
      next()
    }
  } else if (to.matched.some(record => record.meta.requiresAuth)) {
    try {
      const res = await fetch('/api/me')
      if (res.ok) {
        const user = await res.json()
        if (to.meta.requiresAdmin && !user.is_admin) {
          next({ name: 'Dashboard' })
        } else {
          next()
        }
      } else {
        next({ name: 'Login' })
      }
    } catch {
      next({ name: 'Login' })
    }
  } else {
    next()
  }
})

const app = createApp(App)
app.use(router)
app.mount('#app')
