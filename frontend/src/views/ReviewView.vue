<template>
  <div class="review-view">
    <!-- AI 整合特殊要求时的全屏加载遮罩 -->
    <transition name="fade">
      <div v-if="merging" class="ai-processing-overlay">
        <div class="ai-processing-card">
          <div class="ai-icon-wrapper">
            <el-icon class="ai-icon-spin" :size="48"><MagicStick /></el-icon>
          </div>
          <h3 class="ai-title">AI 正在整合特殊要求</h3>
          <p class="ai-desc">正在分析您的特殊要求，智能调整审核标准...</p>
          <div class="ai-progress">
            <div class="ai-progress-bar"></div>
          </div>
          <p class="ai-hint">预计需要 30-60 秒，请耐心等待</p>
        </div>
      </div>
    </transition>

    <!-- 全局操作状态提示 -->
    <transition name="fade">
      <div v-if="store.isOperationInProgress" class="operation-status-bar">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ store.currentOperationMessage }}</span>
      </div>
    </transition>

    <!-- 配额不足提示 -->
    <div
      v-if="store.operationError?.type === 'quota_exceeded' && !store.isOperationInProgress"
      class="quota-exceeded-alert"
    >
      <div class="quota-icon">
        <el-icon :size="32" color="#E6A23C"><Warning /></el-icon>
      </div>
      <div class="quota-content">
        <h4>免费额度已用完</h4>
        <p>您的免费试用额度已全部使用完毕。如需继续使用，请联系我们获取更多额度。</p>
        <div class="quota-actions">
          <el-button type="warning" @click="contactUs">联系我们</el-button>
          <el-button @click="clearError">我知道了</el-button>
        </div>
      </div>
    </div>

    <!-- 错误提示 -->
    <el-alert
      v-else-if="store.operationError && !store.isOperationInProgress"
      type="error"
      :title="store.operationError.message"
      :description="store.operationError.detail"
      show-icon
      closable
      class="error-alert"
      @close="clearError"
    />

    <el-row :gutter="24">
      <!-- 左侧面板：配置区 -->
      <el-col :span="10">
        <el-card class="config-card">
          <template #header>
            <div class="card-header">
              <span>审阅配置</span>
            </div>
          </template>

          <!-- 步骤 1: 上传文档（简化流程，先上传再识别） -->
          <div class="upload-section">
            <h4>
              <el-icon><Document /></el-icon>
              上传待审阅文档
            </h4>
            <el-upload
              class="upload-box"
              drag
              :auto-upload="false"
              :show-file-list="false"
              :on-change="handleDocumentChange"
              :disabled="preprocessing"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.docx,.xlsx,.md,.txt"
            >
              <!-- 预处理中 -->
              <div v-if="preprocessing" class="preprocessing-status">
                <el-icon :size="40" class="is-loading"><Loading /></el-icon>
                <p>正在分析文档...</p>
                <span>识别合同各方和文档类型</span>
              </div>
              <!-- 已上传 -->
              <div v-else-if="currentTask?.document_filename" class="uploaded-file">
                <el-icon :size="40" color="#67c23a"><DocumentChecked /></el-icon>
                <span>{{ currentTask.document_filename }}</span>
                <div class="uploaded-file-actions">
                  <el-button type="primary" text size="small">重新上传</el-button>
                  <el-button type="danger" text size="small" @click.stop="handleClearDocument">取消</el-button>
                </div>
              </div>
              <!-- 未上传 -->
              <div v-else class="upload-placeholder">
                <el-icon :size="40"><UploadFilled /></el-icon>
                <p>拖拽文件到此处或点击上传</p>
                <span>支持 PDF、图片、Word、Excel、Markdown 格式</span>
              </div>
            </el-upload>

            <!-- 已识别的信息展示 -->
            <div v-if="currentTask?.our_party && !preprocessing" class="recognized-info">
              <el-descriptions :column="2" size="small" border>
                <el-descriptions-item label="任务名称">
                  {{ currentTask.name || '未命名' }}
                </el-descriptions-item>
                <el-descriptions-item label="我方身份">
                  {{ currentTask.our_party }}
                </el-descriptions-item>
                <el-descriptions-item label="材料类型">
                  {{ currentTask.material_type === 'contract' ? '合同' : '营销材料' }}
                </el-descriptions-item>
                <el-descriptions-item label="审阅语言">
                  {{ currentTask.language === 'zh-CN' ? '中文' : 'English' }}
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </div>

          <!-- 审阅重点输入（上传文档后显示，可选填写） -->
          <div v-if="currentTask?.document_filename && !preprocessing" class="business-context-section">
            <div class="context-header">
              <el-icon><Edit /></el-icon>
              <span class="context-title">您的审阅重点</span>
              <span class="context-optional">（可选）</span>
            </div>
            <el-input
              v-model="specialRequirements"
              type="textarea"
              :rows="3"
              :autosize="{ minRows: 2, maxRows: 6 }"
              placeholder="告诉 AI 您最关心什么，帮助审阅更精准。例如：&#10;• 重点关注付款条款和违约责任&#10;• 本项目为政府采购，需特别注意合规要求"
            />
            <div v-if="specialRequirements.trim()" class="context-hint">
              <el-icon color="#67c23a"><CircleCheck /></el-icon>
              <span>审阅时将重点关注您指定的内容</span>
            </div>
          </div>

          <el-divider />

          <!-- 高级选项（默认折叠） -->
          <div class="advanced-options-section">
            <div
              class="advanced-options-header"
              :class="{ expanded: showAdvancedOptions, 'has-selection': hasAdvancedSelection }"
              @click="showAdvancedOptions = !showAdvancedOptions"
            >
              <div class="header-left">
                <el-icon><Setting /></el-icon>
                <span class="header-title">高级选项</span>
                <span class="header-subtitle">审阅标准、业务条线</span>
              </div>
              <div class="header-right">
                <template v-if="hasAdvancedSelection">
                  <el-tag v-if="selectedStandards.length" size="small" type="success">
                    {{ selectedStandards.length }} 条标准
                  </el-tag>
                  <el-tag v-if="selectedBusinessLineId" size="small" type="info">
                    业务条线
                  </el-tag>
                </template>
                <el-icon class="expand-icon" :class="{ expanded: showAdvancedOptions }">
                  <ArrowDown />
                </el-icon>
              </div>
            </div>

            <el-collapse-transition>
              <div v-show="showAdvancedOptions" class="advanced-options-content">
                <!-- 审阅标准与业务条线选择入口 -->
                <div class="requirement-selection-entry">
                  <el-button type="primary" @click="openStandardSelector">
                    <el-icon><Collection /></el-icon>
                    审阅标准
                    <el-tag v-if="selectedStandards.length" size="small" type="success" class="btn-tag">
                      {{ selectedStandards.length }}
                    </el-tag>
                  </el-button>
                  <el-button @click="openBusinessSelector">
                    <el-icon><Briefcase /></el-icon>
                    业务条线
                    <el-tag v-if="selectedBusinessLineId" size="small" type="success" class="btn-tag">
                      1
                    </el-tag>
                  </el-button>
                </div>

                <!-- 隐藏的上传组件 -->
                <el-upload
                  ref="standardUploadRef"
                  :auto-upload="false"
                  :show-file-list="false"
                  :on-change="handleStandardUpload"
                  accept=".xlsx,.xls,.csv,.docx,.md,.txt"
                  style="display: none;"
                />

                <!-- 已选标准显示 -->
                <div v-if="selectedStandards.length > 0" class="selected-standards-section">
                  <div class="selected-header">
                    <span class="selected-label">已选标准</span>
                    <el-tag type="success" size="small">{{ selectedStandards.length }} 条</el-tag>
                    <el-button text type="primary" size="small" @click="showStandardPreview = true">
                      查看详情
                    </el-button>
                  </div>
                  <div class="selected-tags">
                    <el-tag
                      v-for="s in selectedStandards.slice(0, 6)"
                      :key="s.id || s.item"
                      size="small"
                      style="margin: 2px"
                    >
                      {{ s.item }}
                    </el-tag>
                    <span v-if="selectedStandards.length > 6" class="more-count">
                      +{{ selectedStandards.length - 6 }} 条
                    </span>
                  </div>
                </div>

                <!-- 当前应用的标准状态 -->
                <div v-if="currentTask?.standard_filename" class="applied-standard">
                  <el-icon color="#67c23a"><CircleCheck /></el-icon>
                  <span>已应用: {{ currentTask.standard_filename }}</span>
                  <el-button text type="primary" size="small" @click="reselect">重新选择</el-button>
                </div>
              </div>
            </el-collapse-transition>
          </div>

          <!-- 标准推荐对话框 -->
          <el-dialog
            v-model="showRecommendDialog"
            title="智能推荐标准"
            width="700px"
          >
            <div v-if="recommendations.length">
              <el-alert type="info" :closable="false" style="margin-bottom: 16px">
                根据您上传的文档，推荐以下审核标准：
              </el-alert>

              <div class="recommend-list">
                <div
                  v-for="rec in recommendations"
                  :key="rec.standard_id"
                  class="recommend-item"
                  :class="{ selected: isStandardSelected(rec.standard_id) }"
                  @click="toggleStandard(rec)"
                >
                  <el-checkbox :model-value="isStandardSelected(rec.standard_id)" />
                  <div class="recommend-content">
                    <div class="recommend-header">
                      <span class="recommend-title">{{ rec.standard.item }}</span>
                      <el-tag size="small" :type="getRelevanceType(rec.relevance_score)">
                        相关度 {{ Math.round(rec.relevance_score * 100) }}%
                      </el-tag>
                    </div>
                    <p class="recommend-reason">{{ rec.match_reason }}</p>
                    <p class="recommend-desc">{{ rec.standard.description }}</p>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无推荐结果" />

            <template #footer>
              <el-button @click="showRecommendDialog = false">取消</el-button>
              <el-button type="primary" @click="confirmRecommendation">
                确认选择 ({{ selectedLibraryStandards.length }})
              </el-button>
            </template>
          </el-dialog>

          <!-- 标准集合选择对话框 -->
          <el-dialog
            v-model="showLibrarySelector"
            title="选择审核标准"
            width="800px"
          >
            <div class="library-selector">
              <!-- 搜索框和操作按钮 -->
              <div class="selector-header">
                <el-input
                  v-model="collectionSearch"
                  placeholder="搜索标准..."
                  clearable
                  style="flex: 1"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <el-button
                  type="success"
                  @click="getCollectionRecommendations"
                  :loading="recommendingCollections"
                  :disabled="!currentTask?.document_filename"
                >
                  <el-icon><MagicStick /></el-icon>
                  智能推荐
                </el-button>
                <el-dropdown trigger="click" @command="handleNewStandardInReview">
                  <el-button type="primary">
                    <el-icon><Plus /></el-icon>
                    新建标准
                    <el-icon class="el-icon--right"><ArrowDown /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="upload">
                        <el-icon><UploadFilled /></el-icon>
                        上传新标准
                      </el-dropdown-item>
                      <el-dropdown-item command="ai">
                        <el-icon><MagicStick /></el-icon>
                        AI辅助制作
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>

              <!-- 智能推荐结果 -->
              <div v-if="collectionRecommendations.length > 0" class="recommendation-section">
                <div class="recommendation-header">
                  <el-icon color="#67c23a"><MagicStick /></el-icon>
                  <span>智能推荐</span>
                  <el-button text type="info" size="small" @click="collectionRecommendations = []">
                    清除推荐
                  </el-button>
                </div>
                <div class="recommendation-list">
                  <div
                    v-for="rec in collectionRecommendations"
                    :key="rec.collection_id"
                    class="recommendation-card"
                    :class="{ selected: selectedCollection?.id === rec.collection_id }"
                    @click="selectRecommendedCollection(rec)"
                  >
                    <div class="rec-header">
                      <span class="rec-name">{{ rec.collection_name }}</span>
                      <el-tag type="success" size="small">
                        相关度 {{ Math.round(rec.relevance_score * 100) }}%
                      </el-tag>
                    </div>
                    <p class="rec-reason">{{ rec.match_reason }}</p>
                    <div class="rec-meta">
                      <el-tag size="small" type="info">{{ rec.standard_count }} 条审核条目</el-tag>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 标准集合列表 -->
              <div class="collection-list">
                <div
                  v-for="collection in filteredCollections"
                  :key="collection.id"
                  class="collection-card-dialog"
                  :class="{ selected: selectedCollection?.id === collection.id }"
                  @click="selectCollectionInDialog(collection)"
                >
                  <div class="collection-card-header">
                    <el-icon :size="24" :color="selectedCollection?.id === collection.id ? '#409eff' : '#909399'">
                      <Folder />
                    </el-icon>
                    <div class="collection-info">
                      <span class="collection-name">{{ collection.name }}</span>
                      <span class="collection-meta">
                        <el-tag size="small" type="info">{{ collection.standard_count }} 条审核条目</el-tag>
                        <el-tag v-if="collection.is_preset" size="small" type="success">预设</el-tag>
                      </span>
                    </div>
                    <el-icon v-if="selectedCollection?.id === collection.id" class="check-icon" color="#409eff">
                      <CircleCheck />
                    </el-icon>
                  </div>
                  <p v-if="collection.description" class="collection-desc">{{ collection.description }}</p>
                </div>

                <el-empty v-if="filteredCollections.length === 0" description="暂无标准">
                  <el-button type="primary" @click="goToStandardsManagement">
                    前往标准管理
                  </el-button>
                </el-empty>
              </div>

              <!-- 当前选择状态 -->
              <div v-if="selectedCollection" class="selection-summary">
                <el-icon><InfoFilled /></el-icon>
                <span>已选择「{{ selectedCollection.name }}」，共 {{ selectedCollection.standard_count }} 条审核条目</span>
              </div>
            </div>

            <template #footer>
              <el-button @click="showLibrarySelector = false">取消</el-button>
              <el-button type="primary" @click="confirmCollectionSelection" :disabled="!selectedCollection">
                确认选择
              </el-button>
            </template>
          </el-dialog>

          <!-- 标准预览对话框 -->
          <el-dialog
            v-model="showStandardPreview"
            title="已选审核标准"
            width="750px"
          >
            <el-table :data="selectedStandards" max-height="450">
              <el-table-column prop="category" label="分类" width="100" />
              <el-table-column prop="item" label="审核要点" width="150" />
              <el-table-column prop="description" label="详细说明" show-overflow-tooltip />
              <el-table-column label="风险" width="60" align="center">
                <template #default="{ row }">
                  <el-tag :type="getRiskTagType(row.risk_level)" size="small">
                    {{ getRiskLabel(row.risk_level) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <template #footer>
              <el-button @click="showStandardPreview = false">关闭</el-button>
              <el-button type="primary" @click="applyStandards" :loading="applyingStandards">
                应用标准
              </el-button>
            </template>
          </el-dialog>

          <!-- 整合预览对话框 -->
          <el-dialog
            v-model="showMergePreview"
            title="标准整合预览"
            width="850px"
            :close-on-click-modal="false"
          >
            <div class="merge-preview">
              <!-- 整合摘要 -->
              <div class="merge-summary">
                <el-alert :title="mergeResult?.merge_notes" type="info" :closable="false" show-icon />
                <div class="summary-stats">
                  <el-tag type="success">
                    <el-icon><CirclePlus /></el-icon>
                    新增 {{ mergeResult?.summary?.added_count || 0 }} 条
                  </el-tag>
                  <el-tag type="warning">
                    <el-icon><Edit /></el-icon>
                    修改 {{ mergeResult?.summary?.modified_count || 0 }} 条
                  </el-tag>
                  <el-tag type="danger">
                    <el-icon><Remove /></el-icon>
                    删除 {{ mergeResult?.summary?.removed_count || 0 }} 条
                  </el-tag>
                  <el-tag type="info">
                    <el-icon><Check /></el-icon>
                    未变 {{ mergeResult?.summary?.unchanged_count || 0 }} 条
                  </el-tag>
                </div>
              </div>

              <!-- 标准列表 -->
              <div class="merge-standards-list">
                <div
                  v-for="(s, idx) in mergeResult?.merged_standards || []"
                  :key="idx"
                  class="merge-standard-item"
                  :class="s.change_type"
                >
                  <div class="standard-change-badge">
                    <el-tag
                      :type="getChangeTagType(s.change_type)"
                      size="small"
                    >
                      {{ getChangeLabel(s.change_type) }}
                    </el-tag>
                  </div>
                  <div class="standard-content">
                    <div class="standard-header">
                      <span class="standard-category">{{ s.category }}</span>
                      <span class="standard-item">{{ s.item }}</span>
                      <el-tag :type="getRiskTagType(s.risk_level)" size="small">
                        {{ getRiskLabel(s.risk_level) }}
                      </el-tag>
                    </div>
                    <p class="standard-desc">{{ s.description }}</p>
                    <p v-if="s.change_reason" class="change-reason">
                      <el-icon><InfoFilled /></el-icon>
                      {{ s.change_reason }}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <template #footer>
              <el-button @click="cancelMerge">取消，保留原标准</el-button>
              <el-button type="primary" @click="applyMergedStandards">
                应用整合后的标准
              </el-button>
            </template>
          </el-dialog>

          <!-- 业务条线选择对话框 -->
          <el-dialog
            v-model="showBusinessLineDialog"
            title="选择业务条线"
            width="800px"
          >
            <div class="business-selector">
              <!-- 搜索框和操作按钮 -->
              <div class="selector-header">
                <el-input
                  v-model="businessLineSearch"
                  placeholder="搜索业务条线..."
                  clearable
                  style="flex: 1"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <router-link to="/business">
                  <el-button type="primary">
                    <el-icon><Plus /></el-icon>
                    管理业务条线
                  </el-button>
                </router-link>
              </div>

              <!-- 提示说明 -->
              <el-alert
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 16px"
              >
                选择业务条线后，审阅时将根据业务背景信息提供更有针对性的建议（可选）
              </el-alert>

              <!-- 业务条线列表 -->
              <div class="business-line-list" v-loading="loadingBusinessLines">
                <div
                  v-for="line in filteredBusinessLines"
                  :key="line.id"
                  class="business-line-card"
                  :class="{ selected: tempSelectedBusinessLineId === line.id }"
                  @click="selectBusinessLineInDialog(line)"
                >
                  <div class="business-line-header">
                    <el-icon :size="24" :color="tempSelectedBusinessLineId === line.id ? '#409eff' : '#909399'">
                      <Briefcase />
                    </el-icon>
                    <div class="business-line-info">
                      <span class="business-line-name">{{ line.name }}</span>
                      <span class="business-line-meta">
                        <el-tag size="small" type="info">{{ line.context_count }} 条背景信息</el-tag>
                        <el-tag v-if="line.is_preset" size="small" type="success">预设</el-tag>
                        <el-tag v-if="line.industry" size="small">{{ line.industry }}</el-tag>
                      </span>
                    </div>
                    <el-icon v-if="tempSelectedBusinessLineId === line.id" class="check-icon" color="#409eff">
                      <CircleCheck />
                    </el-icon>
                  </div>
                  <p v-if="line.description" class="business-line-desc">{{ line.description }}</p>
                </div>

                <el-empty v-if="filteredBusinessLines.length === 0 && !loadingBusinessLines" description="暂无业务条线">
                  <router-link to="/business">
                    <el-button type="primary">前往创建</el-button>
                  </router-link>
                </el-empty>
              </div>

              <!-- 当前选择状态 -->
              <div v-if="tempSelectedBusinessLine" class="selection-summary">
                <el-icon><InfoFilled /></el-icon>
                <span>已选择「{{ tempSelectedBusinessLine.name }}」，共 {{ tempSelectedBusinessLine.context_count }} 条背景信息</span>
              </div>
            </div>

            <template #footer>
              <el-button @click="showBusinessLineDialog = false">取消</el-button>
              <el-button v-if="selectedBusinessLineId" type="danger" text @click="clearBusinessLineSelection">
                清除选择
              </el-button>
              <el-button type="primary" @click="confirmBusinessLineSelection">
                确认选择
              </el-button>
            </template>
          </el-dialog>

          <el-divider />

          <!-- 开始审阅按钮 -->
          <el-button
            type="primary"
            size="large"
            class="start-btn"
            :loading="store.isReviewing"
            :disabled="!canStart"
            @click="startReview"
          >
            <template v-if="store.isReviewing">
              审阅中...
            </template>
            <template v-else>
              开始审阅
            </template>
          </el-button>

          <!-- 模式提示 -->
          <div class="mode-hint" v-if="!store.isReviewing">
            <el-icon><InfoFilled /></el-icon>
            <span v-if="selectedStandards.length">将基于已选标准进行审阅</span>
            <span v-else>默认使用 AI 智能审阅，无需选择标准</span>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧面板：进度/结果预览 -->
      <el-col :span="14">
        <el-card class="progress-card">
          <template #header>
            <div class="card-header">
              <span>审阅进度</span>
            </div>
          </template>

          <!-- 等待状态 -->
          <div v-if="!store.isReviewing && !isCompleted" class="waiting-state">
            <el-empty description="完成配置后点击开始审阅">
              <template #image>
                <el-icon :size="80" color="#909399"><Document /></el-icon>
              </template>
            </el-empty>
          </div>

          <!-- 审阅进度 -->
          <div v-else-if="store.isReviewing" class="progress-state">
            <div class="progress-content">
              <el-progress
                type="circle"
                :percentage="store.progress.percentage"
                :width="150"
                :stroke-width="10"
              />
              <div class="progress-info">
                <h3>{{ stageText }}</h3>
                <p>{{ store.progress.message }}</p>
              </div>
            </div>
            <div class="progress-steps">
              <el-steps :active="activeStep" align-center>
                <el-step title="分析文档" />
                <el-step title="识别风险" />
                <el-step title="生成建议" />
                <el-step title="完成" />
              </el-steps>
            </div>
          </div>

          <!-- 完成状态 -->
          <div v-else-if="isCompleted" class="completed-state">
            <el-result icon="success" title="审阅完成">
              <template #sub-title>
                <p v-if="store.reviewResult">
                  发现 {{ store.reviewResult.summary.total_risks }} 个风险点，
                  生成 {{ store.reviewResult.summary.total_modifications }} 条修改建议
                </p>
              </template>
              <template #extra>
                <el-button type="primary" @click="goToResult">
                  查看完整结果
                </el-button>
              </template>
            </el-result>
          </div>

          <!-- 失败状态 -->
          <div v-else-if="isFailed" class="failed-state">
            <el-result icon="error" title="审阅失败">
              <template #sub-title>
                <p>{{ currentTask?.message || '发生未知错误' }}</p>
              </template>
              <template #extra>
                <el-button type="primary" @click="retryReview">重试</el-button>
              </template>
            </el-result>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 身份选择弹窗 -->
    <PartySelectDialog
      v-model="showPartySelectDialog"
      :parties="recognizedParties"
      :document-preview="documentPreview"
      @confirm="handlePartySelected"
      @cancel="handlePartySelectCancel"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useReviewStore } from '@/store'
import { ElMessage } from 'element-plus'
import { Loading, Search, Folder, CircleCheck, InfoFilled, Briefcase, Plus, Warning, Setting } from '@element-plus/icons-vue'
import api from '@/api'
import interactiveApi from '@/api/interactive'
import PartySelectDialog from '@/components/common/PartySelectDialog.vue'

const route = useRoute()
const router = useRouter()
const store = useReviewStore()

const formRef = ref(null)
const standardUploadRef = ref(null)
const taskId = ref(route.params.taskId || null)

const form = ref({
  name: '',
  our_party: '',
  material_type: 'contract',
  language: 'zh-CN'
})

// 语言检测相关状态
const detectedLanguage = ref(null)
const detectedConfidence = ref(0)

// 文档预处理相关状态
const preprocessing = ref(false)
const showPartySelectDialog = ref(false)
const recognizedParties = ref([])
const documentPreview = ref('')  // 文档开头预览内容
const preprocessResult = ref(null)
const pendingFile = ref(null) // 暂存待上传的文件

const rules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  our_party: [{ required: true, message: '请输入我方身份', trigger: 'blur' }]
}

