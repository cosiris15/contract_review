<template>
  <div class="skills-view">
    <div class="page-header">
      <h2>Skills 管理</h2>
      <div v-if="skillsData" class="stats">
        <span class="stat-item">共 {{ skillsData.total }} 个 Skills</span>
        <span
          v-for="(count, backend) in skillsData.by_backend"
          :key="backend"
          class="stat-item"
        >
          {{ backendLabel(backend) }}: {{ count }}
        </span>
      </div>
    </div>

    <div class="filter-bar">
      <select v-model="filterDomain" class="filter-select">
        <option value="">全部领域</option>
        <option value="*">通用</option>
        <option
          v-for="domain in domains"
          :key="domain.domain_id"
          :value="domain.domain_id"
        >
          {{ domain.name }}
        </option>
      </select>

      <select v-model="filterBackend" class="filter-select">
        <option value="">全部来源</option>
        <option value="local">本地</option>
        <option value="refly">Refly</option>
      </select>
    </div>

    <div v-if="loading" class="state-text">加载中...</div>
    <div v-else-if="errorMessage" class="state-text error">{{ errorMessage }}</div>

    <div v-else class="skills-grid">
      <article
        v-for="skill in filteredSkills"
        :key="skill.skill_id"
        class="skill-card"
        :class="{ 'not-registered': !skill.is_registered }"
        @click="toggleDetail(skill.skill_id)"
      >
        <div class="skill-header">
          <h3 class="skill-name">{{ skill.name }}</h3>
          <span class="status-dot" :class="skill.is_registered ? 'active' : 'inactive'" />
        </div>

        <p class="skill-id">{{ skill.skill_id }}</p>
        <p class="skill-desc">{{ skill.description || '暂无描述' }}</p>

        <div class="skill-tags">
          <span class="tag domain">{{ domainLabel(skill.domain) }}</span>
          <span class="tag backend">{{ backendLabel(skill.backend) }}</span>
          <span class="tag category">{{ categoryLabel(skill.category) }}</span>
        </div>

        <div
          v-if="expandedSkillId === skill.skill_id"
          class="skill-detail"
          @click.stop
        >
          <div v-if="currentDetail(skill.skill_id)?.local_handler">
            <strong>Handler:</strong>
            <span>{{ currentDetail(skill.skill_id).local_handler }}</span>
          </div>
          <div v-if="currentDetail(skill.skill_id)?.refly_workflow_id">
            <strong>Workflow:</strong>
            <span>{{ currentDetail(skill.skill_id).refly_workflow_id }}</span>
          </div>
          <div>
            <strong>被引用条款:</strong>
            <span>
              {{
                (currentDetail(skill.skill_id)?.used_by_checklist_items || []).length
                  ? currentDetail(skill.skill_id).used_by_checklist_items.join(', ')
                  : '无'
              }}
            </span>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchDomains, fetchSkillDetail, fetchSkills } from '@/api/skills'

const skillsData = ref(null)
const domains = ref([])
const filterDomain = ref('')
const filterBackend = ref('')
const expandedSkillId = ref('')
const detailCache = ref({})
const loading = ref(false)
const errorMessage = ref('')

const filteredSkills = computed(() => {
  if (!skillsData.value?.skills) return []
  return skillsData.value.skills.filter((skill) => {
    if (filterDomain.value && skill.domain !== filterDomain.value) return false
    if (filterBackend.value && skill.backend !== filterBackend.value) return false
    return true
  })
})

function domainLabel(domain) {
  if (domain === '*') return '通用'
  return String(domain || '').toUpperCase()
}

function backendLabel(backend) {
  return backend === 'local' ? '本地' : 'Refly'
}

function categoryLabel(category) {
  const labels = {
    extraction: '提取',
    comparison: '对比',
    validation: '校验',
    general: '通用'
  }
  return labels[category] || category || '通用'
}

function currentDetail(skillId) {
  return detailCache.value[skillId] || null
}

async function loadSkills() {
  loading.value = true
  errorMessage.value = ''
  try {
    skillsData.value = await fetchSkills()
    const domainsResp = await fetchDomains()
    domains.value = domainsResp?.domains || []
  } catch (error) {
    errorMessage.value = error?.message || '加载 Skills 失败'
  } finally {
    loading.value = false
  }
}

async function toggleDetail(skillId) {
  if (expandedSkillId.value === skillId) {
    expandedSkillId.value = ''
    return
  }
  expandedSkillId.value = skillId

  if (detailCache.value[skillId]) {
    return
  }

  try {
    const detail = await fetchSkillDetail(skillId)
    detailCache.value = {
      ...detailCache.value,
      [skillId]: detail
    }
  } catch (error) {
    detailCache.value = {
      ...detailCache.value,
      [skillId]: {
        used_by_checklist_items: [],
        error: error?.message || '详情加载失败'
      }
    }
  }
}

onMounted(() => {
  loadSkills()
})
</script>

<style scoped>
.skills-view {
  max-width: var(--max-width);
  margin: 0 auto;
  padding: var(--spacing-2) 0 var(--spacing-6);
}

.page-header {
  margin-bottom: var(--spacing-4);
}

.page-header h2 {
  margin: 0;
  font-size: var(--font-size-2xl);
  color: var(--color-text-primary);
}

.stats {
  margin-top: var(--spacing-3);
  display: flex;
  gap: var(--spacing-3);
  flex-wrap: wrap;
}

.stat-item {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: var(--spacing-1) var(--spacing-3);
}

.filter-bar {
  display: flex;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-5);
  flex-wrap: wrap;
}

.filter-select {
  min-width: 180px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  background: var(--color-bg-card);
  color: var(--color-text-primary);
  padding: var(--spacing-2) var(--spacing-3);
}

.state-text {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.state-text.error {
  color: var(--color-danger);
}

.skills-grid {
  display: grid;
  gap: var(--spacing-4);
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}

.skill-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}

.skill-card:hover {
  transform: translateY(-2px);
  border-color: var(--color-primary-lighter);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.12);
}

.skill-card.not-registered {
  opacity: 0.75;
}

.skill-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--spacing-2);
}

.skill-name {
  margin: 0;
  font-size: var(--font-size-lg);
  color: var(--color-text-primary);
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
}

.status-dot.active {
  background: #10b981;
}

.status-dot.inactive {
  background: #9ca3af;
}

.skill-id {
  margin: var(--spacing-2) 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.skill-desc {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
  min-height: 40px;
}

.skill-tags {
  margin-top: var(--spacing-3);
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
}

.tag {
  font-size: var(--font-size-xs);
  border-radius: 999px;
  padding: 4px 10px;
  border: 1px solid transparent;
}

.tag.domain {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.tag.backend {
  background: #ecfdf5;
  color: #047857;
  border-color: #a7f3d0;
}

.tag.category {
  background: #fff7ed;
  color: #c2410c;
  border-color: #fed7aa;
}

.skill-detail {
  margin-top: var(--spacing-3);
  padding-top: var(--spacing-3);
  border-top: 1px dashed var(--color-border-light);
  display: grid;
  gap: var(--spacing-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

@media (max-width: 768px) {
  .filter-select {
    width: 100%;
  }
}
</style>
