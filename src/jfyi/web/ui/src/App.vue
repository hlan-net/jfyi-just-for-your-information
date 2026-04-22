<template>
  <div v-if="!isAuthRoute">
    <header>
      <h1>⚡ JFYI Dashboard</h1>
      <span>Just For Your Information — MCP Server &amp; Analytics Hub</span>
      <span class="badge">v2.0</span>
      <div style="margin-left:auto; display:flex; gap:1rem; align-items:center;" v-if="user">
        <span style="font-size:0.8rem; color:var(--muted)">{{ user.email }}</span>
        <button class="btn btn-outline" @click="logout" style="padding:0.2rem 0.5rem; font-size:0.75rem;">Logout</button>
      </div>
    </header>
    <nav v-if="user">
      <router-link to="/">📊 Analytics</router-link>
      <router-link to="/profile">👤 Profile</router-link>
      <router-link to="/settings">⚙️ Settings</router-link>
      <router-link v-if="user.is_admin" to="/admin">🛡️ Admin</router-link>
    </nav>
    <main>
      <router-view></router-view>
    </main>
  </div>
  <div v-else>
    <router-view></router-view>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const user = ref(null)

const isAuthRoute = computed(() => route.name === 'Login')

onMounted(async () => {
  if (!isAuthRoute.value) {
    const res = await fetch('/api/me')
    if (res.ok) {
      user.value = await res.json()
    } else {
      router.push('/login')
    }
  }
})

const logout = async () => {
  await fetch('/auth/logout', { method: 'POST' })
  user.value = null
  router.push('/login')
}
</script>
