<template>
  <section class="panel">
    <div class="panel-title">
      <h2>接管动作</h2>
    </div>
    <div class="actions">
      <button
        v-for="action in actions"
        :key="action.id"
        type="button"
        :disabled="!action.enabled"
        :title="action.reason || action.label"
        @click="$emit('action', action.id)"
      >
        {{ action.label }}
      </button>
    </div>
    <router-link v-if="projectId" class="expert-link" :to="`/director/produce/${projectId}`">
      打开专家后台
    </router-link>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  actions: Array<{ id: string; label: string; enabled: boolean; reason?: string }>
  projectId: string
}>()

defineEmits<{
  action: [actionId: string]
}>()
</script>

<style scoped>
.panel {
  background: #0b0b0c;
  border: 1px solid #3f3f46;
  border-radius: 7px;
  overflow: hidden;
}

.panel-title {
  padding: 16px 18px;
  border-bottom: 1px solid #27272a;
}

h2 {
  margin: 0;
  color: #f8fafc;
  font-size: 16px;
}

.actions {
  display: grid;
  gap: 8px;
  padding: 14px;
}

button,
.expert-link {
  display: block;
  width: 100%;
  border: 1px solid #3f3f46;
  border-radius: 7px;
  background: #111113;
  padding: 10px 12px;
  color: #e5e7eb;
  text-align: center;
  text-decoration: none;
  cursor: pointer;
}

button:disabled {
  color: #52525b;
  cursor: not-allowed;
}

.expert-link {
  margin: 0 14px 14px;
  width: auto;
  border-color: #f97316;
  color: #fed7aa;
  font-weight: 700;
}
</style>