// 标准集合相关状态
const collections = ref([])
const selectedCollection = ref(null)
const selectedStandards = ref([]) // 当前选中的标准列表（来自集合）

// 标准选择相关状态
const showLibrarySelector = ref(false)
const collectionSearch = ref('')
const applyingStandards = ref(false)
const showStandardPreview = ref(false)

// 高级选项（默认折叠）
const showAdvancedOptions = ref(false)
const hasAdvancedSelection = computed(() => {
  return selectedStandards.value.length > 0 || selectedBusinessLineId.value
})

// 业务背景/特殊要求（已移到上传区域后面，简化了相关状态）
const specialRequirements = ref('')
const specialReqMode = ref('direct') // 保持 'direct' 模式，简化用户体验
const merging = ref(false)
const mergeResult = ref(null)

// 推荐相关
const recommending = ref(false)
const showRecommendDialog = ref(false)
const recommendations = ref([])
const selectedLibraryStandards = ref([])

// 集合推荐相关
const recommendingCollections = ref(false)
const collectionRecommendations = ref([])

// 业务条线相关状态
const showBusinessLineDialog = ref(false)
const businessLineSearch = ref('')
const businessLines = ref([])
const loadingBusinessLines = ref(false)
const selectedBusinessLineId = ref(null)
const tempSelectedBusinessLineId = ref(null)

