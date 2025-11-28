<template>
  <div class="standards-view">
    <!-- 第一层：集合列表 -->
    <template v-if="!selectedCollection">
      <!-- 页面头部 -->
      <div class="page-header">
        <div class="header-left">
          <h1>审核标准管理</h1>
          <p class="subtitle">管理审核标准，每套标准包含若干审核条目</p>
        </div>
        <div class="header-actions">
          <el-dropdown trigger="click" @command="handleNewStandardCommand">
            <el-button type="primary">
              <el-icon><Plus /></el-icon>
              新建标准
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="upload">
                  <el-icon><Upload /></el-icon>
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
      </div>

      <!-- 筛选 -->
      <el-card class="filter-card">
        <div class="filter-row">
          <el-input
            v-model="collectionSearch"
            placeholder="搜索标准..."
            clearable
            style="width: 300px"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select
            v-model="filterMaterialType"
            placeholder="材料类型"
            clearable
            style="width: 150px"
          >
            <el-option label="合同" value="contract" />
            <el-option label="营销材料" value="marketing" />
          </el-select>
          <el-select
            v-model="filterLanguage"
            placeholder="标准语言"
            clearable
            style="width: 150px"
            @change="loadCollections"
          >
            <el-option label="中文" value="zh-CN" />
            <el-option label="English" value="en" />
          </el-select>
        </div>
      </el-card>

      <!-- 集合列表 -->
      <div class="collections-list" v-loading="loadingCollections">
        <el-empty v-if="filteredCollections.length === 0" description="暂无标准" />
        <div
          v-for="col in filteredCollections"
          :key="col.id"
          class="collection-card"
        >
          <div class="collection-card-main" @click="openCollection(col)">
            <div class="collection-icon">
              <el-icon :size="24"><Folder /></el-icon>
            </div>
            <div class="collection-info">
              <div class="collection-name">
                {{ col.name }}
                <el-tag v-if="col.is_preset" size="small" type="info">系统预设</el-tag>
                <el-tag v-if="col.language === 'en'" size="small" type="success">EN</el-tag>
              </div>
              <div class="collection-desc">{{ col.description || '暂无描述' }}</div>
              <div class="collection-meta">
                <span>{{ col.standard_count }} 条审核条目</span>
                <span class="meta-sep">|</span>
                <span>{{ formatMaterialType(col.material_type) }}</span>
                <span class="meta-sep">|</span>
                <span>{{ formatLanguage(col.language) }}</span>
              </div>
            </div>
          </div>
          <div class="collection-actions">
            <el-button text type="primary" @click.stop="openCollection(col)">
              <el-icon><View /></el-icon>
              查看
            </el-button>
            <el-button text type="primary" @click.stop="editCollectionInfo(col)">
              <el-icon><Edit /></el-icon>
              编辑
            </el-button>
            <el-button
              text
              type="danger"
              @click.stop="deleteCollection(col)"
              :disabled="col.is_preset"
            >
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </div>
        </div>
      </div>
    </template>

    <!-- 第二层：集合详情（风险点管理） -->
    <template v-else>
      <!-- 详情头部 -->
      <div class="detail-header">
        <el-button text @click="backToList">
          <el-icon><ArrowLeft /></el-icon>
          返回列表
        </el-button>
        <h2>{{ selectedCollection.name }}</h2>
        <el-tag v-if="selectedCollection.is_preset" size="small" type="info">系统预设</el-tag>
      </div>

      <!-- 集合信息卡片 -->
      <el-card class="collection-info-card">
        <div class="info-row">
          <div class="info-item">
            <span class="info-label">适用场景：</span>
            <span class="info-value">{{ selectedCollection.description || '暂无描述' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">材料类型：</span>
            <span class="info-value">{{ formatMaterialType(selectedCollection.material_type) }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">审核条目数量：</span>
            <span class="info-value">{{ standards.length }} 条</span>
          </div>
        </div>
        <!-- 适用说明（用于智能推荐） -->
        <div v-if="selectedCollection.usage_instruction" class="usage-instruction-display">
          <span class="info-label">适用说明：</span>
          <span class="info-value">{{ selectedCollection.usage_instruction }}</span>
        </div>
        <el-button type="primary" text size="small" @click="editCollectionInfo(selectedCollection)">
          <el-icon><Edit /></el-icon>
          编辑标准信息
        </el-button>
      </el-card>

      <!-- 审核条目筛选和操作 -->
      <el-card class="filter-card">
        <div class="filter-row">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索审核条目..."
            clearable
            style="width: 300px"
            @input="handleSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>

          <el-select
            v-model="filterCategory"
            placeholder="选择分类"
            clearable
            style="width: 200px"
            @change="loadStandards"
          >
            <el-option
              v-for="cat in categories"
              :key="cat"
              :label="cat"
              :value="cat"
            />
          </el-select>

          <el-select
            v-model="filterRiskLevel"
            placeholder="风险等级"
            clearable
            style="width: 150px"
            @change="loadStandards"
          >
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>

          <el-button type="primary" @click="showAddDialog = true">
            <el-icon><Plus /></el-icon>
            添加审核条目
          </el-button>
        </div>
      </el-card>

      <!-- 审核条目列表表格 -->
      <el-card class="table-card">
        <el-table
          :data="standards"
          v-loading="loading"
          stripe
          style="width: 100%"
        >
          <el-table-column prop="category" label="分类" width="120" />
          <el-table-column prop="item" label="审核要点" min-width="180" />
          <el-table-column prop="description" label="说明" min-width="250" show-overflow-tooltip />
          <el-table-column label="风险等级" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="getRiskTagType(row.risk_level)" size="small">
                {{ getRiskLabel(row.risk_level) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="适用类型" width="120">
            <template #default="{ row }">
              <span>{{ formatApplicableTo(row.applicable_to) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="usage_instruction" label="适用说明" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.usage_instruction">{{ row.usage_instruction }}</span>
              <el-button
                v-else
                type="primary"
                text
                size="small"
                @click="generateUsageInstruction(row)"
                :loading="generatingIds.includes(row.id)"
              >
                生成
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" text size="small" @click="editStandard(row)">
                编辑
              </el-button>
              <el-button type="danger" text size="small" @click="deleteStandard(row)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="table-footer">
          <span>共 {{ standards.length }} 条审核条目</span>
        </div>
      </el-card>
    </template>

    <!-- 添加审核条目对话框 -->
    <el-dialog
      v-model="showAddDialog"
      :title="editingStandard ? '编辑审核条目' : '添加审核条目'"
      width="600px"
      @close="resetStandardForm"
    >
      <el-form :model="standardForm" label-width="100px">
        <el-form-item label="分类" required>
          <el-input v-model="standardForm.category" placeholder="如：主体资格、权利义务" />
        </el-form-item>
        <el-form-item label="审核要点" required>
          <el-input v-model="standardForm.item" placeholder="简要描述审核要点" />
        </el-form-item>
        <el-form-item label="详细说明" required>
          <el-input
            v-model="standardForm.description"
            type="textarea"
            :rows="3"
            placeholder="详细的审核说明"
          />
        </el-form-item>
        <el-form-item label="风险等级">
          <el-select v-model="standardForm.risk_level" style="width: 100%">
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>
        </el-form-item>
        <el-form-item label="适用类型">
          <el-checkbox-group v-model="standardForm.applicable_to">
            <el-checkbox label="contract">合同</el-checkbox>
            <el-checkbox label="marketing">营销材料</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="适用说明">
          <el-input
            v-model="standardForm.usage_instruction"
            type="textarea"
            :rows="2"
            placeholder="可选，说明何时使用该标准"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="saveStandard" :loading="saving">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑标准信息对话框 -->
    <el-dialog
      v-model="showCollectionEditDialog"
      title="编辑标准信息"
      width="600px"
    >
      <el-form :model="collectionForm" label-width="100px">
        <el-form-item label="标准名称" required>
          <el-input v-model="collectionForm.name" placeholder="如：电商平台合作协议审核标准" />
        </el-form-item>
        <el-form-item label="适用场景">
          <el-input
            v-model="collectionForm.description"
            type="textarea"
            :rows="2"
            placeholder="描述该标准的适用场景"
          />
        </el-form-item>
        <el-form-item label="适用说明">
          <el-input
            v-model="collectionForm.usage_instruction"
            type="textarea"
            :rows="3"
            placeholder="用于智能推荐的详细说明，例如：适用于各类商务合同的法务审阅，包括采购合同、销售合同、服务合同等。重点关注合同主体资格、权利义务平衡、付款条款、违约责任等核心条款。"
          />
          <div class="form-tip">
            <el-icon><InfoFilled /></el-icon>
            适用说明用于智能推荐功能，帮助 AI 判断该标准是否适合审阅文档
          </div>
        </el-form-item>
        <el-form-item label="材料类型">
          <el-select v-model="collectionForm.material_type" style="width: 100%">
            <el-option label="合同" value="contract" />
            <el-option label="营销材料" value="marketing" />
            <el-option label="两者都适用" value="both" />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCollectionEditDialog = false">取消</el-button>
        <el-button type="primary" @click="saveCollectionInfo" :loading="savingCollection">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入对话框（创建新集合） -->
    <el-dialog
      v-model="showImportDialog"
      title="上传审核标准"
      width="700px"
      @close="resetImportDialog"
    >
      <div v-if="importStep === 1">
        <!-- 第一步：输入标准信息 -->
        <el-form :model="newCollectionForm" label-width="100px">
          <el-form-item label="标准名称" required>
            <el-input v-model="newCollectionForm.name" placeholder="如：电商平台合作协议审核标准" />
          </el-form-item>
          <el-form-item label="适用场景">
            <el-input
              v-model="newCollectionForm.description"
              type="textarea"
              :rows="2"
              placeholder="描述该标准的适用场景"
            />
          </el-form-item>
          <el-form-item label="材料类型">
            <el-select v-model="newCollectionForm.material_type" style="width: 100%">
              <el-option label="合同" value="contract" />
              <el-option label="营销材料" value="marketing" />
              <el-option label="两者都适用" value="both" />
            </el-select>
          </el-form-item>
          <el-form-item label="标准语言">
            <el-radio-group v-model="newCollectionForm.language">
              <el-radio value="zh-CN">中文</el-radio>
              <el-radio value="en">English</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>

        <el-divider />

        <el-upload
          ref="uploadRef"
          drag
          :auto-upload="false"
          :on-change="handleFileChange"
          accept=".xlsx,.xls,.csv,.docx,.md,.txt"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">
            拖拽文件到此处，或 <em>点击上传</em>
          </div>
          <template #tip>
            <div class="el-upload__tip">
              支持 Excel (.xlsx/.xls)、CSV、Word (.docx)、Markdown (.md)、文本 (.txt) 格式
            </div>
          </template>
        </el-upload>
      </div>

      <div v-else>
        <!-- 第二步：预览标准 -->
        <el-alert
          type="success"
          :closable="false"
          style="margin-bottom: 16px"
        >
          解析成功，将创建标准「{{ newCollectionForm.name }}」，共 {{ previewStandards.length }} 条审核条目
        </el-alert>

        <el-table :data="previewStandards" max-height="400" size="small">
          <el-table-column prop="category" label="分类" width="100" />
          <el-table-column prop="item" label="审核要点" width="150" />
          <el-table-column prop="description" label="说明" show-overflow-tooltip />
          <el-table-column label="风险" width="60">
            <template #default="{ row }">
              {{ getRiskLabel(row.risk_level) }}
            </template>
          </el-table-column>
        </el-table>
      </div>

      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button
          v-if="importStep === 1"
          type="primary"
          @click="previewFile"
          :loading="previewing"
          :disabled="!selectedFile || !newCollectionForm.name"
        >
          预览
        </el-button>
        <el-button
          v-else
          @click="importStep = 1"
        >
          上一步
        </el-button>
        <el-button
          v-if="importStep === 2"
          type="primary"
          @click="saveToLibrary"
          :loading="saving"
        >
          确认入库
        </el-button>
      </template>
    </el-dialog>

    <!-- 制作标准对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      :title="createDialogTitle"
      width="900px"
      :close-on-click-modal="false"
      @close="resetCreateDialog"
    >
      <!-- 步骤指示器 -->
      <el-steps :active="createStep - 1" align-center style="margin-bottom: 24px;">
        <el-step title="填写问卷" description="提供业务信息" />
        <el-step title="预览编辑" description="确认生成的标准" />
        <el-step title="确认入库" description="保存到标准库" />
      </el-steps>

      <!-- 步骤1：问卷表单 -->
      <div v-if="createStep === 1" class="create-step-content">
        <el-form :model="creationForm" label-width="120px" label-position="top">
          <!-- 必答问题区域 -->
          <div class="form-section">
            <div class="form-section-title">
              <span class="required-badge">必答</span>
              基本信息
            </div>

            <el-form-item label="文档类型" required>
              <el-radio-group v-model="creationForm.document_type">
                <el-radio value="contract">合同</el-radio>
                <el-radio value="marketing">营销材料</el-radio>
                <el-radio value="both">两者都有</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="标准语言" required>
              <el-radio-group v-model="creationForm.language">
                <el-radio value="zh-CN">中文</el-radio>
                <el-radio value="en">English</el-radio>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="业务场景描述" required>
              <el-input
                v-model="creationForm.business_scenario"
                type="textarea"
                :rows="3"
                placeholder="请详细描述您的业务场景，例如：我们是一家软件公司，需要审核与客户签订的SaaS服务协议，主要涉及订阅费用、服务级别承诺、数据安全等条款..."
                maxlength="500"
                show-word-limit
              />
            </el-form-item>

            <el-form-item label="核心关注点" required>
              <div class="focus-area-selector">
                <el-checkbox-group v-model="creationForm.focus_areas">
                  <el-checkbox
                    v-for="area in focusAreaOptions"
                    :key="area"
                    :value="area"
                    :label="area"
                  />
                </el-checkbox-group>
                <el-button
                  type="primary"
                  text
                  size="small"
                  class="add-focus-btn"
                  @click="showCustomFocusInput = true"
                >
                  <el-icon><Plus /></el-icon>
                  添加其他
                </el-button>
              </div>
              <!-- 自定义关注点输入 -->
              <div v-if="showCustomFocusInput" class="custom-focus-input">
                <el-input
                  v-model="customFocusInput"
                  placeholder="输入关注点名称"
                  size="small"
                  style="width: 200px;"
                  @keyup.enter="addCustomFocus"
                />
                <el-button type="primary" size="small" @click="addCustomFocus">添加</el-button>
                <el-button size="small" @click="showCustomFocusInput = false; customFocusInput = ''">取消</el-button>
              </div>
              <!-- 已添加的自定义关注点 -->
              <div v-if="customFocusAreas.length > 0" class="custom-focus-tags">
                <el-tag
                  v-for="(area, index) in customFocusAreas"
                  :key="index"
                  closable
                  size="small"
                  @close="removeCustomFocus(index)"
                >
                  {{ area }}
                </el-tag>
              </div>
            </el-form-item>
          </div>

          <!-- 选答问题区域 -->
          <div class="form-section">
            <div class="form-section-title">
              <span class="optional-badge">选答</span>
              补充信息（帮助生成更精准的标准）
            </div>

            <el-form-item label="我方角色">
              <el-input
                v-model="creationForm.our_role"
                placeholder="例如：甲方/采购方/服务提供方/委托方"
              />
            </el-form-item>

            <el-form-item label="所属行业">
              <div class="industry-selector">
                <el-select
                  v-model="creationForm.industry"
                  placeholder="选择行业"
                  clearable
                  style="width: 200px;"
                >
                  <el-option
                    v-for="ind in industryOptions"
                    :key="ind"
                    :label="ind"
                    :value="ind"
                  />
                </el-select>
                <el-input
                  v-model="creationForm.custom_industry"
                  placeholder="或输入其他行业"
                  style="width: 200px; margin-left: 12px;"
                />
              </div>
            </el-form-item>

            <el-form-item label="特殊风险关注">
              <el-input
                v-model="creationForm.special_risks"
                type="textarea"
                :rows="2"
                placeholder="如有特殊的审核要求，请在此说明"
              />
            </el-form-item>

            <el-form-item label="参考材料">
              <el-input
                v-model="creationForm.reference_material"
                type="textarea"
                :rows="4"
                placeholder="粘贴相关的法规条文、行业规范、已有合同模板等作为参考"
              />
            </el-form-item>
          </div>
        </el-form>
      </div>

      <!-- 步骤2：预览编辑生成的标准 -->
      <div v-if="createStep === 2" class="create-step-content">
        <el-alert
          v-if="generationSummary"
          type="success"
          :closable="false"
          style="margin-bottom: 16px;"
        >
          {{ generationSummary }}
        </el-alert>

        <!-- 集合名称编辑 -->
        <div class="collection-name-edit">
          <el-form-item label="标准名称" label-width="100px">
            <el-input v-model="generatedCollectionName" placeholder="AI生成的名称，可修改" />
          </el-form-item>
        </div>

        <el-table
          :data="generatedStandards"
          border
          size="small"
          max-height="350"
        >
          <el-table-column type="expand">
            <template #default="{ row, $index }">
              <div class="expand-edit-form">
                <el-form label-width="80px" size="small">
                  <el-form-item label="分类">
                    <el-input v-model="row.category" />
                  </el-form-item>
                  <el-form-item label="审核要点">
                    <el-input v-model="row.item" />
                  </el-form-item>
                  <el-form-item label="详细说明">
                    <el-input v-model="row.description" type="textarea" :rows="2" />
                  </el-form-item>
                  <el-form-item label="风险等级">
                    <el-select v-model="row.risk_level">
                      <el-option label="高" value="high" />
                      <el-option label="中" value="medium" />
                      <el-option label="低" value="low" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="适用类型">
                    <el-checkbox-group v-model="row.applicable_to">
                      <el-checkbox label="contract" value="contract">合同</el-checkbox>
                      <el-checkbox label="marketing" value="marketing">营销材料</el-checkbox>
                    </el-checkbox-group>
                  </el-form-item>
                  <el-form-item label="适用说明">
                    <el-input v-model="row.usage_instruction" type="textarea" :rows="2" />
                  </el-form-item>
                </el-form>
                <div class="expand-actions">
                  <el-button type="danger" size="small" @click="removeGeneratedStandard($index)">
                    删除此标准
                  </el-button>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="category" label="分类" width="100" />
          <el-table-column prop="item" label="审核要点" width="150" />
          <el-table-column prop="description" label="说明" show-overflow-tooltip />
          <el-table-column label="风险" width="60" align="center">
            <template #default="{ row }">
              <el-tag :type="getRiskTagType(row.risk_level)" size="small">
                {{ getRiskLabel(row.risk_level) }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <div class="step2-tip">
          <el-icon><InfoFilled /></el-icon>
          点击行左侧展开按钮可编辑标准详情
        </div>
      </div>

      <!-- 步骤3：确认适用条件 -->
      <div v-if="createStep === 3" class="create-step-content">
        <el-alert
          type="info"
          :closable="false"
          style="margin-bottom: 16px;"
        >
          将创建标准「{{ generatedCollectionName }}」，包含 {{ generatedStandards.length }} 条审核条目
        </el-alert>

        <div class="usage-instruction-list">
          <div
            v-for="(std, index) in generatedStandards"
            :key="index"
            class="usage-item"
          >
            <div class="usage-item-header">
              <el-tag :type="getRiskTagType(std.risk_level)" size="small">{{ getRiskLabel(std.risk_level) }}</el-tag>
              <span class="usage-item-title">{{ std.category }} - {{ std.item }}</span>
            </div>
            <el-input
              v-model="std.usage_instruction"
              type="textarea"
              :rows="2"
              placeholder="说明该标准适用的条件，例如：适用于涉及支付条款的合同"
            />
          </div>
        </div>
      </div>

      <template #footer>
        <div class="create-dialog-footer">
          <el-button @click="showCreateDialog = false">取消</el-button>

          <!-- 步骤1按钮 -->
          <template v-if="createStep === 1">
            <el-button
              type="primary"
              @click="generateStandardsFromBusiness"
              :loading="generating"
              :disabled="!canGenerate"
            >
              <el-icon><MagicStick /></el-icon>
              生成标准
            </el-button>
          </template>

          <!-- 步骤2按钮 -->
          <template v-if="createStep === 2">
            <el-button @click="createStep = 1">上一步</el-button>
            <el-button type="primary" @click="createStep = 3" :disabled="!generatedStandards.length || !generatedCollectionName">
              下一步
            </el-button>
          </template>

          <!-- 步骤3按钮 -->
          <template v-if="createStep === 3">
            <el-button @click="createStep = 2">上一步</el-button>
            <el-button
              type="primary"
              @click="saveGeneratedStandards"
              :loading="savingCreated"
            >
              确认入库
            </el-button>
          </template>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Upload, Download, Search, Plus, UploadFilled, MagicStick, InfoFilled, ArrowDown,
  Folder, View, Edit, Delete, ArrowLeft
} from '@element-plus/icons-vue'
import api from '@/api'

// ==================== 路由参数 ====================
const route = useRoute()
const router = useRouter()

// ==================== 标准列表相关 ====================
const loadingCollections = ref(false)
const collections = ref([])
const collectionSearch = ref('')
const filterMaterialType = ref('')
const filterLanguage = ref('')  // 语言筛选
const selectedCollection = ref(null)

// 筛选后的集合
const filteredCollections = computed(() => {
  let result = collections.value

  if (collectionSearch.value) {
    const keyword = collectionSearch.value.toLowerCase()
    result = result.filter(c =>
      c.name.toLowerCase().includes(keyword) ||
      (c.description && c.description.toLowerCase().includes(keyword))
    )
  }

  if (filterMaterialType.value) {
    result = result.filter(c =>
      c.material_type === filterMaterialType.value || c.material_type === 'both'
    )
  }

  return result
})

// 加载集合列表
async function loadCollections() {
  loadingCollections.value = true
  try {
    const params = {}
    if (filterLanguage.value) params.language = filterLanguage.value
    const response = await api.getCollections(params)
    collections.value = response.data
  } catch (error) {
    ElMessage.error('加载标准失败: ' + error.message)
  } finally {
    loadingCollections.value = false
  }
}

// 打开集合详情
async function openCollection(col) {
  selectedCollection.value = col
  await loadStandards()
  await loadCategories()
}

// 返回列表
function backToList() {
  selectedCollection.value = null
  standards.value = []
  filterCategory.value = ''
  filterRiskLevel.value = ''
  searchKeyword.value = ''
}

// ==================== 集合编辑相关 ====================
const showCollectionEditDialog = ref(false)
const savingCollection = ref(false)
const editingCollection = ref(null)
const collectionForm = reactive({
  name: '',
  description: '',
  usage_instruction: '',
  material_type: 'both'
})

function editCollectionInfo(col) {
  editingCollection.value = col
  collectionForm.name = col.name
  collectionForm.description = col.description
  collectionForm.usage_instruction = col.usage_instruction || ''
  collectionForm.material_type = col.material_type
  showCollectionEditDialog.value = true
}

async function saveCollectionInfo() {
  if (!collectionForm.name.trim()) {
    ElMessage.warning('集合名称不能为空')
    return
  }

  savingCollection.value = true
  try {
    await api.updateCollection(editingCollection.value.id, {
      name: collectionForm.name,
      description: collectionForm.description,
      usage_instruction: collectionForm.usage_instruction || null,
      material_type: collectionForm.material_type
    })
    ElMessage.success('更新成功')
    showCollectionEditDialog.value = false

    // 更新本地数据
    if (selectedCollection.value && selectedCollection.value.id === editingCollection.value.id) {
      selectedCollection.value.name = collectionForm.name
      selectedCollection.value.description = collectionForm.description
      selectedCollection.value.usage_instruction = collectionForm.usage_instruction
      selectedCollection.value.material_type = collectionForm.material_type
    }
    loadCollections()
  } catch (error) {
    ElMessage.error('更新失败: ' + error.message)
  } finally {
    savingCollection.value = false
  }
}

// 删除集合
async function deleteCollection(col) {
  if (col.is_preset) {
    ElMessage.warning('系统预设集合不可删除')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要删除标准「${col.name}」吗？该标准内的所有审核条目将一并删除。`,
      '确认删除',
      { type: 'warning' }
    )
    await api.deleteCollection(col.id)
    ElMessage.success('删除成功')
    loadCollections()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

// ==================== 风险点管理相关 ====================
const loading = ref(false)
const standards = ref([])
const categories = ref([])
const searchKeyword = ref('')
const filterCategory = ref('')
const filterRiskLevel = ref('')
const generatingIds = ref([])

// 加载风险点列表
async function loadStandards() {
  if (!selectedCollection.value) return

  loading.value = true
  try {
    const params = {}
    if (filterCategory.value) params.category = filterCategory.value
    if (filterRiskLevel.value) params.risk_level = filterRiskLevel.value
    if (searchKeyword.value) params.keyword = searchKeyword.value

    const response = await api.getCollectionStandards(selectedCollection.value.id, params)
    standards.value = response.data
  } catch (error) {
    ElMessage.error('加载风险点失败: ' + error.message)
  } finally {
    loading.value = false
  }
}

// 加载分类列表
async function loadCategories() {
  if (!selectedCollection.value) return

  try {
    const response = await api.getCollectionCategories(selectedCollection.value.id)
    categories.value = response.data
  } catch (error) {
    console.error('加载分类失败:', error)
  }
}

// 搜索处理（防抖）
let searchTimer = null
function handleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    loadStandards()
  }, 300)
}

// ==================== 添加/编辑风险点 ====================
const showAddDialog = ref(false)
const saving = ref(false)
const editingStandard = ref(null)
const standardForm = reactive({
  category: '',
  item: '',
  description: '',
  risk_level: 'medium',
  applicable_to: ['contract', 'marketing'],
  usage_instruction: ''
})

function editStandard(row) {
  editingStandard.value = row
  Object.assign(standardForm, {
    category: row.category,
    item: row.item,
    description: row.description,
    risk_level: row.risk_level,
    applicable_to: row.applicable_to || ['contract', 'marketing'],
    usage_instruction: row.usage_instruction || ''
  })
  showAddDialog.value = true
}

async function saveStandard() {
  if (!standardForm.category || !standardForm.item || !standardForm.description) {
    ElMessage.warning('请填写必填字段')
    return
  }

  saving.value = true
  try {
    if (editingStandard.value) {
      // 更新
      await api.updateLibraryStandard(editingStandard.value.id, standardForm)
      ElMessage.success('更新成功')
    } else {
      // 添加到当前集合
      await api.addStandardToCollection(selectedCollection.value.id, standardForm)
      ElMessage.success('添加成功')
    }
    showAddDialog.value = false
    resetStandardForm()
    loadStandards()
    loadCategories()

    // 更新集合的风险点数量
    selectedCollection.value.standard_count = standards.value.length + (editingStandard.value ? 0 : 1)
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

async function deleteStandard(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除风险点「${row.item}」吗？`,
      '确认删除',
      { type: 'warning' }
    )
    await api.deleteLibraryStandard(row.id)
    ElMessage.success('删除成功')
    loadStandards()
    loadCategories()
    selectedCollection.value.standard_count--
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + error.message)
    }
  }
}

function resetStandardForm() {
  editingStandard.value = null
  Object.assign(standardForm, {
    category: '',
    item: '',
    description: '',
    risk_level: 'medium',
    applicable_to: ['contract', 'marketing'],
    usage_instruction: ''
  })
}

// 生成适用说明
async function generateUsageInstruction(row) {
  generatingIds.value.push(row.id)
  try {
    const response = await api.generateUsageInstruction({
      standard_ids: [row.id],
    })
    if (response.data.success_count > 0) {
      row.usage_instruction = response.data.results[0].usage_instruction
      ElMessage.success('生成成功')
    } else {
      ElMessage.error('生成失败: ' + response.data.errors[0])
    }
  } catch (error) {
    ElMessage.error('生成失败: ' + error.message)
  } finally {
    generatingIds.value = generatingIds.value.filter(id => id !== row.id)
  }
}

// ==================== 导入标准（创建新集合） ====================
const showImportDialog = ref(false)
const importStep = ref(1)
const selectedFile = ref(null)
const previewStandards = ref([])
const previewing = ref(false)
const newCollectionForm = reactive({
  name: '',
  description: '',
  material_type: 'both',
  language: 'zh-CN'
})

function handleFileChange(file) {
  selectedFile.value = file.raw
}

async function previewFile() {
  if (!selectedFile.value) return
  if (!newCollectionForm.name.trim()) {
    ElMessage.warning('请先输入集合名称')
    return
  }

  previewing.value = true
  try {
    const response = await api.previewStandards(selectedFile.value)
    previewStandards.value = response.data.standards
    importStep.value = 2
    ElMessage.success(`解析成功，共 ${response.data.total_count} 条标准`)
  } catch (error) {
    ElMessage.error('解析失败: ' + error.message)
  } finally {
    previewing.value = false
  }
}

async function saveToLibrary() {
  if (!previewStandards.value.length) return

  saving.value = true
  try {
    const response = await api.saveToLibrary({
      collection_name: newCollectionForm.name,
      collection_description: newCollectionForm.description,
      material_type: newCollectionForm.material_type,
      language: newCollectionForm.language,
      standards: previewStandards.value,
    })
    ElMessage.success(response.data.message)
    showImportDialog.value = false
    resetImportDialog()
    loadCollections()
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

function resetImportDialog() {
  importStep.value = 1
  selectedFile.value = null
  previewStandards.value = []
  Object.assign(newCollectionForm, {
    name: '',
    description: '',
    material_type: 'both',
    language: 'zh-CN'
  })
}

// ==================== AI 制作标准 ====================
const showCreateDialog = ref(false)
const createStep = ref(1)
const generating = ref(false)
const savingCreated = ref(false)
const generatedStandards = ref([])
const generatedCollectionName = ref('')
const generationSummary = ref('')

const creationForm = reactive({
  document_type: 'contract',
  business_scenario: '',
  focus_areas: [],
  our_role: '',
  industry: '',
  special_risks: '',
  reference_material: '',
  custom_industry: '',
  language: 'zh-CN'  // 语言选择
})

// 自定义关注点相关
const showCustomFocusInput = ref(false)
const customFocusInput = ref('')
const customFocusAreas = ref([])

function addCustomFocus() {
  const value = customFocusInput.value.trim()
  if (value && !customFocusAreas.value.includes(value)) {
    customFocusAreas.value.push(value)
    customFocusInput.value = ''
    showCustomFocusInput.value = false
  }
}

function removeCustomFocus(index) {
  customFocusAreas.value.splice(index, 1)
}

const focusAreaOptions = [
  '合同主体资格',
  '权利义务条款',
  '费用与支付',
  '违约责任',
  '知识产权',
  '保密条款',
  '争议解决',
  '合规性要求',
]

const industryOptions = [
  '信息技术/互联网',
  '金融/保险',
  '制造业',
  '房地产/建筑',
  '医疗/生物',
  '零售/消费',
]

const createDialogTitle = computed(() => {
  const titles = ['制作审核标准', '预览编辑标准', '确认入库']
  return titles[createStep.value - 1]
})

const canGenerate = computed(() => {
  return (
    creationForm.business_scenario.trim() &&
    (creationForm.focus_areas.length > 0 || customFocusAreas.value.length > 0)
  )
})

async function generateStandardsFromBusiness() {
  if (!canGenerate.value) {
    ElMessage.warning('请填写业务场景和至少一个关注点')
    return
  }

  generating.value = true
  try {
    const allFocusAreas = [...creationForm.focus_areas, ...customFocusAreas.value]

    const industry = creationForm.custom_industry.trim() || creationForm.industry

    const response = await api.createStandardsFromBusiness({
      document_type: creationForm.document_type,
      business_scenario: creationForm.business_scenario,
      focus_areas: allFocusAreas,
      our_role: creationForm.our_role || null,
      industry: industry || null,
      special_risks: creationForm.special_risks || null,
      reference_material: creationForm.reference_material || null,
      language: creationForm.language,
    })

    generatedStandards.value = response.data.standards
    generatedCollectionName.value = response.data.collection_name || ''
    generationSummary.value = response.data.generation_summary || `成功生成 ${response.data.standards.length} 条标准`
    createStep.value = 2
    ElMessage.success('标准生成成功')
  } catch (error) {
    ElMessage.error('生成标准失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    generating.value = false
  }
}

function removeGeneratedStandard(index) {
  generatedStandards.value.splice(index, 1)
}

async function saveGeneratedStandards() {
  if (!generatedStandards.value.length) {
    ElMessage.warning('没有可保存的标准')
    return
  }
  if (!generatedCollectionName.value.trim()) {
    ElMessage.warning('请输入标准名称')
    return
  }

  savingCreated.value = true
  try {
    const response = await api.saveToLibrary({
      collection_name: generatedCollectionName.value,
      collection_description: creationForm.business_scenario,
      material_type: creationForm.document_type === 'both' ? 'both' : creationForm.document_type,
      language: creationForm.language,
      standards: generatedStandards.value,
    })
    ElMessage.success(response.data.message || '标准保存成功')
    showCreateDialog.value = false
    resetCreateDialog()
    loadCollections()
  } catch (error) {
    ElMessage.error('保存失败: ' + error.message)
  } finally {
    savingCreated.value = false
  }
}

function resetCreateDialog() {
  createStep.value = 1
  Object.assign(creationForm, {
    document_type: 'contract',
    business_scenario: '',
    focus_areas: [],
    our_role: '',
    industry: '',
    special_risks: '',
    reference_material: '',
    custom_industry: '',
    language: 'zh-CN'
  })
  // 重置自定义关注点
  customFocusAreas.value = []
  customFocusInput.value = ''
  showCustomFocusInput.value = false

  generatedStandards.value = []
  generatedCollectionName.value = ''
  generationSummary.value = ''
}

// ==================== 辅助函数 ====================
function getRiskTagType(level) {
  return { high: 'danger', medium: 'warning', low: 'success' }[level] || 'info'
}

function getRiskLabel(level) {
  return { high: '高', medium: '中', low: '低' }[level] || level
}

function formatApplicableTo(types) {
  if (!types) return ''
  return types.map(t => t === 'contract' ? '合同' : '营销').join('、')
}

function formatMaterialType(type) {
  const map = { contract: '合同', marketing: '营销材料', both: '合同/营销' }
  return map[type] || type
}

function formatLanguage(lang) {
  const map = { 'zh-CN': '中文', 'en': 'English' }
  return map[lang] || lang || '中文'
}

function handleNewStandardCommand(command) {
  if (command === 'upload') {
    showImportDialog.value = true
  } else if (command === 'ai') {
    showCreateDialog.value = true
  }
}

// ==================== 初始化 ====================

// 监听路由 query 参数变化（处理从其他页面跳转过来的情况）
watch(
  () => route.query.action,
  (action) => {
    if (action === 'ai-create') {
      showCreateDialog.value = true
      // 清除 query 参数，避免刷新页面时重复打开
      router.replace({ query: {} })
    }
  }
)

onMounted(async () => {
  await loadCollections()
  // 初次加载时也检查是否需要自动打开 AI 制作对话框（从 ReviewView 跳转过来）
  if (route.query.action === 'ai-create') {
    showCreateDialog.value = true
    router.replace({ query: {} })
  }
})
</script>

<style scoped>
.standards-view {
  padding: var(--spacing-6);
  max-width: var(--max-width);
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-6);
}

.header-left h1 {
  margin: 0 0 var(--spacing-2) 0;
  font-size: var(--font-size-2xl);
  color: var(--color-text-primary);
}

.subtitle {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-base);
}

.header-actions {
  display: flex;
  gap: var(--spacing-3);
}

.filter-card {
  margin-bottom: var(--spacing-4);
}

.filter-row {
  display: flex;
  gap: var(--spacing-4);
  flex-wrap: wrap;
  align-items: center;
}

/* 集合列表样式 */
.collections-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.collection-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-4) var(--spacing-5);
  background: var(--color-bg-card);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-light);
  transition: all 0.2s;
}

.collection-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.collection-card-main {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  flex: 1;
  cursor: pointer;
}

.collection-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  color: var(--color-primary);
}

.collection-info {
  flex: 1;
}

.collection-name {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.collection-desc {
  margin-top: var(--spacing-1);
  font-size: var(--font-size-sm);
  color: var(--color-text-tertiary);
}

.collection-meta {
  margin-top: var(--spacing-2);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.meta-sep {
  margin: 0 var(--spacing-2);
}

.collection-actions {
  display: flex;
  gap: var(--spacing-2);
}

/* 详情页样式 */
.detail-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  margin-bottom: var(--spacing-4);
}

.detail-header h2 {
  margin: 0;
  font-size: var(--font-size-xl);
  color: var(--color-text-primary);
}

.collection-info-card {
  margin-bottom: var(--spacing-4);
}

.info-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-6);
  margin-bottom: var(--spacing-3);
}

