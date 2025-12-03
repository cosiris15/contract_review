# 深度交互审阅模式（Interactive Mode）开发计划

## 一、需求分析与可行性评估

### 1.1 Gemini 建议评估

**整体评价：方向正确，细节需调整**

Gemini 的建议抓住了核心思路——"双模式架构"和"只增不改"原则。但结合本项目的实际代码结构，有以下需要修正的地方：

| Gemini 建议 | 实际情况 | 调整方案 |
|------------|---------|---------|
| 在 `Projects` 或 `Contracts` 表添加 `review_mode` 字段 | 项目中是 `tasks` 表 | 在 `tasks` 表添加 `review_mode` 字段 |
| 在 `Review_Items` 表添加 `chat_thread` 字段 | 项目中审核条目存储在 `review_results.modifications` 的 JSONB 数组中，没有独立的 `Review_Items` 表 | **方案 A**：在 `modifications` 数组的每个对象中增加 `chat_history` 字段；**方案 B**（推荐）：新建 `interactive_chats` 表 |
| 复用"初审接口" | 现有初审需要先选择审核标准，新模式不需要 | 需要新建独立的"无标准快速审阅"接口 |
| 前端新建 `[id]/interactive/page.tsx` | 项目前端是 Vue 3，不是 Next.js | 新建 `/views/InteractiveResultView.vue` |

### 1.2 可行性结论

✅ **完全可行**，理由如下：

1. **数据模型兼容**：现有的 `risks`、`modifications`、`actions` JSONB 结构可以完美复用
2. **LLM 能力充足**：现有的 `llm_client.py` 和 `fallback_llm.py` 支持多轮对话
3. **前端组件可复用**：Element Plus 提供了完整的聊天界面组件支持
4. **导出逻辑不变**：最终导出 Redline Word 的逻辑完全可以复用

---

## 二、架构设计

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端 (Vue 3)                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐         ┌─────────────────────────────┐   │
│  │   HomeView      │         │   InteractiveResultView     │   │
│  │  (模式选择入口)  │ ──────▶ │  (深度交互审阅主界面)        │   │
│  └─────────────────┘         │                             │   │
│          │                   │  ┌──────────┬────────────┐  │   │
│          │                   │  │ 左侧导航  │  右侧工作区 │  │   │
│          ▼                   │  │ (风险列表)│  (对话区)  │  │   │
│  ┌─────────────────┐         │  └──────────┴────────────┘  │   │
│  │  ReviewView     │         └─────────────────────────────┘   │
│  │  (标准模式)     │                                            │
│  └─────────────────┘                                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        后端 (FastAPI)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  现有 API (保持不变)              新增 API                        │
│  ┌─────────────────────┐       ┌─────────────────────────────┐  │
│  │ POST /tasks         │       │ POST /tasks/{id}/quick-review│  │
│  │ POST /tasks/{id}/   │       │ (无标准快速审阅)              │  │
│  │      review         │       ├─────────────────────────────┤  │
│  │ GET  /tasks/{id}/   │       │ POST /api/interactive/      │  │
│  │      result         │       │      {item_id}/chat         │  │
│  └─────────────────────┘       │ (单条目多轮对话)             │  │
│                                ├─────────────────────────────┤  │
│                                │ GET  /api/interactive/      │  │
│                                │      {task_id}/items        │  │
│                                │ (获取条目列表及状态)         │  │
│                                └─────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      数据库 (Supabase)                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  tasks 表 (增加字段)           新增表                            │
│  ┌─────────────────────┐       ┌─────────────────────────────┐  │
│  │ + review_mode       │       │ interactive_chats           │  │
│  │   ('batch'|         │       │ - id                        │  │
│  │    'interactive')   │       │ - task_id                   │  │
│  └─────────────────────┘       │ - item_id (modification id) │  │
│                                │ - item_type ('modification' │  │
│  review_results 表             │            | 'action')      │  │
│  ┌─────────────────────┐       │ - messages (JSONB)          │  │
│  │ (结构不变，完全复用) │       │ - status                    │  │
│  └─────────────────────┘       │ - created_at / updated_at   │  │
│                                └─────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心流程对比

