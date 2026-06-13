<template>
  <div class="director-hub">
    <header class="page-header">
      <div>
        <p class="page-kicker">Director Chain</p>
        <h1>导演链路</h1>
        <p class="page-subtitle">拆分为制作流与诊断流，减少单页负担，保持快速操作。</p>
      </div>
      <router-link to="/tasks" class="btn-link">任务队列</router-link>
    </header>

    <section class="quick-bar">
      <label for="project-id">项目 ID</label>
      <input id="project-id" v-model.trim="projectId" placeholder="可选：输入 project_id 后再进入子页" />
      <button type="button" class="btn-primary" @click="openFlow">进入制作流</button>
      <button type="button" class="btn-secondary" @click="openInsight">进入诊断流</button>
      <button type="button" class="btn-secondary" @click="router.push('/director/workbench')">导演工作台</button>
      <button type="button" class="btn-secondary" @click="router.push('/director/produce')">生产流水线</button>
    </section>

    <section class="cards-grid">
      <article class="card">
        <h2>制作流</h2>
        <p>用于提交 5 类异步任务：`script/chat/prepare/produce/reference-images`。</p>
        <ul>
          <li>适合“我要开始生产”场景</li>
          <li>一屏聚焦提交与返回 task_id</li>
          <li>提交后可一键跳任务页追踪</li>
        </ul>
        <button type="button" class="btn-primary" @click="openFlow">打开制作流</button>
      </article>

      <article class="card">
        <h2>诊断流</h2>
        <p>用于同步诊断、评估、重做建议、项目记忆读写、演化模式查询。</p>
        <ul>
          <li>适合“为什么这样”和“怎么改”场景</li>
          <li>覆盖 presets/evaluation/diagnose/recommend/explain/evaluate/rework</li>
          <li>支持 project-memory 与 evolution-patterns</li>
        </ul>
        <button type="button" class="btn-secondary" @click="openInsight">打开诊断流</button>
      </article>
    </section>

    <section class="extra-links">
      <router-link class="btn-secondary" to="/director/retrieve">提示词检索调试</router-link>
      <router-link class="btn-secondary" to="/director/evaluation">闭环评测</router-link>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const projectId = ref((route.params.projectId as string) || localStorage.getItem('director:last_project_id') || '')

watch(
  () => route.params.projectId,
  (value) => {
    if (typeof value === 'string') {
      projectId.value = value
    }
  },
)

watch(projectId, (value) => {
  localStorage.setItem('director:last_project_id', value || '')
})

function openFlow() {
  if (projectId.value) {
    void router.push(`/director/flow/${encodeURIComponent(projectId.value)}`)
    return
  }
  void router.push('/director/flow')
}

function openInsight() {
  if (projectId.value) {
    void router.push(`/director/insight/${encodeURIComponent(projectId.value)}`)
    return
  }
  void router.push('/director/insight')
}
</script>

<style scoped>
.director-hub {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--space-xl);
  display: grid;
  gap: var(--space-lg);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-md);
}

.page-kicker {
  margin: 0 0 var(--space-xs);
  color: var(--color-primary);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.page-header h1 {
  margin: 0;
  font-size: 2rem;
}

.page-subtitle {
  margin: var(--space-sm) 0 0;
  color: var(--color-text-secondary);
}

.btn-link {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
  color: var(--color-text-secondary);
}

.quick-bar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-wrap: wrap;
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
}

.quick-bar label {
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.quick-bar input {
  min-width: 280px;
  flex: 1;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg);
  color: var(--color-text);
  padding: var(--space-sm);
  font: inherit;
}

.quick-bar input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-md);
}

.card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-lg);
  background: var(--color-bg);
  display: grid;
  gap: var(--space-sm);
}

.card h2 {
  margin: 0;
}

.card p {
  margin: 0;
  color: var(--color-text-secondary);
}

.card ul {
  margin: 0;
  padding-left: 1.1rem;
  color: var(--color-text-secondary);
}

button {
  border: none;
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
  cursor: pointer;
}

.btn-primary {
  background: var(--color-primary);
  color: #fff;
}

.btn-secondary {
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
}

.extra-links {
  display: flex;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.extra-links .btn-secondary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  padding: var(--space-sm) var(--space-md);
}

@media (max-width: 800px) {
  .director-hub {
    padding: var(--space-md);
  }

  .page-header {
    flex-direction: column;
  }

  .cards-grid {
    grid-template-columns: 1fr;
  }
}
</style>
