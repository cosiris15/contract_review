<template>
  <el-dialog
    v-model="visible"
    title="选择您的身份"
    width="500px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
  >
    <div class="party-select-content">
      <p class="hint-text">
        系统已识别出文档中的各方，请选择您代表的一方：
      </p>

      <div class="party-list">
        <div
          v-for="(party, index) in parties"
          :key="index"
          class="party-item"
          :class="{ selected: selectedIndex === index }"
          @click="selectedIndex = index"
        >
          <div class="party-radio">
            <el-icon v-if="selectedIndex === index" color="#409eff" :size="20">
              <CircleCheckFilled />
            </el-icon>
            <el-icon v-else color="#c0c4cc" :size="20">
              <CirclePlus />
            </el-icon>
          </div>
          <div class="party-info">
            <div class="party-role">{{ party.role }}</div>
            <div class="party-name">{{ party.name }}</div>
            <div v-if="party.description" class="party-desc">{{ party.description }}</div>
          </div>
        </div>
      </div>

      <!-- 手动输入选项 -->
      <div
        class="party-item manual-input"
        :class="{ selected: selectedIndex === -1 }"
        @click="selectedIndex = -1"
      >
        <div class="party-radio">
          <el-icon v-if="selectedIndex === -1" color="#409eff" :size="20">
            <CircleCheckFilled />
          </el-icon>
          <el-icon v-else color="#c0c4cc" :size="20">
            <CirclePlus />
          </el-icon>
        </div>
        <div class="party-info">
          <div class="party-role">其他（手动输入）</div>
          <el-input
            v-if="selectedIndex === -1"
            v-model="customParty"
            placeholder="请输入您的身份"
            size="small"
            style="margin-top: 8px"
          />
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button type="primary" :disabled="!canConfirm" @click="handleConfirm">
        确认
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { CircleCheckFilled, CirclePlus } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  parties: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const selectedIndex = ref(0)
const customParty = ref('')

// 当对话框打开时重置选择
watch(() => props.modelValue, (val) => {
  if (val) {
    selectedIndex.value = props.parties.length > 0 ? 0 : -1
    customParty.value = ''
  }
})

const canConfirm = computed(() => {
  if (selectedIndex.value === -1) {
    return customParty.value.trim().length > 0
  }
  return selectedIndex.value >= 0 && selectedIndex.value < props.parties.length
})

function handleConfirm() {
  let selectedParty = ''

  if (selectedIndex.value === -1) {
    selectedParty = customParty.value.trim()
  } else if (props.parties[selectedIndex.value]) {
    const party = props.parties[selectedIndex.value]
    // 组合角色和名称
    selectedParty = party.name !== '未指明' ? party.name : party.role
  }

  emit('confirm', selectedParty)
  visible.value = false
}

function handleCancel() {
  emit('cancel')
  visible.value = false
}
</script>

<style scoped>
.party-select-content {
  padding: var(--spacing-2) 0;
}

.hint-text {
  margin: 0 0 var(--spacing-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.party-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.party-item {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-4);
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.party-item:hover {
  border-color: var(--color-primary-lighter);
  background: var(--color-bg-hover);
}

.party-item.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.party-radio {
  flex-shrink: 0;
  padding-top: 2px;
}

.party-info {
  flex: 1;
  min-width: 0;
}

.party-role {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
}

.party-name {
  margin-top: 2px;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.party-desc {
  margin-top: 4px;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.manual-input {
  margin-top: var(--spacing-2);
  border-style: dashed;
}
</style>