```
【标准模式 (Batch Mode)】现有流程
┌──────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌──────┐
│ 上传 │ → │ 选择审核标准│ → │ AI一次性审阅│ → │ 静态修改   │ → │ 导出 │
└──────┘   └────────────┘   └────────────┘   └────────────┘   └──────┘
                                  ↓
                           生成 risks, modifications, actions

【深度交互模式 (Interactive Mode)】新流程
┌──────┐   ┌────────────┐   ┌─────────────────────────────┐   ┌──────┐
│ 上传 │ → │ AI快速初审 │ → │ 逐条多轮对话打磨             │ → │ 导出 │
└──────┘   │ (无需选标准)│   │ ┌─────┐ ┌─────┐ ┌─────┐    │   └──────┘
           └────────────┘   │ │条目1│→│条目2│→│条目N│    │
                 ↓          │ │对话 │ │对话 │ │对话 │    │
           生成初步结果      │ └──┬──┘ └──┬──┘ └──┬──┘    │
                            │    │确认    │确认    │确认   │
                            └─────────────────────────────┘
```

---

## 三、数据库设计

### 3.1 tasks 表修改

```sql
-- 迁移脚本：为 tasks 表添加审阅模式字段
ALTER TABLE tasks
ADD COLUMN IF NOT EXISTS review_mode TEXT DEFAULT 'batch';

-- 添加约束（可选）
-- ALTER TABLE tasks
-- ADD CONSTRAINT chk_review_mode
-- CHECK (review_mode IN ('batch', 'interactive'));

-- 添加索引
CREATE INDEX IF NOT EXISTS idx_tasks_review_mode ON tasks(review_mode);
```

字段说明：
- `batch`：批量模式（现有模式，默认值）
- `interactive`：深度交互模式

### 3.2 新增 interactive_chats 表

```sql
-- 新建深度交互对话记录表
CREATE TABLE interactive_chats (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,              -- 对应 modification.id 或 action.id
    item_type TEXT NOT NULL DEFAULT 'modification',  -- 'modification' | 'action'
    messages JSONB DEFAULT '[]',        -- 对话历史
    status TEXT DEFAULT 'pending',      -- 'pending' | 'in_progress' | 'completed'
    current_suggestion TEXT,            -- 当前最新建议（每次对话后更新）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_interactive_chats_task_id ON interactive_chats(task_id);
CREATE INDEX idx_interactive_chats_item_id ON interactive_chats(item_id);
CREATE INDEX idx_interactive_chats_status ON interactive_chats(status);

-- RLS 策略
ALTER TABLE interactive_chats ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own chats" ON interactive_chats
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM tasks WHERE tasks.id = interactive_chats.task_id
                AND tasks.user_id = auth.uid()::text)
    );

CREATE POLICY "Users can insert own chats" ON interactive_chats
    FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM tasks WHERE tasks.id = interactive_chats.task_id
                AND tasks.user_id = auth.uid()::text)
    );

CREATE POLICY "Users can update own chats" ON interactive_chats
    FOR UPDATE USING (
        EXISTS (SELECT 1 FROM tasks WHERE tasks.id = interactive_chats.task_id
                AND tasks.user_id = auth.uid()::text)
    );

-- 自动更新 updated_at
CREATE TRIGGER interactive_chats_updated_at
    BEFORE UPDATE ON interactive_chats
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();
```

### 3.3 messages JSONB 结构

