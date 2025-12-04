# 十行合同 - 当前交互流程文档

> 最后更新：2024年12月
> 用于后续开发参考

---

## 一、项目概述

AI辅助法务文本审阅系统，支持两种审阅模式：
- **标准模式**：使用预先定义的审核标准进行三阶段审阅
- **交互模式**：无需预设标准，AI自主审阅 + 多轮对话迭代

---

## 二、用户交互流程总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         首页 (HomeView)                          │
│                                                                 │
│  [新建审阅任务] ──────────────────────────────────────────────►  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    审阅流程页 (ReviewView)                        │
│                                                                 │
│  步骤1: 上传合同文档                                              │
│         └─ 自动识别：合同各方、材料类型、推荐任务名称                  │
│         └─ 弹出身份选择框（可查看文档预览）                          │
│                                                                 │
│  步骤2: 直接开始审阅（默认 AI 智能审阅模式）                         │
│         └─ 无需选择任何配置，上传文档后即可开始                       │
│                                                                 │
│  [高级选项]（默认折叠，点击展开）                                   │
│         ├─ 选择/上传审核标准                                      │
│         ├─ 选择业务条线                                          │
│         └─ 填写特殊要求                                          │
│                                                                 │
│  [开始审阅] ─────────────────────────────────────────────────►   │
└─────────────────────────────────────────────────────────────────┘
                              │
           ┌──────────────────┴──────────────────┐
           │                                     │
           ▼                                     ▼
┌─────────────────────────┐        ┌─────────────────────────────┐
│  标准模式结果页            │        │  交互审阅页                   │
│  (UnifiedResultView)     │        │  (InteractiveReviewView)    │
│                         │        │                             │
│  ├─ 风险点列表            │        │  ┌───────────┬───────────┐  │
│  ├─ 修改建议列表（可编辑）  │        │  │ 文档查看器  │  对话面板   │  │
│  ├─ 行动建议列表（可编辑）  │        │  │           │           │  │
│  └─ 统计摘要             │        │  │ 段落列表   │ 条目tabs  │  │
│                         │        │  │ 高亮定位   │ 原文vs建议 │  │
│  [导出]                  │        │  │           │ 对话历史   │  │
│   ├─ Word修订版          │        │  │           │ 输入框    │  │
│   ├─ Excel              │        │  │           │           │  │
│   ├─ JSON               │        │  └───────────┴───────────┘  │
│   └─ CSV                │        │                             │
└─────────────────────────┘        │  [标记完成] [导出]           │
                                   └─────────────────────────────┘
```

---

## 三、标准模式详细流程

### 3.1 审阅过程

```
用户操作                          后端处理                         前端展示
─────────────────────────────────────────────────────────────────────────

1. 上传文档 ──────────────►  DocumentPreprocessor          显示识别结果
   (PDF/Word/TXT)            ├─ 提取文本                    ├─ 合同各方
                             ├─ 识别合同各方                 ├─ 材料类型
                             └─ 推荐任务名称                 └─ 推荐名称

2. 选择标准 ──────────────►  加载标准内容                   显示标准预览
   ├─ 上传文件(Excel/CSV)
   ├─ 选择内置模板
   └─ 从标准库选择

3. 可选配置
   ├─ 选择业务条线
   └─ 填写特殊要求

4. 开始审阅 ──────────────►  ReviewEngine.review_document()
                             │
                             ├─ 阶段1: 风险识别 ─────────►  进度: 33%
                             │   └─ 生成 RiskPoint[]
                             │
                             ├─ 阶段2: 修改建议 ─────────►  进度: 66%
                             │   └─ 生成 ModificationSuggestion[]
                             │
                             └─ 阶段3: 行动建议 ─────────►  进度: 100%
                                 └─ 生成 ActionRecommendation[]

5. 查看结果 ◄──────────────  返回 ReviewResult              UnifiedResultView
                                                          ├─ 风险点表
                                                          ├─ 修改建议表
                                                          └─ 行动建议表
```

### 3.2 结果编辑

| 操作 | API | 说明 |
|------|-----|------|
| 编辑修改建议 | `PATCH /api/tasks/{taskId}/result/modifications/{id}` | 修改建议文本、优先级 |
| 编辑行动建议 | `PATCH /api/tasks/{taskId}/result/actions/{id}` | 修改描述、紧急程度 |
| 确认条目 | 同上，设置 `user_confirmed=true` | 标记为已确认 |

---

## 四、交互模式详细流程

### 4.1 启动审阅

```
用户操作                          后端处理                         前端展示
─────────────────────────────────────────────────────────────────────────

1. 上传文档 ──────────────►  同标准模式                     同标准模式

2. 可选配置
   ├─ 选择标准（非必须）
   └─ 选择业务条线

3. 深度交互审阅 ───────────►  InteractiveReviewEngine       进入交互页面
                             └─ unified_review()
                                 └─ 一次性生成完整结果
                                    ├─ risks[]
                                    ├─ modifications[]
                                    └─ actions[]
```

### 4.2 交互页面布局

```
┌────────────────────────────────────────────────────────────────────────┐
│  InteractiveReviewView                                                  │
├──────────────────────────────┬─────────────────────────────────────────┤
│                              │                                         │
│  DocumentViewer              │  ChatPanel                              │
│  ─────────────────────────   │  ─────────────────────────────────────  │
│                              │                                         │
│  段落1                        │  [条目1] [条目2] [条目3] ...  ← tabs    │
│  段落2  ← 高亮当前条目位置      │  ─────────────────────────────────────  │
│  段落3                        │                                         │
│  段落4                        │  原文：xxx                              │
│  ...                         │  建议：xxx                              │
│                              │  风险说明：xxx                           │
│  可滚动                       │  ─────────────────────────────────────  │
│  点击定位                      │                                         │
│                              │  [AI] 基于合同分析，建议修改为...          │
│                              │  [用户] 能否保留原有表述？                 │
│                              │  [AI] 可以，但需要注意...                 │
│                              │  ...                                    │
│                              │  ─────────────────────────────────────  │
│                              │  [输入框________________] [发送]         │
│                              │                                         │
│                              │  [标记完成]                              │
│                              │                                         │
└──────────────────────────────┴─────────────────────────────────────────┘
```

### 4.3 对话交互

```
用户操作                          后端处理                         数据变化
─────────────────────────────────────────────────────────────────────────