const selectedBusinessLine = computed(() => {
  if (!selectedBusinessLineId.value) return null
  return businessLines.value.find(line => line.id === selectedBusinessLineId.value)
})

const tempSelectedBusinessLine = computed(() => {
  if (!tempSelectedBusinessLineId.value) return null
  return businessLines.value.find(line => line.id === tempSelectedBusinessLineId.value)
})

const filteredBusinessLines = computed(() => {
  if (!businessLineSearch.value) return businessLines.value
  const keyword = businessLineSearch.value.toLowerCase()
  return businessLines.value.filter(line =>
    line.name.toLowerCase().includes(keyword) ||
    (line.description && line.description.toLowerCase().includes(keyword)) ||
    (line.industry && line.industry.toLowerCase().includes(keyword))
  )
})

const currentTask = computed(() => store.currentTask)
const isCompleted = computed(() => currentTask.value?.status === 'completed')
const isFailed = computed(() => currentTask.value?.status === 'failed')

const canStart = computed(() => {
  if (!taskId.value) return false
  // 统一模式：只需要上传文档，标准可选
  return currentTask.value?.document_filename
})

const stageText = computed(() => {
  const stages = {
    idle: '准备中',
    analyzing: '分析文档',
    generating: '生成建议',
    completed: '已完成'
  }
  return stages[store.progress.stage] || '处理中'
})