```json
[
  {
    "role": "system",
    "content": "你是法律审阅助手，当前正在针对合同中的特定条款进行修改讨论...",
    "timestamp": "2024-01-15T10:30:00Z"
  },
  {
    "role": "assistant",
    "content": "根据初步审阅，这条关于赔偿限额的条款存在以下问题...\n\n**当前建议**：将赔偿上限从100万调整为300万...",
    "timestamp": "2024-01-15T10:30:05Z",
    "suggestion_snapshot": "将赔偿上限从100万调整为300万..."
  },
  {
    "role": "user",
    "content": "赔偿限额太低了，我们的项目金额很大，建议改成500万",
    "timestamp": "2024-01-15T10:32:00Z"
  },
  {
    "role": "assistant",
    "content": "收到您的意见。考虑到项目金额较大，我调整了建议...\n\n**更新后的建议**：将赔偿上限调整为500万，同时建议添加分级赔偿条款...",
    "timestamp": "2024-01-15T10:32:10Z",
    "suggestion_snapshot": "将赔偿上限调整为500万，同时添加分级赔偿条款..."
  }
]
```

---

## 四、后端 API 设计

### 4.1 新增 API 端点

#### 4.1.1 快速初审接口

```
POST /api/tasks/{task_id}/quick-review
```

**功能**：无需选择审核标准，直接对文档进行快速初审，生成初步的风险点和修改建议。

**请求参数**：
```json
{
  "llm_provider": "deepseek"  // 可选，默认 deepseek
}
```

**响应**：与现有 `/api/tasks/{task_id}/review` 响应格式一致

**实现要点**：
- 使用内置的通用审阅标准（或无标准的开放式审阅 Prompt）
- 复用 `ReviewEngine` 的三阶段审阅逻辑
- 设置 `task.review_mode = 'interactive'`

#### 4.1.2 获取条目列表及对话状态

```
GET /api/interactive/{task_id}/items
```

**响应**：
```json
{
  "task_id": "xxx",
  "items": [
    {
      "id": "mod_xxx",
      "type": "modification",
      "risk_level": "high",
      "original_text": "原文...",
      "current_suggestion": "当前建议...",
      "chat_status": "completed",  // pending | in_progress | completed
      "message_count": 4,
      "last_updated": "2024-01-15T10:32:10Z"
    },
    // ...
  ],
  "summary": {
    "total": 10,
    "completed": 3,
    "in_progress": 1,
    "pending": 6
  }
}
```

#### 4.1.3 单条目对话接口

```
POST /api/interactive/{task_id}/items/{item_id}/chat
```

**请求参数**：
```json
{
  "message": "赔偿限额太低了，建议改成500万",
  "llm_provider": "deepseek"  // 可选
}
```

**响应**：
```json
{
  "item_id": "mod_xxx",
  "assistant_reply": "收到您的意见。考虑到项目金额较大...",
  "updated_suggestion": "将赔偿上限调整为500万，同时添加分级赔偿条款...",
  "chat_status": "in_progress",
  "messages": [/* 完整对话历史 */]
}
```

**实现要点**：
- 组装上下文：原始条款 + 当前建议 + 历史对话
- 专用 Prompt：强调"针对特定条款修改"，而非全文审阅
- 更新 `interactive_chats.messages` 和 `current_suggestion`
- 同步更新 `review_results.modifications[item_id].suggested_text`

#### 4.1.4 标记条目完成

```
POST /api/interactive/{task_id}/items/{item_id}/complete
```

**请求参数**：
```json
{
  "final_suggestion": "用户最终确认的建议文本（可选，不传则使用当前建议）"
}
```

**响应**：
```json
{
  "item_id": "mod_xxx",
  "status": "completed",
  "final_suggestion": "..."
}
```

### 4.2 Prompt 设计

新增 `prompts.py` 中的交互式对话 Prompt：

