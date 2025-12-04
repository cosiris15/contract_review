<template>
  <el-dialog
    v-model="visible"
    title="选择您的身份"
    width="600px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
  >
    <div class="party-select-content">
      <!-- 根据是否有识别结果显示不同提示 -->
      <p class="hint-text" v-if="parties.length > 0">
        系统已识别出文档中的各方，请选择您代表的一方：
      </p>
      <p class="hint-text" v-else>
        未能自动识别合同各方，请手动输入您的身份（如：甲方、买方、XX公司）：
      </p>

      <!-- 识别到的各方列表 -->
      <div class="party-list" v-if="parties.length > 0">
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
        :class="{ selected: selectedIndex === -1, 'no-parties': parties.length === 0 }"
        @click="handleManualInputClick"
      >
        <div class="party-radio" v-if="parties.length > 0">
          <el-icon v-if="selectedIndex === -1" color="#409eff" :size="20">
            <CircleCheckFilled />
          </el-icon>
          <el-icon v-else color="#c0c4cc" :size="20">
            <CirclePlus />
          </el-icon>
        </div>
        <div class="party-info" :class="{ 'full-width': parties.length === 0 }">
          <div class="party-role" v-if="parties.length > 0">其他（手动输入）</div>
          <el-input
            ref="customInputRef"
            v-model="customParty"
            :placeholder="parties.length > 0 ? '请输入您的身份' : '例如：甲方、买方、XX科技有限公司'"
            size="default"
            :style="{ marginTop: parties.length > 0 ? '8px' : '0' }"
            @focus="selectedIndex = -1"
          />
        </div>
      </div>

      <!-- 文档预览区域 -->
      <div class="preview-section" v-if="documentPreview">
        <div class="preview-header" @click="showPreview = !showPreview">
          <el-icon :class="{ 'is-rotated': showPreview }"><ArrowRight /></el-icon>
          <span>查看文档开头内容</span>
        </div>
        <el-collapse-transition>
          <div v-show="showPreview" class="preview-content">
            <pre>{{ documentPreview }}</pre>
          </div>
        </el-collapse-transition>
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
import { ref, computed, watch, nextTick } from 'vue'
import { CircleCheckFilled, CirclePlus, ArrowRight } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false
  },
  parties: {
    type: Array,
    default: () => []
  },
  documentPreview: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:modelValue', 'confirm', 'cancel'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const selectedIndex = ref(0)
const customParty = ref('')
const showPreview = ref(false)
const customInputRef = ref(null)

// 当对话框打开时重置选择
watch(() => props.modelValue, (val) => {
  if (val) {
    if (props.parties.length > 0) {
      selectedIndex.value = 0
    } else {
      // 没有识别到选项时，自动选中手动输入并聚焦
      selectedIndex.value = -1
      nextTick(() => {
        customInputRef.value?.focus()
      })
    }
    customParty.value = ''
    showPreview.value = false
  }
})

const canConfirm = computed(() => {
  if (selectedIndex.value === -1) {
    return customParty.value.trim().length > 0
  }
  return selectedIndex.value >= 0 && selectedIndex.value < props.parties.length
})

function handleManualInputClick() {
  selectedIndex.value = -1
  nextTick(() => {
    customInputRef.value?.focus()
  })
}

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

.party-info.full-width {
  width: 100%;
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

.manual-input.no-parties {
  border-style: solid;
  margin-top: 0;
}

/* 文档预览区域 */
.preview-section {
  margin-top: var(--spacing-4);
  border-top: 1px solid var(--color-border-light);
  padding-top: var(--spacing-3);
}

.preview-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  user-select: none;
}

.preview-header:hover {
  color: var(--color-primary);
}

.preview-header .el-icon {
  transition: transform 0.2s;
}

.preview-header .el-icon.is-rotated {
  transform: rotate(90deg);
}

.preview-content {
  margin-top: var(--spacing-2);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-sm);
  max-height: 200px;
  overflow-y: auto;
}

.preview-content pre {
  margin: 0;
  font-size: var(--font-size-xs);
  line-height: 1.6;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  font-family: inherit;
}
</style>