const activeStep = computed(() => {
  const stage = store.progress.stage
  if (stage === 'idle') return 0
  if (stage === 'analyzing') return 1
  if (stage === 'generating') return 2
  if (stage === 'completed') return 4
  return 1
})

onMounted(async () => {
  // 加载标准集合列表
  try {
    const response = await api.getCollections()
    collections.value = response.data.map(c => ({
      id: c.id,
      name: c.name,
      description: c.description,
      material_type: c.material_type,
      standard_count: c.standard_count,
      is_preset: c.is_preset,
      standards: []  // 集合列表API不返回standards，需要单独获取
    }))
  } catch (error) {
    console.error('加载标准集合失败:', error)
  }

  // 加载业务条线列表
  loadBusinessLines()

  // 如果有 taskId，加载任务
  if (taskId.value) {
    try {
      await store.loadTask(taskId.value)
      form.value = {
        name: currentTask.value.name,
        our_party: currentTask.value.our_party,
        material_type: currentTask.value.material_type
      }

      // 如果正在审阅中，恢复轮询
      if (currentTask.value.status === 'reviewing') {
        store.isReviewing = true
        store.startPolling(taskId.value)
      }
    } catch (error) {
      ElMessage.error('加载任务失败')
      router.push('/')
    }
  }
})

// 监听路由变化
watch(() => route.params.taskId, async (newId) => {
  if (newId && newId !== taskId.value) {
    taskId.value = newId
    await store.loadTask(newId)
  }
})

async function handleDocumentChange(file) {
  // 保存待处理的文件
  pendingFile.value = file.raw

  // 如果还没有任务，先创建一个临时任务
  if (!taskId.value) {
    try {
      // 使用临时默认值创建任务
      const task = await store.createTask({
        name: '正在分析...',
        our_party: '待确认',
        material_type: form.value.material_type || 'contract',
        language: 'zh-CN' // 默认中文，后续会自动更新
      })
      taskId.value = task.id
      router.replace(`/review/${task.id}`)
    } catch (error) {
      ElMessage.error('创建任务失败')
      pendingFile.value = null
      return
    }
  }

  // 上传文档
  try {
    await store.uploadDocument(taskId.value, file.raw)
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
    pendingFile.value = null
    return
  }

  // 开始预处理
  await preprocessDocument()
}

// 文档预处理
async function preprocessDocument() {
  if (!taskId.value) return

  preprocessing.value = true
  try {
    const response = await api.preprocessDocument(taskId.value)
    preprocessResult.value = response.data

    // 保存识别到的各方和文档预览
    recognizedParties.value = response.data.parties || []
    documentPreview.value = response.data.document_preview || ''

    // 弹出选择对话框（无论是否识别到各方）
    showPartySelectDialog.value = true
  } catch (error) {
    console.error('预处理失败:', error)
    ElMessage.warning('文档分析失败，请手动输入信息')
    // 即使预处理失败，也允许用户继续
    recognizedParties.value = []
    documentPreview.value = ''
    showPartySelectDialog.value = true
  } finally {
    preprocessing.value = false
  }
}

// 用户选择身份后
async function handlePartySelected(selectedParty) {
  if (!taskId.value) return

  // 更新任务信息
  const taskName = preprocessResult.value?.suggested_name || '未命名文档'
  const language = preprocessResult.value?.language || 'zh-CN'

  try {
    // 调用 API 更新任务
    await api.updateTask(taskId.value, {
      name: taskName,
      our_party: selectedParty,
      language: language
    })

    // 更新本地状态
    if (currentTask.value) {
      currentTask.value.name = taskName
      currentTask.value.our_party = selectedParty
      currentTask.value.language = language
    }

    // 更新表单（如果需要）
    form.value.name = taskName
    form.value.our_party = selectedParty
    form.value.language = language

    ElMessage.success('已确认您的身份')

    // 清理临时状态
    pendingFile.value = null
  } catch (error) {
    console.error('更新任务失败:', error)
    ElMessage.error('保存失败，请重试')
  }
}

// 用户取消选择身份
function handlePartySelectCancel() {
  // 如果用户取消，可以考虑清除任务或保留让用户重新选择
  ElMessage.info('请选择您在合同中的身份以继续')
  // 重新显示对话框
  setTimeout(() => {
    showPartySelectDialog.value = true
  }, 500)
}

// 取消已上传的文档（清除显示状态，允许重新拖入）
function handleClearDocument() {
  if (currentTask.value) {
    currentTask.value.document_filename = null
    currentTask.value.document_storage_name = null
  }
}

// 检测文档语言
async function detectDocumentLanguage(file) {
  try {
    // 读取文件文本内容
    const text = await readFileAsText(file)
    if (!text || text.length < 50) return // 文本太短则跳过检测

    // 调用语言检测API
    const result = await api.detectLanguage(text.slice(0, 5000))
    if (result.data) {
      detectedLanguage.value = result.data.detected_language
      detectedConfidence.value = result.data.confidence

      // 如果置信度足够高且当前语言与检测结果不同，自动切换
      if (result.data.confidence > 0.7 && form.value.language !== result.data.detected_language) {
        form.value.language = result.data.detected_language
        ElMessage.info(`已根据文档内容自动切换为${result.data.detected_language === 'zh-CN' ? '中文' : 'English'}审阅模式`)
      }
    }
  } catch (error) {
    console.log('语言检测失败，使用默认语言:', error)
  }
}

// 读取文件为文本
function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => resolve(e.target.result)
    reader.onerror = reject
    // 对于 docx 和 pdf 文件，只读取部分内容
    if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
      // PDF 文件暂不支持客户端读取，跳过检测
      resolve('')
    } else if (file.name.endsWith('.docx')) {
      // docx 文件暂不支持客户端读取，跳过检测
      resolve('')
    } else {
      reader.readAsText(file)
    }
  })
}

// ==================== 集合智能推荐 ====================

// 获取集合推荐
async function getCollectionRecommendations() {
  if (!currentTask.value?.document_filename) {
    ElMessage.warning('请先上传文档')
    return
  }

  recommendingCollections.value = true
  try {
    // 从 store 获取文档文本（如果有）或使用任务信息
    const documentText = store.documentText || `文档名称: ${currentTask.value.document_filename}`

    const response = await api.recommendCollections({
      document_text: documentText.slice(0, 1000),
      material_type: form.value.material_type
    })

    collectionRecommendations.value = response.data || []

    if (collectionRecommendations.value.length === 0) {
      ElMessage.info('没有找到匹配的标准集合推荐')
    } else {
      ElMessage.success(`推荐了 ${collectionRecommendations.value.length} 个标准集合`)
    }
  } catch (error) {
    console.error('获取推荐失败:', error)
    ElMessage.error('获取推荐失败: ' + (error.message || '请重试'))
  } finally {
    recommendingCollections.value = false
  }
}

// 选择推荐的集合
async function selectRecommendedCollection(rec) {
  // 从集合列表中找到对应的集合
  let collection = collections.value.find(c => c.id === rec.collection_id)

  if (collection) {
    // 如果标准列表为空，需要从 API 获取
    if (!collection.standards || collection.standards.length === 0) {
      try {
        const response = await api.getCollection(collection.id)
        collection.standards = response.data.standards || []
        collection.standard_count = collection.standards.length
      } catch (error) {
        console.error('获取集合详情失败:', error)
        ElMessage.error('获取标准详情失败')
        return
      }
    }
    selectedCollection.value = collection
  }
}