```python
def build_interactive_chat_messages(
    original_clause: str,
    current_suggestion: str,
    risk_description: str,
    user_message: str,
    chat_history: List[Dict],
    language: str = "zh-CN"
) -> List[Dict]:
    """构建单条目交互对话的 Prompt"""

    system_prompt = """你是一位专业的法务审阅助手。当前任务是针对合同中的一个特定条款，根据用户的修改意见进行讨论和优化。

## 当前条款原文
{original_clause}

## 该条款的风险分析
{risk_description}

## 当前的修改建议
{current_suggestion}

## 你的职责
1. 认真理解用户的修改意见
2. 结合法律专业知识，评估用户意见的合理性
3. 如果用户意见合理，据此更新修改建议
4. 如果用户意见有潜在问题，礼貌地指出并给出专业建议
5. 每次回复都要明确给出【更新后的建议】部分

## 回复格式
先对用户的意见进行简短回应，然后：

**更新后的建议**：
[完整的修改建议文本]

**说明**：
[简要解释这样修改的理由]
"""

    messages = [
        {"role": "system", "content": system_prompt.format(
            original_clause=original_clause,
            risk_description=risk_description,
            current_suggestion=current_suggestion
        )}
    ]

    # 添加历史对话
    for msg in chat_history:
        if msg["role"] in ["user", "assistant"]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # 添加当前用户消息
    messages.append({"role": "user", "content": user_message})

    return messages
```

---

## 五、前端设计

### 5.1 新增文件结构

```
frontend/src/
├── views/
│   ├── InteractiveResultView.vue    # 新增：深度交互主界面
│   └── ... (现有文件不变)
├── components/
│   └── interactive/                  # 新增：交互模式专用组件
│       ├── ItemNavigator.vue         # 左侧条目导航列表
│       ├── ChatWorkspace.vue         # 右侧聊天工作区
│       ├── ClauseCompare.vue         # 原文 vs 建议对比视图
│       └── ChatMessage.vue           # 单条聊天消息
├── api/
│   └── interactive.js                # 新增：交互模式 API
└── router/
    └── index.js                      # 添加新路由
```

### 5.2 路由设计

```javascript
// router/index.js 新增路由
{
  path: '/interactive/:taskId',
  name: 'InteractiveResult',
  component: () => import('@/views/InteractiveResultView.vue'),
  meta: { requiresAuth: true }
}
```

### 5.3 InteractiveResultView.vue 布局设计

```
┌─────────────────────────────────────────────────────────────────────┐
│ 顶部导航栏                                                          │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ ← 返回  |  合同名称  |  进度: 3/10 已完成  |  [导出按钮]        │ │
│ └─────────────────────────────────────────────────────────────────┘ │
├───────────────────────┬─────────────────────────────────────────────┤
│                       │                                             │
│   条目导航列表         │              聊天工作区                      │
│   (30% 宽度)          │              (70% 宽度)                      │
│                       │                                             │
│ ┌───────────────────┐ │ ┌─────────────────────────────────────────┐ │
│ │ 🔴 条目 1 (高风险) │ │ │ 【原文 vs 建议】对比区域                │ │
│ │    ✓ 已完成       │ │ │ ┌─────────────┬─────────────────────┐   │ │
│ ├───────────────────┤ │ │ │ 原文        │ 当前建议            │   │ │
│ │ 🟡 条目 2 (中风险) │ │ │ │ "甲方承担  │ "建议修改为：       │   │ │
│ │    ✓ 已完成       │ │ │ │  全部责任" │  甲方承担不超过..." │   │ │
│ ├───────────────────┤ │ │ └─────────────┴─────────────────────┘   │ │
│ │ 🔴 条目 3 ← 当前  │ │ ├─────────────────────────────────────────┤ │
│ │    💬 对话中      │ │ │ 【对话历史区域】                        │ │
│ ├───────────────────┤ │ │                                         │ │
│ │ 🟢 条目 4 (低风险) │ │ │ AI: 根据初审，这条款存在...            │ │
│ │    ○ 待处理       │ │ │                                         │ │
│ ├───────────────────┤ │ │ 您: 赔偿限额太低了，改成500万           │ │
│ │ ...               │ │ │                                         │ │
│ └───────────────────┘ │ │ AI: 收到您的意见，已更新建议...         │ │
│                       │ │                                         │ │
│ ┌───────────────────┐ │ ├─────────────────────────────────────────┤ │
│ │ 进度统计          │ │ │ 【输入区域】                            │ │
│ │ 已完成: 2/10      │ │ │ ┌───────────────────────────────┬─────┐ │ │
│ │ 对话中: 1         │ │ │ │ 请输入您的修改意见...         │发送 │ │ │
│ │ 待处理: 7         │ │ │ └───────────────────────────────┴─────┘ │ │
│ └───────────────────┘ │ │ [确认此条并继续下一条]                  │ │
│                       │ └─────────────────────────────────────────┘ │
└───────────────────────┴─────────────────────────────────────────────┘
```

