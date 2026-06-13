<template>
  <teleport to="body">
    <transition name="confirm-fade">
      <div v-if="items.length > 0" class="confirm-mask" @click.self="onCancel(items[items.length - 1])">
        <div
          v-for="item in items"
          :key="item.id"
          class="confirm-card"
          role="alertdialog"
          :aria-labelledby="`confirm-title-${item.id}`"
          :aria-describedby="`confirm-msg-${item.id}`"
        >
          <h3 :id="`confirm-title-${item.id}`" class="confirm-title">
            {{ item.title || '请确认' }}
          </h3>
          <p :id="`confirm-msg-${item.id}`" class="confirm-message">{{ item.message }}</p>
          <div class="confirm-actions">
            <button type="button" class="btn btn-cancel" @click="onCancel(item)">
              {{ item.cancelText || '取消' }}
            </button>
            <button
              type="button"
              class="btn"
              :class="item.danger ? 'btn-danger' : 'btn-primary'"
              @click="onConfirm(item)"
            >
              {{ item.okText || '确定' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup lang="ts">
import { confirmQueue, type ConfirmItem } from '@/composables/useConfirm'

const items = confirmQueue

function onConfirm(item: ConfirmItem) {
  item.resolve(true)
}

function onCancel(item: ConfirmItem) {
  item.resolve(false)
}
</script>

<style scoped>
.confirm-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.48);
  z-index: 9000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.confirm-card {
  background: var(--color-bg, #fff);
  color: var(--color-text, #111827);
  min-width: 320px;
  max-width: 440px;
  padding: 24px;
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.18);
  animation: confirm-pop 0.18s ease-out;
}

.confirm-title {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 600;
}

.confirm-message {
  margin: 0 0 20px;
  font-size: 14px;
  color: var(--color-text-secondary, #4b5563);
  line-height: 1.6;
  white-space: pre-wrap;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn {
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.btn-cancel {
  background: transparent;
  color: var(--color-text-secondary, #4b5563);
  border: 1px solid var(--color-border, #e5e7eb);
}

.btn-cancel:hover {
  background: var(--color-bg-secondary, #f9fafb);
}

.btn-primary {
  background: var(--color-primary, #6366f1);
  color: #fff;
}

.btn-primary:hover {
  background: var(--color-primary-hover, #4f46e5);
}

.btn-danger {
  background: var(--color-error, #ef4444);
  color: #fff;
}

.btn-danger:hover {
  background: #dc2626;
}

.confirm-fade-enter-active,
.confirm-fade-leave-active {
  transition: opacity 0.18s ease;
}

.confirm-fade-enter-from,
.confirm-fade-leave-to {
  opacity: 0;
}

@keyframes confirm-pop {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
</style>