// ==================== 标准选择相关函数 ====================

// 过滤后的集合列表
const filteredCollections = computed(() => {
  if (!collectionSearch.value) return collections.value
  const keyword = collectionSearch.value.toLowerCase()
  return collections.value.filter(c =>
    c.name.toLowerCase().includes(keyword) ||
    (c.description && c.description.toLowerCase().includes(keyword))
  )
})

// 打开标准选择对话框
function openStandardSelector() {
  // 重置对话框内的临时选择状态
  selectedCollection.value = null
  showLibrarySelector.value = true
}

// 跳转到标准管理页面
function goToStandardsManagement() {
  showLibrarySelector.value = false
  router.push({ name: 'standards' })
}

// 对话框内选择集合
async function selectCollectionInDialog(collection) {
  if (selectedCollection.value?.id === collection.id) {
    // 再次点击取消选择
    selectedCollection.value = null
  } else {
    // 如果标准列表为空，需要从API获取完整集合详情
    if (!collection.standards || collection.standards.length === 0) {
      try {
        const response = await api.getCollection(collection.id)
        collection.standards = response.data.standards || []
        collection.standard_count = collection.standards.length
      } catch (error) {
        console.error('获取集合详情失败:', error)
        ElMessage.error('获取标准详情失败')
        return
      }
    }
    selectedCollection.value = collection
  }
}

// 确认集合选择
async function confirmCollectionSelection() {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    return
  }

  if (!selectedCollection.value) {
    ElMessage.warning('请先选择标准')
    return
  }

  // 设置当前选中的标准（用于显示和特殊要求整合）
  selectedStandards.value = selectedCollection.value.standards.map(s => ({
    id: s.id,
    category: s.category,
    item: s.item,
    description: s.description,
    risk_level: s.risk_level,
    applicable_to: s.applicable_to || ['contract']
  }))

  showLibrarySelector.value = false

  // 直接应用标准到任务
  await applyStandardsImmediately(selectedStandards.value)
}

// 立即应用标准到任务
async function applyStandardsImmediately(standards) {
  applyingStandards.value = true
  try {
    // 创建 CSV 内容
    const csvContent = [
      '审核分类,审核要点,详细说明,风险等级,适用材料类型',
      ...standards.map(s =>
        `"${s.category}","${s.item}","${s.description}","${s.risk_level === 'high' ? '高' : s.risk_level === 'medium' ? '中' : '低'}","${(s.applicable_to || ['contract']).join(',')}"`
      )
    ].join('\n')

    // 创建 Blob 并上传
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' })
    const fileName = selectedCollection.value
      ? `${selectedCollection.value.name}.csv`
      : 'selected_standards.csv'
    const file = new File([blob], fileName, { type: 'text/csv' })

    await store.uploadStandard(taskId.value, file)
    ElMessage.success(`已应用 ${standards.length} 条审核标准`)
  } catch (error) {
    ElMessage.error('应用标准失败: ' + error.message)
  } finally {
    applyingStandards.value = false
  }
}


// 新建标准下拉菜单命令处理
function handleNewStandardInReview(command) {
  if (command === 'upload') {
    // 触发隐藏的上传组件
    const uploadInput = standardUploadRef.value?.$el?.querySelector('input[type="file"]')
    if (uploadInput) {
      uploadInput.click()
    }
  } else if (command === 'ai') {
    // 先关闭弹窗，再跳转到标准管理页面的AI制作功能
    showLibrarySelector.value = false
    router.push({ name: 'Standards', query: { action: 'ai-create' } })
  }
}

// 上传自定义标准文件
async function handleStandardUpload(file) {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    return
  }

  try {
    await store.uploadStandard(taskId.value, file.raw)
    selectedPresetTemplate.value = null
    selectedStandards.value = []
    ElMessage.success('审核标准上传成功')
  } catch (error) {
    ElMessage.error(error.message || '上传失败')
  }
}

// 重新选择标准
function reselect() {
  selectedCollection.value = null
  selectedStandards.value = []
  specialRequirements.value = ''
}

async function startReview() {
  if (!taskId.value) {
    ElMessage.warning('请先完成配置')
    return
  }

  try {
    // 统一使用新的审阅 API
    await startUnifiedReview()
  } catch (error) {
    ElMessage.error(error.message || '启动审阅失败')
  }
}

// 统一审阅入口
async function startUnifiedReview() {
  store.isReviewing = true

  // 判断是否使用标准（确保是布尔值）
  const hasStandards = !!(selectedStandards.value.length > 0 && currentTask.value?.standard_filename)
  const progressMessage = hasStandards ? '正在基于审核标准进行审阅...' : '正在进行 AI 自主审阅...'
  store.progress = { stage: 'analyzing', percentage: 10, message: progressMessage }

  // 如果使用"直接传递"模式且有特殊要求，传递给后端
  const directRequirements = (specialReqMode.value === 'direct' && specialRequirements.value.trim())
    ? specialRequirements.value.trim()
    : null

  const reviewOptions = {
    llmProvider: 'deepseek',
    useStandards: hasStandards,  // 现在确保是 true 或 false
    businessLineId: selectedBusinessLineId.value,
    specialRequirements: directRequirements
  }

  // 优先使用流式审阅（SSE），失败时降级为普通轮询模式
  try {
    await startStreamReview(reviewOptions)
  } catch (streamError) {
    console.warn('流式审阅失败，降级为普通模式:', streamError)
    await startFallbackReview(reviewOptions)
  }
}

// 流式审阅（SSE 模式）- 边审边看
async function startStreamReview(options) {
  let firstRiskReceived = false
  let riskCount = 0

  try {
    await interactiveApi.startUnifiedReviewStream(taskId.value, options, {
      onStart: (data) => {
        console.log('流式审阅开始:', data)
        store.progress = { stage: 'analyzing', percentage: 15, message: 'AI 正在分析文档...' }
      },

      onProgress: (data) => {
        store.progress = {
          stage: 'analyzing',
          percentage: data.percentage || 20,
          message: data.message || '正在分析...'
        }
      },

      onRisk: (data) => {
        riskCount++
        const riskData = data.data || {}
        console.log(`收到风险点 #${riskCount}:`, riskData.risk_type)

        // 第一条风险点到达时，立即跳转到交互界面
        if (!firstRiskReceived) {
          firstRiskReceived = true
          store.progress = {
            stage: 'partial_ready',
            percentage: 85,
            message: `第1条风险点已识别，可以开始处理...`
          }

          // 立即跳转（后台继续接收剩余风险）
          setTimeout(async () => {
            await store.loadTask(taskId.value)
            router.push(`/interactive/${taskId.value}`)
          }, 300)
        } else {
          // 后续风险更新进度
          store.progress = {
            stage: 'partial_ready',
            percentage: Math.min(85 + riskCount, 95),
            message: `已识别 ${riskCount} 个风险点...`
          }
        }
      },

      onComplete: async (data) => {
        console.log('流式审阅完成:', data)
        store.isReviewing = false
        store.progress = { stage: 'completed', percentage: 100, message: '审阅完成' }

        // 如果还没跳转（可能是 0 个风险的情况），现在跳转
        if (!firstRiskReceived) {
          await store.loadTask(taskId.value)
          router.push(`/interactive/${taskId.value}`)
        }
      },

      onError: (error) => {
        console.error('流式审阅错误:', error)
        // 抛出错误触发降级
        throw error
      }
    })
  } catch (error) {
    // 如果已经收到了第一条风险，说明部分成功，不需要降级
    if (firstRiskReceived) {
      console.log('流式审阅中断，但已有部分结果，继续使用')
      return
    }
    // 否则抛出错误触发降级
    throw error
  }
}

// 降级模式 - 传统轮询
async function startFallbackReview(options) {
  try {
    // 调用普通审阅 API
    await interactiveApi.startUnifiedReview(taskId.value, options)

    // 开始轮询任务状态
    pollReviewStatus()
  } catch (error) {
    store.isReviewing = false
    store.progress = { stage: 'idle', percentage: 0, message: '' }
    ElMessage.error(error.message || '启动审阅失败')
  }
}