### 5.4 入口改造

在 HomeView.vue 或新建项目弹窗中添加模式选择：

```vue
<template>
  <div class="mode-selector">
    <h3>选择审阅模式</h3>
    <div class="mode-cards">
      <!-- 标准模式 -->
      <div
        class="mode-card"
        :class="{ active: selectedMode === 'batch' }"
        @click="selectedMode = 'batch'"
      >
        <el-icon :size="48"><List /></el-icon>
        <h4>标准模式</h4>
        <p>选择审核标准 → AI 一次性审阅 → 查看修改结果</p>
        <ul>
          <li>适合有明确审核标准的场景</li>
          <li>审阅速度快，一次出结果</li>
          <li>可批量修改和导出</li>
        </ul>
      </div>

      <!-- 深度交互模式 -->
      <div
        class="mode-card"
        :class="{ active: selectedMode === 'interactive' }"
        @click="selectedMode = 'interactive'"
      >
        <el-icon :size="48"><ChatDotRound /></el-icon>
        <h4>深度交互模式</h4>
        <p>AI 快速扫描 → 逐条讨论打磨 → 导出精修结果</p>
        <ul>
          <li>无需预设审核标准</li>
          <li>逐条深入讨论，精准修改</li>
          <li>适合重要/复杂合同</li>
        </ul>
        <el-tag type="success" size="small">NEW</el-tag>
      </div>
    </div>
  </div>
</template>
```

---

## 六、开发步骤（执行顺序）

### 阶段一：数据库层（预计工作量：小）

**步骤 1.1**：执行数据库迁移
- [ ] 在 Supabase 执行 `ALTER TABLE tasks ADD COLUMN review_mode...`
- [ ] 创建 `interactive_chats` 表
- [ ] 设置 RLS 策略
- [ ] 验证：检查 Supabase 后台，确认字段和表已创建

**步骤 1.2**：更新后端 models.py
- [ ] 在 `ReviewTask` 模型中添加 `review_mode` 字段
- [ ] 创建 `InteractiveChat` 模型
- [ ] 创建 `ChatMessage` 模型

### 阶段二：后端 API（预计工作量：中）

**步骤 2.1**：创建数据访问层
- [ ] 新建 `backend/src/contract_review/supabase_interactive.py`
- [ ] 实现 CRUD 操作：`create_chat`, `get_chat`, `update_chat`, `get_chats_by_task`

**步骤 2.2**：实现快速初审接口
- [ ] 在 `api_server.py` 添加 `POST /api/tasks/{task_id}/quick-review`
- [ ] 编写无标准审阅的 Prompt（参考 `prompts.py` 现有结构）
- [ ] 复用 `ReviewEngine`，但传入通用标准或空标准

**步骤 2.3**：实现对话接口
- [ ] 在 `api_server.py` 添加 `GET /api/interactive/{task_id}/items`
- [ ] 在 `api_server.py` 添加 `POST /api/interactive/{task_id}/items/{item_id}/chat`
- [ ] 在 `api_server.py` 添加 `POST /api/interactive/{task_id}/items/{item_id}/complete`
- [ ] 在 `prompts.py` 添加 `build_interactive_chat_messages()`

