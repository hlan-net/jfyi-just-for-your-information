<template>
  <div style="max-width: 600px; margin: 4rem auto;">
    <div class="card" v-if="!system.is_ready">
      <h2>Welcome to JFYI! 🚀</h2>
      <p style="color:var(--muted);font-size:0.9rem;margin-bottom:1rem;">
        It looks like this is a fresh installation. To get started, you must configure at least one Identity Provider. The first user to log in will automatically become the system Administrator.
      </p>
      
      <div v-if="!system.has_idp">
        <h3 style="margin-top:2rem;margin-bottom:1rem;font-size:1rem;">Step 1: Configure Identity Provider</h3>
        <div class="form-row">
          <label>Provider Type</label>
          <select v-model="idpForm.provider">
            <option value="github">GitHub OAuth App</option>
            <option value="google">Google OAuth Client</option>
            <option value="entra">Microsoft Entra ID</option>
          </select>
        </div>
        <div class="form-row">
          <label>Client ID</label>
          <input type="text" v-model="idpForm.client_id" placeholder="Client ID from provider" />
        </div>
        <div class="form-row">
          <label>Client Secret</label>
          <input type="password" v-model="idpForm.client_secret" placeholder="Client Secret from provider" />
        </div>
        <button class="btn" @click="saveIdp" style="margin-top:1.5rem;width:100%;">Save Configuration</button>
      </div>

      <div v-else-if="!system.has_admin">
        <h3 style="margin-top:2rem;margin-bottom:1rem;font-size:1rem;">Step 2: Log in as Administrator</h3>
        <p style="color:var(--muted);font-size:0.9rem;margin-bottom:1rem;">
          Your Identity Provider has been configured. Click below to log in and claim the administrator account.
        </p>
        <div style="display:flex; gap:1rem; justify-content:center;">
          <a v-for="provider in system.providers" :key="provider" :href="`/auth/login/${provider}`" class="btn">
            Sign in with {{ provider }}
          </a>
        </div>
      </div>
    </div>
    
    <div class="card" v-else>
      <h2 style="text-align:center;margin-bottom:2rem;">Sign In</h2>
      <div style="display:flex; gap:1rem; justify-content:center;">
        <a v-for="provider in system.providers" :key="provider" :href="`/auth/login/${provider}`" class="btn">
          Sign in with {{ provider }}
        </a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const system = ref({ is_ready: false, has_idp: false, has_admin: false, providers: [] })
const idpForm = ref({ provider: 'github', client_id: '', client_secret: '' })

const loadStatus = async () => {
  const res = await fetch('/api/system/status')
  if (res.ok) {
    system.value = await res.json()
  }
}

const saveIdp = async () => {
  const res = await fetch('/api/system/idp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(idpForm.value)
  })
  if (res.ok) {
    await loadStatus()
  } else {
    alert('Failed to configure IDP.')
  }
}

onMounted(loadStatus)
</script>