// 轮询审阅状态
async function pollReviewStatus() {
  // 用于模拟进度的变量
  let lastServerProgress = 0
  let simulatedProgress = 0
  let stagnantCount = 0  // 服务器进度停滞的次数

  const pollInterval = setInterval(async () => {
    try {
      // 使用 getTaskStatus API 获取包含 progress 的完整状态
      const response = await api.getTaskStatus(taskId.value)
      const taskStatus = response.data

      // partial_ready: 第一条风险已就绪，可以立即跳转让用户开始工作
      if (taskStatus.status === 'partial_ready') {
        clearInterval(pollInterval)
        store.isReviewing = false
        store.progress = { stage: 'partial_ready', percentage: 95, message: '第一条已就绪，正在准备更多...' }

        // 刷新任务详情
        await store.loadTask(taskId.value)

        // 立即跳转到交互审阅页面（后台继续处理剩余风险）
        setTimeout(() => {
          router.push(`/interactive/${taskId.value}`)
        }, 500)  // 缩短等待时间，让用户更快进入
      } else if (taskStatus.status === 'completed') {
        clearInterval(pollInterval)
        store.isReviewing = false
        store.progress = { stage: 'completed', percentage: 100, message: '审阅完成' }

        // 刷新任务详情
        await store.loadTask(taskId.value)

        // 跳转到交互审阅页面（深度交互对话界面）
        setTimeout(() => {
          router.push(`/interactive/${taskId.value}`)
        }, 500)  // 缩短等待时间
      } else if (taskStatus.status === 'failed') {
        clearInterval(pollInterval)
        store.isReviewing = false
        store.progress = { stage: 'idle', percentage: 0, message: '' }
        ElMessage.error(taskStatus.message || '审阅失败')
      } else if (taskStatus.status === 'reviewing') {
        // 获取服务器返回的进度
        const progress = taskStatus.progress || {}
        const serverProgress = progress.percentage || 0

        // 模拟进度逻辑：当服务器进度停滞时，前端缓慢增加显示进度
        if (serverProgress > lastServerProgress) {
          // 服务器进度更新了，使用服务器进度
          simulatedProgress = serverProgress
          lastServerProgress = serverProgress
          stagnantCount = 0
        } else {
          // 服务器进度没变，模拟缓慢增加（但不超过下一个阶段的上限）
          stagnantCount++
          // 每次停滞增加 2-3%，但不超过90%（留给完成阶段）
          const maxSimulated = Math.min(serverProgress + stagnantCount * 2.5, 90)
          simulatedProgress = Math.min(simulatedProgress + 2, maxSimulated)
        }

        store.progress = {
          stage: progress.stage || 'analyzing',
          percentage: Math.round(simulatedProgress),
          message: progress.message || taskStatus.message || '正在分析文档...'
        }
      }
    } catch (error) {
      console.error('轮询状态失败:', error)
    }
  }, 2000)

  // 5分钟超时
  setTimeout(() => {
    clearInterval(pollInterval)
    if (store.isReviewing) {
      store.isReviewing = false
      store.progress = { stage: 'idle', percentage: 0, message: '' }
      ElMessage.error('审阅超时，请重试')
    }
  }, 5 * 60 * 1000)
}

// 加载业务条线列表
async function loadBusinessLines() {
  loadingBusinessLines.value = true
  try {
    const response = await api.getBusinessLines({ include_preset: true })
    businessLines.value = response.data
  } catch (error) {
    console.error('加载业务条线失败:', error)
  } finally {
    loadingBusinessLines.value = false
  }
}

// 打开业务条线选择对话框
function openBusinessSelector() {
  tempSelectedBusinessLineId.value = selectedBusinessLineId.value
  businessLineSearch.value = ''
  showBusinessLineDialog.value = true
  // 如果业务条线列表为空，重新加载
  if (businessLines.value.length === 0) {
    loadBusinessLines()
  }
}

// 对话框内选择业务条线
function selectBusinessLineInDialog(line) {
  if (tempSelectedBusinessLineId.value === line.id) {
    tempSelectedBusinessLineId.value = null
  } else {
    tempSelectedBusinessLineId.value = line.id
  }
}

// 确认业务条线选择
function confirmBusinessLineSelection() {
  selectedBusinessLineId.value = tempSelectedBusinessLineId.value
  showBusinessLineDialog.value = false
  if (selectedBusinessLineId.value) {
    ElMessage.success(`已选择业务条线: ${selectedBusinessLine.value?.name}`)
  }
}

// 清除业务条线选择
function clearBusinessLineSelection() {
  selectedBusinessLineId.value = null
  tempSelectedBusinessLineId.value = null
  showBusinessLineDialog.value = false
  ElMessage.info('已清除业务条线选择')
}

function retryReview() {
  store.progress = { stage: 'idle', percentage: 0, message: '' }
  if (currentTask.value) {
    currentTask.value.status = 'created'
  }
}

function goToResult() {
  // 跳转到交互审阅界面（三阶段：分析-讨论-修改）
  router.push(`/interactive/${taskId.value}`)
}

function clearError() {
  store.operationState.lastError = null
}

function contactUs() {
  window.location.href = 'mailto:support@example.com'
}

// ==================== 辅助函数 ====================

// 风险等级辅助函数
function getRiskTagType(level) {
  return { high: 'danger', medium: 'warning', low: 'success' }[level] || 'info'
}

function getRiskLabel(level) {
  return { high: '高', medium: '中', low: '低' }[level] || level
}

// 变更类型辅助函数
function getChangeTagType(changeType) {
  const types = {
    added: 'success',
    modified: 'warning',
    removed: 'danger',
    unchanged: 'info'
  }
  return types[changeType] || 'info'
}

function getChangeLabel(changeType) {
  const labels = {
    added: '新增',
    modified: '修改',
    removed: '删除',
    unchanged: '未变'
  }
  return labels[changeType] || changeType
}

// ==================== 特殊要求整合相关函数 ====================

// 整合特殊要求到标准
async function mergeSpecialRequirements() {
  if (!selectedStandards.value.length) {
    ElMessage.warning('请先选择基础标准')
    return
  }
  if (!specialRequirements.value.trim()) {
    ElMessage.warning('请输入特殊要求')
    return
  }

  merging.value = true
  try {
    const response = await api.mergeSpecialRequirements({
      standards: selectedStandards.value.map(s => ({
        category: s.category,
        item: s.item,
        description: s.description,
        risk_level: s.risk_level,
        applicable_to: s.applicable_to || ['contract']
      })),
      special_requirements: specialRequirements.value.trim(),
      our_party: form.value.our_party,
      material_type: form.value.material_type
    })
    mergeResult.value = response.data
    showMergePreview.value = true
  } catch (error) {
    ElMessage.error('整合失败: ' + (error.message || '请重试'))
  } finally {
    merging.value = false
  }
}

// 取消整合，保留原标准
function cancelMerge() {
  showMergePreview.value = false
  mergeResult.value = null
}

// 应用整合后的标准
function applyMergedStandards() {
  if (!mergeResult.value) return

  // 将整合后的标准（排除已删除的）设为当前选中标准
  selectedStandards.value = mergeResult.value.merged_standards
    .filter(s => s.change_type !== 'removed')
    .map(s => ({
      id: s.id,
      category: s.category,
      item: s.item,
      description: s.description,
      risk_level: s.risk_level,
      applicable_to: ['contract'] // 默认值
    }))

  showMergePreview.value = false
  mergeResult.value = null
  ElMessage.success('已应用到本次审核')
}

// 应用选中的标准到任务
async function applyStandards() {
  if (!taskId.value) {
    ElMessage.warning('请先上传文档')
    return
  }
  if (!selectedStandards.value.length) {
    ElMessage.warning('请先选择标准')
    return
  }

  applyingStandards.value = true
  try {
    // 创建 CSV 内容
    const csvContent = [
      '审核分类,审核要点,详细说明,风险等级,适用材料类型',
      ...selectedStandards.value.map(s =>
        `"${s.category}","${s.item}","${s.description}","${s.risk_level === 'high' ? '高' : s.risk_level === 'medium' ? '中' : '低'}","${(s.applicable_to || ['contract']).join(',')}"`
      )
    ].join('\n')

    // 创建 Blob 并上传
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' })
    const fileName = selectedCollection.value
      ? `${selectedCollection.value.name}.csv`
      : 'selected_standards.csv'
    const file = new File([blob], fileName, { type: 'text/csv' })

    await store.uploadStandard(taskId.value, file)
    showStandardPreview.value = false
    ElMessage.success('标准应用成功')
  } catch (error) {
    ElMessage.error('应用标准失败: ' + error.message)
  } finally {
    applyingStandards.value = false
  }
}
</script>