**步骤 2.4**：测试后端 API
- [ ] 使用 curl 或 Postman 测试所有新接口
- [ ] 验证对话历史正确存储和读取
- [ ] 验证 `review_results` 同步更新

### 阶段三：前端界面（预计工作量：大）

**步骤 3.1**：基础架构
- [ ] 新建 `frontend/src/api/interactive.js`
- [ ] 新建 `frontend/src/views/InteractiveResultView.vue`
- [ ] 在 `router/index.js` 添加路由

**步骤 3.2**：左侧导航组件
- [ ] 新建 `ItemNavigator.vue`
- [ ] 实现条目列表渲染（风险等级颜色、状态标记）
- [ ] 实现点击切换当前条目
- [ ] 实现进度统计显示

**步骤 3.3**：右侧工作区
- [ ] 新建 `ClauseCompare.vue`（原文 vs 建议对比）
- [ ] 新建 `ChatMessage.vue`（单条消息样式）
- [ ] 新建 `ChatWorkspace.vue`（整合对比区和聊天区）
- [ ] 实现消息发送和接收
- [ ] 实现"确认并继续"功能

**步骤 3.4**：入口改造
- [ ] 在 HomeView.vue 添加模式选择卡片
- [ ] 根据选择跳转到不同的流程
- [ ] 深度交互模式：上传 → 快速初审 → InteractiveResultView

**步骤 3.5**：导出功能对接
- [ ] 复用现有的 Redline 导出逻辑
- [ ] 确保 `user_confirmed` 状态正确同步

### 阶段四：联调与优化

**步骤 4.1**：端到端测试
- [ ] 完整流程测试：上传 → 快速初审 → 逐条对话 → 确认 → 导出
- [ ] 异常场景测试：网络中断、LLM 超时、并发操作

**步骤 4.2**：UI/UX 优化
- [ ] 参考 ChatGPT 样式优化聊天界面
- [ ] 添加 Loading 状态和动画
- [ ] 移动端适配（如需要）

**步骤 4.3**：性能优化
- [ ] 对话历史过长时的分页加载
- [ ] 消息发送的 debounce 处理

---

## 七、改进建议（相比 Gemini 原方案）

### 7.1 数据存储策略

**Gemini 方案**：在 `Review_Items` 表的每条记录中添加 `chat_thread` 字段

**改进方案**：新建独立的 `interactive_chats` 表

**理由**：
1. 本项目的审核条目存储在 `review_results.modifications` 的 JSONB 数组中，直接修改会导致结构混乱
2. 独立表更易于查询、索引和维护
3. 对话历史可能很长，独立存储避免影响主表性能
4. 便于后续扩展（如对话统计、导出对话记录等）

### 7.2 快速初审策略

**Gemini 方案**：复用现有初审接口

**改进方案**：新建独立的 `/quick-review` 接口

**理由**：
1. 现有接口需要先选择审核标准，而新模式的核心是"无标准快速扫描"
2. 两种模式的 Prompt 设计不同：
   - 标准模式：按照预设标准逐项检查
   - 交互模式：开放式发现问题，更注重识别关键风险点
3. 避免在现有接口中加入过多条件判断，保持代码清晰

### 7.3 前端架构

**Gemini 方案**：新建 `[id]/interactive/page.tsx`

**改进方案**：新建 `/views/InteractiveResultView.vue` + 组件拆分

**理由**：
1. 本项目是 Vue 3，不是 Next.js
2. 采用组件拆分（`ItemNavigator`、`ChatWorkspace`、`ClauseCompare`）更易于维护和复用
3. 聊天组件可能在未来用于其他场景（如标准库管理中的 AI 助手）

### 7.4 新增：快捷操作支持

**新增建议**：在对话界面添加快捷回复按钮