.info-item {
  display: flex;
  align-items: center;
}

.info-label {
  color: var(--color-text-tertiary);
  margin-right: var(--spacing-2);
}

.info-value {
  color: var(--color-text-primary);
}

.usage-instruction-display {
  margin-top: var(--spacing-3);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  line-height: var(--line-height-relaxed);
}

.form-tip {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
  margin-top: var(--spacing-2);
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

.table-card {
  margin-bottom: var(--spacing-6);
}

.table-footer {
  margin-top: var(--spacing-4);
  text-align: right;
  color: var(--color-text-tertiary);
  font-size: var(--font-size-base);
}

/* 制作标准对话框样式 */
.create-step-content {
  min-height: 300px;
}

.form-section {
  margin-bottom: var(--spacing-6);
  padding: var(--spacing-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
}

.form-section-title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-4);
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.required-badge {
  background: var(--color-danger);
  color: white;
  font-size: var(--font-size-xs);
  padding: 2px var(--spacing-2);
  border-radius: var(--radius-sm);
}

.optional-badge {
  background: var(--color-info);
  color: white;
  font-size: var(--font-size-xs);
  padding: 2px var(--spacing-2);
  border-radius: var(--radius-sm);
}

.focus-area-selector {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-2);
}

.focus-area-selector .el-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
}

.add-focus-btn {
  margin-left: var(--spacing-2);
}

.custom-focus-input {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: var(--spacing-3);
}

.custom-focus-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
  margin-top: var(--spacing-3);
}

.industry-selector {
  display: flex;
  align-items: center;
}

.collection-name-edit {
  margin-bottom: var(--spacing-4);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.expand-edit-form {
  padding: var(--spacing-4) var(--spacing-6);
  background: var(--color-bg-hover);
}

.expand-actions {
  margin-top: var(--spacing-3);
  text-align: right;
}

.step2-tip {
  margin-top: var(--spacing-3);
  color: var(--color-text-tertiary);
  font-size: var(--font-size-sm);
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

.usage-instruction-list {
  max-height: 400px;
  overflow-y: auto;
}

.usage-item {
  margin-bottom: var(--spacing-4);
  padding: var(--spacing-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
}

.usage-item-header {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-2);
}

.usage-item-title {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.create-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-3);
}
</style>