<style scoped>
.review-view {
  max-width: var(--max-width);
  margin: 0 auto;
}

/* 操作状态提示栏 */
.operation-status-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-5);
  margin-bottom: var(--spacing-4);
  background: linear-gradient(135deg, var(--color-primary) 0%, var(--color-primary-dark) 100%);
  color: white;
  border-radius: var(--radius-md);
  font-size: var(--font-size-base);
  box-shadow: 0 2px 12px rgba(37, 99, 235, 0.4);
}

.operation-status-bar .el-icon {
  font-size: var(--font-size-lg);
}

/* AI 处理全屏遮罩样式 */
.ai-processing-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.ai-processing-card {
  background: white;
  border-radius: var(--radius-xl);
  padding: var(--spacing-8) var(--spacing-10);
  text-align: center;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
  max-width: 400px;
  width: 90%;
}

.ai-icon-wrapper {
  width: 80px;
  height: 80px;
  margin: 0 auto var(--spacing-5);
  background: linear-gradient(135deg, var(--color-primary) 0%, #8B5CF6 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ai-icon-wrapper .el-icon {
  color: white;
}

.ai-icon-spin {
  animation: ai-spin 2s linear infinite;
}

@keyframes ai-spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.ai-title {
  margin: 0 0 var(--spacing-3);
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.ai-desc {
  margin: 0 0 var(--spacing-5);
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
}

.ai-progress {
  height: 6px;
  background: var(--color-border);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: var(--spacing-4);
}

.ai-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary) 0%, #8B5CF6 50%, var(--color-primary) 100%);
  background-size: 200% 100%;
  animation: ai-progress 1.5s ease-in-out infinite;
  border-radius: 3px;
}

@keyframes ai-progress {
  0% {
    width: 0%;
    background-position: 0% 0%;
  }
  50% {
    width: 70%;
    background-position: 100% 0%;
  }
  100% {
    width: 100%;
    background-position: 0% 0%;
  }
}

.ai-hint {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

/* 配额不足提示样式 */
.quota-exceeded-alert {
  display: flex;
  gap: var(--spacing-4);
  padding: var(--spacing-5);
  margin-bottom: var(--spacing-4);
  background: linear-gradient(135deg, #FDF6EC 0%, #FCF0E0 100%);
  border: 1px solid #F5DAA0;
  border-radius: var(--radius-lg);
  box-shadow: 0 2px 12px rgba(230, 162, 60, 0.15);
}

.quota-icon {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #FEF0E6;
  border-radius: 50%;
}

.quota-content {
  flex: 1;
}

.quota-content h4 {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: #B88230;
}

.quota-content p {
  margin: 0 0 var(--spacing-3);
  font-size: var(--font-size-sm);
  color: #A6711C;
  line-height: var(--line-height-normal);
}

.quota-actions {
  display: flex;
  gap: var(--spacing-3);
}

.error-alert {
  margin-bottom: var(--spacing-4);
}

/* 过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.config-card,
.progress-card {
  height: calc(100vh - var(--header-height) - 76px);
  overflow-y: auto;
}

.card-header {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-md);
  color: var(--color-text-primary);
}

.upload-section h4 {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-3);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.language-detection-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-success-bg);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  color: var(--color-success);
}

.upload-box {
  width: 100%;
}

.upload-box :deep(.el-upload-dragger) {
  padding: var(--spacing-5);
  border-radius: var(--radius-md);
}

.upload-placeholder {
  color: var(--color-text-tertiary);
  text-align: center;
}

.upload-placeholder p {
  margin: var(--spacing-2) 0 var(--spacing-1);
}

.upload-placeholder span {
  font-size: var(--font-size-xs);
}

/* 预处理中状态 */
.preprocessing-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-2);
  color: var(--color-primary);
  text-align: center;
}

.preprocessing-status p {
  margin: var(--spacing-2) 0 var(--spacing-1);
  font-weight: var(--font-weight-medium);
}

.preprocessing-status span {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

/* 已识别信息展示 */
.recognized-info {
  margin-top: var(--spacing-4);
}

.recognized-info :deep(.el-descriptions__label) {
  width: 80px;
}

/* 业务背景输入区域 */
.business-context-section {
  margin-top: var(--spacing-4);
  padding: var(--spacing-4);
  background: var(--color-bg-soft, #fafafa);
  border-radius: var(--radius-base);
  border: 1px solid var(--color-border-light, #ebeef5);
}

.context-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-3);
}

.context-header .el-icon {
  color: var(--color-primary);
}

.context-title {
  font-size: var(--font-size-base);
  font-weight: 500;
  color: var(--color-text-primary);
}

.context-optional {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.business-context-section :deep(.el-textarea__inner) {
  background: #fff;
  font-size: var(--font-size-sm);
  line-height: 1.6;
}

.context-hint {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: var(--spacing-2);
  font-size: var(--font-size-sm);
  color: var(--color-success);
}

.uploaded-file {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-2);
  color: var(--color-success);
}

.uploaded-file > span {
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
}

.uploaded-file-actions {
  display: flex;
  gap: var(--spacing-2);
}

.standard-status {
  margin-top: var(--spacing-3);
}

.start-btn {
  width: 100%;
  margin-top: var(--spacing-4);
}

/* 模式提示 */
.mode-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-2);
  margin-top: var(--spacing-3);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-success-bg, #f0f9eb);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: var(--color-success, #67c23a);
}

.mode-hint .el-icon {
  color: var(--color-success, #67c23a);
}

.waiting-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}

.progress-state {
  padding: var(--spacing-10);
}

.progress-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-6);
  margin-bottom: var(--spacing-10);
}

.progress-info {
  text-align: center;
}

.progress-info h3 {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.progress-info p {
  margin: 0;
  color: var(--color-text-tertiary);
}

.completed-state,
.failed-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
}

/* 标准库相关样式 */
.library-section {
  padding: var(--spacing-2) 0;
}

.library-actions {
  display: flex;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

.library-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--spacing-6);
  color: var(--color-text-tertiary);
  text-align: center;
}

.library-tip p {
  margin-top: var(--spacing-3);
  font-size: var(--font-size-base);
}

.selected-standards {
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.selected-count {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

.standards-preview {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.more-count {
  color: var(--color-text-tertiary);
  font-size: var(--font-size-xs);
  margin-left: var(--spacing-2);
}

/* 推荐列表样式 */
.recommend-list {
  max-height: 400px;
  overflow-y: auto;
}

.recommend-item {
  display: flex;
  gap: var(--spacing-3);
  padding: var(--spacing-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-3);
  cursor: pointer;
  transition: all 0.2s;
}

.recommend-item:hover {
  border-color: var(--color-primary);
  background: var(--color-bg-secondary);
}

.recommend-item.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.recommend-content {
  flex: 1;
}

.recommend-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-2);
}

.recommend-title {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.recommend-reason {
  margin: 0 0 var(--spacing-1);
  font-size: var(--font-size-sm);
  color: var(--color-primary);
}

.recommend-desc {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

/* ==================== 标准集合选择界面样式 ==================== */

.standard-section h4 {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-4);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
}

/* 标准选择入口 */
.standard-selection-entry {
  display: flex;
  align-items: center;
  margin-bottom: var(--spacing-4);
}

.section-label {
  margin: 0 0 var(--spacing-3);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

/* 弹窗头部：搜索框+新建按钮 */
.selector-header {
  display: flex;
  gap: var(--spacing-3);
  align-items: center;
  margin-bottom: var(--spacing-4);
}

/* 智能推荐区域样式 */
.recommendation-section {
  margin-bottom: var(--spacing-4);
  padding: var(--spacing-4);
  background: var(--color-success-bg);
  border-radius: var(--radius-md);
  border: 1px solid #c2e7b0;
}

.recommendation-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-3);
  font-weight: var(--font-weight-semibold);
  color: var(--color-success);
}

.recommendation-header span {
  flex: 1;
}

.recommendation-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.recommendation-card {
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-card);
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.recommendation-card:hover {
  border-color: var(--color-success);
  box-shadow: var(--shadow-sm);
}

.recommendation-card.selected {
  border-color: var(--color-success);
  background: #f0fdf4;
}

.rec-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-2);
}