```vue
<div class="quick-actions">
  <el-button size="small" @click="sendQuickReply('同意这个建议')">
    👍 同意建议
  </el-button>
  <el-button size="small" @click="sendQuickReply('请解释一下为什么这样修改')">
    ❓ 请解释
  </el-button>
  <el-button size="small" @click="sendQuickReply('风险等级是否可以降低')">
    📉 降低风险
  </el-button>
  <el-button size="small" @click="sendQuickReply('请提供更激进的修改方案')">
    💪 更激进
  </el-button>
</div>
```

### 7.5 新增：上下文保持

**新增建议**：在对话中保持文档全文上下文

当用户讨论某一条款时，AI 应该能够引用文档中的其他相关条款。实现方式：

```python
def build_interactive_chat_messages(...):
    # 在 system prompt 中包含文档全文摘要
    system_prompt = f"""
    ...
    ## 文档全文（供参考）
    {document_summary}

    ## 当前聚焦的条款
    {original_clause}
    ...
    """
```

---

## 八、成本与第三方服务分析

### 8.1 第三方服务需求：无需新增付费服务

**结论：不需要引入任何新的付费第三方服务。**

现有技术栈完全满足需求：

| 服务类型 | 现有方案 | 是否满足新需求 |
|---------|---------|--------------|
| **前端托管** | Vercel | ✅ 完全满足 |
| **后端托管** | Render | ✅ 完全满足 |
| **数据库** | Supabase | ✅ 完全满足（Free Tier 500MB 足够） |
| **用户认证** | Clerk | ✅ 完全满足 |
| **LLM API** | DeepSeek / Gemini | ✅ 完全满足（按量付费） |
| **UI 组件库** | Element Plus (Vue 3) | ✅ 完全满足，开源免费 |

**关于 Gemini 提到的 shadcn/ui 和 Vercel AI SDK**：
- 这两个是 **React 生态** 的组件库，不适用于本项目（Vue 3）
- 本项目继续使用 **Element Plus**，它已经提供了足够的组件支持聊天界面

**关于实时通信**：
- 不需要购买 Pusher、Ably 等 WebSocket 服务
- 对话交互使用普通的 HTTP 请求即可（用户发送 → 等待 AI 回复 → 显示结果）
- 可选扩展：后续如需流式输出（打字机效果），Render 支持 HTTP Streaming，无需额外费用

### 8.2 LLM API 成本分析（重点关注）

这是**唯一会显著增加的运营成本**。

#### 成本对比

| 模式 | Token 消耗模式 | 单次审阅估算 |
|-----|---------------|-------------|
| **标准模式 (Batch)** | 1 次长输入 + 1 次长输出 | 约 10K-30K tokens |
| **深度交互模式 (Interactive)** | 初审 + N 轮对话（每轮累加历史） | 约 30K-100K+ tokens |

#### 成本增长原因

1. **对话历史累加**：每轮对话需要将历史消息重新发送给 LLM，Token 消耗随轮数叠加
2. **多条目处理**：每个条目独立对话，10 个条目 × 5 轮对话 = 50 次 LLM 调用
3. **上下文保持**：为保证 AI 理解合同全貌，每次调用都需包含文档摘要

#### 成本控制策略（已纳入开发计划）

| 策略 | 实现方式 | 预计效果 |
|-----|---------|---------|
| **历史消息截断** | 只保留最近 N 轮对话（建议 N=10） | 减少 50%+ Token |
| **文档摘要替代全文** | 初审时生成摘要，对话时只传摘要 | 减少 30%+ Token |
| **快捷回复** | 预设短回复模板 | 减少用户输入 Token |
| **批量确认** | 低风险条目一键确认，跳过对话 | 减少调用次数 |
| **对话轮数限制** | 单条目最多 20 轮对话 | 防止无限消耗 |
| **费用提示** | 前端显示预估消耗，用户确认后继续 | 用户感知成本 |

#### 计费建议

