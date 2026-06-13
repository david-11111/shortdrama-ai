<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  selectedRows: Array<{ status: string; selected_image?: string | null }>
}>()

const emit = defineEmits<{
  generateImages: []
  generateVideos: []
}>()

const canGenerateImages = computed(() =>
  props.selectedRows.length > 0 &&
  props.selectedRows.some(r => r.status === 'ready')
)

const canGenerateVideos = computed(() =>
  props.selectedRows.length > 0 &&
  props.selectedRows.some(r => r.status === 'image_done' && r.selected_image)
)
</script>

<template>
  <div class="batch-actions">
    <button
      class="btn btn-primary"
      :disabled="!canGenerateImages"
      @click="emit('generateImages')"
    >
      批量生成参考图
    </button>
    <button
      class="btn btn-success"
      :disabled="!canGenerateVideos"
      @click="emit('generateVideos')"
    >
      批量生成视频
    </button>
  </div>
</template>

<style scoped>
.batch-actions {
  display: flex;
  gap: var(--space-sm);
}

.btn {
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-sm);
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--color-primary);
  color: #fff;
}

.btn-primary:not(:disabled):hover {
  background: var(--color-primary-hover);
}

.btn-success {
  background: var(--color-success);
  color: #fff;
}

.btn-success:not(:disabled):hover {
  opacity: 0.9;
}
</style>