选择条目 ────────────────────►  getItemDetail()              加载对话历史

发送消息 ────────────────────►  sendChatMessage()
"请解释为什么要这样修改"          │
                               ├─ 调用 LLM 生成回复
                               ├─ 保存消息到 InteractiveChat
                               └─ 可能更新 current_suggestion

发送消息 ────────────────────►  同上
"请改成更温和的表述"              └─ 生成新建议，更新 suggestion_snapshot

标记完成 ────────────────────►  completeItem()               status='completed'
                               └─ 保存最终建议
```

---

## 五、导出功能

### 5.1 支持的导出格式

| 格式 | API | 说明 |
|------|-----|------|
| Word修订版 | `POST /api/tasks/{taskId}/export/redline/start` | 异步，带修订标记 |
| Excel | `GET /api/tasks/{taskId}/export/excel` | 同步直接下载 |
| JSON | `GET /api/tasks/{taskId}/export/json` | 完整结果 |
| CSV | `GET /api/tasks/{taskId}/export/csv` | 表格格式 |

### 5.2 Word修订版流程

```
1. 启动导出 ─────────────────►  redline_generator
                               ├─ 解析原文档
                               ├─ 应用修改建议
                               │   ├─ 删除线标记原文
                               │   └─ 插入标记新文本
                               └─ 可选：添加批注（行动建议）

2. 轮询状态 ─────────────────►  返回进度百分比

3. 下载文件 ◄────────────────   返回 .docx 文件
```

---

## 六、关键API端点

### 6.1 任务管理
```
POST   /api/tasks                    创建任务
GET    /api/tasks/{taskId}           获取任务详情
GET    /api/tasks/{taskId}/status    获取状态（轮询）
DELETE /api/tasks/{taskId}           删除任务
```

### 6.2 文档处理
```
POST   /api/tasks/{taskId}/document     上传文档
POST   /api/tasks/{taskId}/preprocess   预处理（识别各方）
GET    /api/tasks/{taskId}/document/text 获取段落化文本
```

### 6.3 审阅
```
POST   /api/tasks/{taskId}/review          标准模式审阅
POST   /api/tasks/{taskId}/unified-review  交互模式审阅
GET    /api/tasks/{taskId}/result          获取结果
```

### 6.4 交互对话
```
GET    /api/interactive/{taskId}/items              获取所有条目
GET    /api/interactive/{taskId}/items/{itemId}     获取条目详情
POST   /api/interactive/{taskId}/items/{itemId}/chat 发送消息
POST   /api/interactive/{taskId}/items/{itemId}/complete 标记完成
```

---

## 七、数据模型关系

```
ReviewTask (任务)
    │
    ├── document (文档)
    ├── standard (标准，可选)
    ├── business_line (业务条线，可选)
    │
    └── ReviewResult (结果)
            │
            ├── RiskPoint[] (风险点)
            │       │
            │       └──┐
            │          │
            ├── ModificationSuggestion[] (修改建议)
            │       │   关联 risk_id
            │       │
            │       └── InteractiveChat (对话，交互模式)
            │
            └── ActionRecommendation[] (行动建议)
                    │
                    └── InteractiveChat (对话，交互模式)
```

---

## 八、前端路由

| 路由 | 组件 | 功能 |
|------|------|------|
| `/` | HomeView | 首页 |
| `/documents` | DocumentsView | 文档/任务列表 |
| `/review/:taskId` | ReviewView | 审阅流程（两种模式入口） |
| `/interactive/:taskId` | InteractiveReviewView | 交互审阅工作区 |
| `/review-result/:taskId` | UnifiedResultView | 统一结果页 |
| `/standards` | StandardsView | 标准库管理 |
| `/business` | BusinessView | 业务条线管理 |

---

## 九、状态管理 (Pinia Store)

### review store (主store)
```javascript
{
  currentTask: Task,          // 当前任务
  reviewResult: ReviewResult, // 审阅结果
  isReviewing: boolean,       // 审阅中
  progress: {                 // 进度
    phase: string,
    percentage: number
  }
}
```

### settings store
```javascript
{
  llmProvider: 'deepseek' | 'gemini'  // LLM选择
}
```

---

## 十、后续开发注意事项

1. **两种模式的入口统一在 ReviewView**
   - 标准模式：需要选择标准
   - 交互模式：标准可选

2. **交互模式的对话记录**
   - 存储在 `interactive_chats` 表
   - 每个条目（修改/行动建议）有独立对话

3. **导出时机**
   - 标准模式：审阅完成后即可导出
   - 交互模式：建议在条目对话完成后导出

4. **LLM Fallback**
   - 主：DeepSeek
   - 备：Gemini
   - 自动切换，用户无感知

5. **流式输出**
   - 交互对话支持 SSE (Server-Sent Events) 流式响应
   - 前端实时显示 AI 回复，带打字光标效果
   - 后端 API: `POST /api/interactive/{task_id}/items/{item_id}/chat/stream`
   - 事件类型：
     - `chunk`: 文本片段
     - `suggestion`: 更新后的建议
     - `done`: 完成信号
     - `error`: 错误信息

---

*文档结束*