```python
# 后端计费逻辑建议
COST_CONFIG = {
    "batch_mode": {
        "base_credits": 1,  # 标准模式：1 积分/次
    },
    "interactive_mode": {
        "initial_review_credits": 1,  # 初审：1 积分
        "per_chat_credits": 0.1,  # 每轮对话：0.1 积分
        "max_free_chats_per_item": 5,  # 每条目前 5 轮免费
    }
}
```

### 8.3 数据库容量评估

**Supabase Free Tier：500MB**

| 数据类型 | 单条大小 | 10,000 条 | 占用比例 |
|---------|---------|----------|---------|
| 任务记录 (tasks) | ~1KB | ~10MB | 2% |
| 审阅结果 (review_results) | ~50KB | ~500MB | 100% |
| **对话记录 (interactive_chats)** | ~5KB | ~50MB | 10% |

**结论**：
- 对话记录主要是文本，存储效率高
- 500MB 足够支撑数千次完整的深度交互审阅
- 只有用户量大幅增长后才需要考虑升级（$25/月）

### 8.4 技术选型确认

| 组件 | Gemini 建议 | 本项目实际 | 最终决定 |
|-----|------------|-----------|---------|
| 前端框架 | React | Vue 3 | **保持 Vue 3** |
| UI 库 | shadcn/ui | Element Plus | **保持 Element Plus** |
| AI SDK | Vercel AI SDK | 自研 LLM Client | **保持自研方案** |
| 实时通信 | HTTP Streaming | HTTP 请求/响应 | **先用普通 HTTP，后续可升级流式** |

---

## 九、风险与注意事项

### 9.1 兼容性风险

| 风险 | 缓解措施 |
|-----|---------|
| 旧任务数据缺少 `review_mode` 字段 | 设置默认值 `batch`，代码中做空值处理 |
| 前端路由冲突 | 使用不同的路径 `/interactive/:taskId` |
| API 版本兼容 | 新接口使用独立路径，不影响现有接口 |

### 9.2 性能风险

| 风险 | 缓解措施 |
|-----|---------|
| 对话历史过长导致 LLM 调用变慢 | 设置最大历史消息数（如保留最近 10 轮） |
| 频繁对话导致配额快速消耗 | 前端添加发送频率限制，后端计费单独计算 |
| JSONB 字段过大 | 监控 `messages` 字段大小，必要时归档旧对话 |

### 9.3 用户体验风险

| 风险 | 缓解措施 |
|-----|---------|
| 用户不理解两种模式的区别 | 入口处添加清晰的说明和对比 |
| 逐条处理太繁琐 | 添加"批量确认低风险条目"功能 |
| 对话无限循环 | 设置单条目最大对话轮数（如 20 轮）并提示 |

---

## 十、后续扩展方向

完成 V1 后，可考虑以下扩展：

1. **智能条目排序**：高风险条目优先，或按用户历史偏好排序
2. **对话模板**：预设常见修改场景的对话模板
3. **协作功能**：多人同时审阅同一份合同，分配不同条目
4. **对话导出**：将对话历史导出为审阅记录文档
5. **学习反馈**：根据用户确认的修改，优化后续建议
6. **流式输出**：实现打字机效果，提升交互体验（Render 原生支持 HTTP Streaming）

---

## 十一、总结

本开发计划基于 Gemini 的建议进行了针对性调整，核心原则是：

1. **只增不改**：所有新功能通过新增字段、表、接口、页面实现，不修改现有逻辑
2. **数据复用**：审阅结果的核心数据结构（risks, modifications, actions）完全复用
3. **逻辑复用**：LLM 调用、Redline 导出等核心逻辑完全复用
4. **渐进开发**：按数据库 → 后端 → 前端的顺序逐步实现，每步可验证

预计这是一个中等规模的功能开发，主要工作量在前端聊天界面的实现上。建议分步实施，每完成一个阶段后进行验证再继续。