.rec-name {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.rec-reason {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
}

.rec-meta {
  display: flex;
  gap: var(--spacing-2);
}

/* 集合列表 */
.collection-list {
  max-height: 400px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.collection-card-dialog {
  padding: var(--spacing-4);
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.2s;
}

.collection-card-dialog:hover {
  border-color: var(--color-border-dark);
  box-shadow: var(--shadow-md);
}

.collection-card-dialog.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.collection-card-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.collection-info {
  flex: 1;
  min-width: 0;
}

.collection-name {
  display: block;
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-1);
}

.collection-meta {
  display: flex;
  gap: var(--spacing-2);
  flex-wrap: wrap;
}

.collection-desc {
  margin: var(--spacing-3) 0 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
  line-height: var(--line-height-normal);
  padding-left: 36px;
}

.check-icon {
  font-size: var(--font-size-xl);
}

.empty-tip {
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
  padding: var(--spacing-5);
}

.selection-summary {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: var(--spacing-4);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-primary-bg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-primary);
}

/* 预设模板卡片（旧样式保留兼容） */
.template-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

.template-card {
  padding: var(--spacing-4);
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.template-card:hover {
  border-color: var(--color-border-dark);
  box-shadow: var(--shadow-sm);
}

.template-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.template-card-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-2);
}

.template-name {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
}

.template-desc {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  line-height: var(--line-height-normal);
}

.template-meta {
  display: flex;
  gap: var(--spacing-2);
}

.other-options {
  display: flex;
  gap: var(--spacing-4);
  padding-top: var(--spacing-2);
  border-top: 1px dashed var(--color-border-light);
}

/* 已选标准显示 */
.selected-standards-section {
  margin-top: var(--spacing-4);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.selected-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-2);
}

.selected-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-1);
}

/* 特殊要求输入 */
.special-requirements {
  margin-top: var(--spacing-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: border-color 0.3s, box-shadow 0.3s;
}

.special-requirements.has-content {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-8);
}

.special-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-hover);
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.special-requirements.has-content .special-header {
  background: var(--el-color-primary-light-9);
}

.special-header:hover {
  background: var(--color-bg-secondary);
}

.special-requirements.has-content .special-header:hover {
  background: var(--el-color-primary-light-8);
}

.special-title {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  font-weight: 500;
}

.special-requirements.has-content .special-title {
  color: var(--el-color-primary);
}

.special-priority-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  padding: 2px 8px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-sm);
}

.special-requirements.has-content .special-priority-hint {
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
}

.expand-icon {
  margin-left: auto;
  transition: transform 0.3s;
  color: var(--color-text-tertiary);
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.special-content {
  padding: var(--spacing-4);
  padding-top: var(--spacing-3);
  background: var(--color-bg-card);
}

.special-desc {
  margin: 0 0 var(--spacing-3) 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  line-height: 1.5;
}

.special-content :deep(.el-textarea__inner) {
  font-size: var(--font-size-sm);
  line-height: 1.8;
  padding: var(--spacing-3);
}

.special-content :deep(.el-textarea__inner::placeholder) {
  color: var(--color-text-quaternary);
  line-height: 1.8;
}

/* 特殊要求处理方式选择 */
.special-mode-selection {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-3);
  margin-top: var(--spacing-4);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.mode-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  white-space: nowrap;
  padding-top: 2px;
}

.special-mode-selection :deep(.el-radio-group) {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.special-mode-selection :deep(.el-radio) {
  height: auto;
  margin-right: 0;
}

.mode-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mode-name {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.mode-desc {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.special-footer {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  margin-top: var(--spacing-3);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border-lighter);
}

.special-footer.direct-mode {
  background: #f0f9eb;
  border: none;
  border-radius: var(--radius-md);
  padding: var(--spacing-3);
  margin-top: var(--spacing-3);
}

.direct-hint {
  font-size: var(--font-size-sm);
  color: #67c23a;
}

.special-tip {
  font-size: var(--font-size-xs);
  color: var(--color-text-quaternary);
}

/* 已应用标准状态 */
.applied-standard {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: var(--spacing-4);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-success-bg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-success);
}

.applied-standard span {
  flex: 1;
}

/* ==================== 业务条线选择样式 ==================== */

.business-section {
  margin-top: var(--spacing-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.business-section .section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-hover);
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.business-section .section-header:hover {
  background: var(--color-bg-secondary);
}

.business-section .section-header h4 {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  font-weight: normal;
}

.business-content {
  padding: var(--spacing-4);
  background: var(--color-bg-card);
}

.business-tip {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin: 0 0 var(--spacing-3) 0;
}

.business-option {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.business-option .context-count {
  margin-left: auto;
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.selected-business-info {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-success-bg);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-success);
}

.selected-business-info .business-meta {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.selected-business-info .manage-link {
  margin-left: auto;
}

/* ==================== 任务要求布局样式 ==================== */

.task-requirements-section h4 {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-3);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.requirement-selection-entry {
  display: flex;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

.requirement-selection-entry .el-button {
  flex: 1;
  justify-content: center;
  position: relative;
}

.requirement-selection-entry .btn-tag {
  margin-left: var(--spacing-2);
}

/* ==================== 业务条线选择对话框样式 ==================== */

.business-selector {
  min-height: 300px;
}

.business-selector .selector-header {
  display: flex;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

.business-line-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
  max-height: 350px;
  overflow-y: auto;
  padding-right: var(--spacing-2);
}

.business-line-card {
  padding: var(--spacing-4);
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.business-line-card:hover {
  border-color: var(--color-border-dark);
  box-shadow: var(--shadow-sm);
}

.business-line-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-bg);
}

.business-line-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.business-line-info {
  flex: 1;
  min-width: 0;
}

.business-line-name {
  display: block;
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-1);
}

.business-line-meta {
  display: flex;
  gap: var(--spacing-2);
  flex-wrap: wrap;
}

.business-line-desc {
  margin: var(--spacing-2) 0 0;
  padding-left: calc(24px + var(--spacing-3));
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  line-height: var(--line-height-normal);
}

.business-line-card .check-icon {
  flex-shrink: 0;
}

/* ==================== 整合预览样式 ==================== */

.merge-preview {
  max-height: 500px;
  overflow-y: auto;
}

.merge-summary {
  margin-bottom: var(--spacing-5);
}

.summary-stats {
  display: flex;
  gap: var(--spacing-3);
  margin-top: var(--spacing-3);
  flex-wrap: wrap;
}

.summary-stats .el-tag {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

.merge-standards-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.merge-standard-item {
  display: flex;
  gap: var(--spacing-3);
  padding: var(--spacing-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  transition: all 0.2s;
}

.merge-standard-item.added {
  background: var(--color-success-bg);
  border-color: #c2e7b0;
}

.merge-standard-item.modified {
  background: var(--color-warning-bg);
  border-color: #f5dab1;
}

.merge-standard-item.removed {
  background: var(--color-danger-bg);
  border-color: #fbc4c4;
  opacity: 0.7;
}

.merge-standard-item.removed .standard-desc {
  text-decoration: line-through;
}

.standard-change-badge {
  flex-shrink: 0;
}

.standard-content {
  flex: 1;
  min-width: 0;
}

.standard-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-2);
  flex-wrap: wrap;
}

.standard-category {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  padding: 2px var(--spacing-2);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-sm);
}

.standard-item {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  font-size: var(--font-size-base);
}

.standard-desc {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
}

.change-reason {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-2);
  margin: var(--spacing-2) 0 0;
  font-size: var(--font-size-xs);
  color: var(--color-primary);
  background: var(--color-primary-bg);
  padding: var(--spacing-2) var(--spacing-3);
  border-radius: var(--radius-sm);
}

.change-reason .el-icon {
  margin-top: 2px;
  flex-shrink: 0;
}

/* 高级选项区域 */
.advanced-options-section {
  margin-top: var(--spacing-2);
}

.advanced-options-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s;
}

.advanced-options-header:hover {
  border-color: var(--color-primary-lighter);
  background: var(--color-bg-hover);
}

.advanced-options-header.expanded {
  border-bottom-left-radius: 0;
  border-bottom-right-radius: 0;
  border-bottom-color: transparent;
}

.advanced-options-header.has-selection {
  border-color: var(--color-primary-lighter);
  background: var(--color-primary-bg);
}

.advanced-options-header .header-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.advanced-options-header .header-left .el-icon {
  color: var(--color-text-secondary);
}

.advanced-options-header .header-title {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.advanced-options-header .header-subtitle {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin-left: var(--spacing-1);
}

.advanced-options-header .header-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.advanced-options-header .expand-icon {
  transition: transform 0.2s;
  color: var(--color-text-tertiary);
}

.advanced-options-header .expand-icon.expanded {
  transform: rotate(180deg);
}

.advanced-options-content {
  padding: var(--spacing-4);
  border: 1px solid var(--color-border-light);
  border-top: none;
  border-radius: 0 0 var(--radius-md) var(--radius-md);
  background: var(--color-bg);
}
</style>
