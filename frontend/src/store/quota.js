import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/api'

export const useQuotaStore = defineStore('quota', () => {
  // 状态
  const quota = ref(null)
  const isLoading = ref(false)
  const error = ref(null)

  // 计算属性
  const creditsBalance = computed(() => quota.value?.credits_balance ?? 0)
  const planTier = computed(() => quota.value?.plan_tier ?? 'unknown')
  const totalUsage = computed(() => quota.value?.total_usage ?? 0)
  const billingEnabled = computed(() => quota.value?.billing_enabled ?? false)
  const hasQuota = computed(() => creditsBalance.value > 0)
  const isUnlimited = computed(() => planTier.value === 'unlimited')

  // 获取配额信息
  async function fetchQuota() {
    isLoading.value = true
    error.value = null

    try {
      const response = await api.getQuota()
      quota.value = response.data
      return quota.value
    } catch (err) {
      console.error('[QuotaStore] 获取配额失败:', err)
      error.value = err.message || '获取配额失败'
      // 出错时不阻断业务，返回默认值
      quota.value = {
        credits_balance: 0,
        plan_tier: 'error',
        total_usage: 0,
        billing_enabled: false
      }
      return quota.value
    } finally {
      isLoading.value = false
    }
  }

  // 刷新配额（用于任务完成后）
  async function refreshQuota() {
    return await fetchQuota()
  }

  // 重置状态
  function reset() {
    quota.value = null
    error.value = null
  }

  return {
    // 状态
    quota,
    isLoading,
    error,
    // 计算属性
    creditsBalance,
    planTier,
    totalUsage,
    billingEnabled,
    hasQuota,
    isUnlimited,
    // 方法
    fetchQuota,
    refreshQuota,
    reset
  }
})
