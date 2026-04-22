<template>
  <div class="card">
    <h2>Analytics Dashboard</h2>
    <p style="color:var(--muted);font-size:0.85rem;margin-bottom:1rem;">
      See the performance and friction metrics of the agents executing against your profile.
    </p>
    <div class="loading" v-if="loading">Loading...</div>
    <div v-else>
      <div v-if="!agents.length" class="empty">No agent data yet.</div>
      <div v-else>
        <!-- The agent metrics table or grid goes here -->
        <table class="table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Interactions</th>
              <th>Correction Rate</th>
              <th>Alignment Score</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="agent in agents" :key="agent.name">
              <td>{{ agent.name }}</td>
              <td>{{ agent.total_interactions }}</td>
              <td>{{ agent.correction_rate_pct.toFixed(1) }}%</td>
              <td>{{ agent.alignment_score.toFixed(1) }} / 100</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const agents = ref([])
const loading = ref(true)

const loadAnalytics = async () => {
  try {
    const res = await fetch('/api/analytics/agents')
    if (res.ok) {
      agents.value = await res.json()
    }
  } finally {
    loading.value = false
  }
}

onMounted(loadAnalytics)
</script>
