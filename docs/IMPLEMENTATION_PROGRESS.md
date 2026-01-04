# 意图转执行功能实施进度

> 为合同审阅系统添加"意图转执行"的Agent能力
> 开始时间：2026-01-04
> 最后更新：2026-01-04

## 总体进度：35% (6/17任务完成)

### ✅ 已完成（阶段一、阶段二）

#### 阶段一：后端工具系统 (100%完成)

1. **✅ document_tools.py** - 文档操作工具集
   - 文件位置：`backend/src/contract_review/document_tools.py`
   - 包含4个工具：
     - `modify_paragraph` - 修改段落
     - `batch_replace_text` - 批量替换文本
     - `insert_clause` - 插入新条款
     - `read_paragraph` - 读取段落（用于参考）
   - `DocumentToolExecutor` 类负责执行工具并记录变更

2. **✅ llm_client.py 扩展** - DeepSeek客户端支持工具调用
   - 新增方法：`chat_with_tools(messages, tools, ...) -> Tuple[str, List[Dict]]`
   - 返回格式：(文本回复, 工具调用列表)
   - 兼容OpenAI Function Calling格式

3. **✅ gemini_client.py 扩展** - Gemini客户端支持工具调用
   - 新增方法：`chat_with_tools(messages, tools, ...) -> Tuple[str, List[Dict]]`
   - 新增方法：`_convert_tools_to_gemini_format()` - 格式转换
   - 自动转换OpenAI格式到Gemini Function Calling格式

4. **✅ fallback_llm.py 扩展** - Fallback机制支持工具调用
   - 新增方法：`chat_with_tools(messages, tools, ...) -> Tuple[str, List[Dict]]`
   - 主LLM失败自动切换到备用LLM
   - 优雅降级：不支持工具调用时回退到普通chat

#### 阶段二：SSE协议与数据库 (100%完成)

5. **✅ sse_protocol.py** - SSE事件协议定义
   - 文件位置：`backend/src/contract_review/sse_protocol.py`
   - 定义8种事件类型：
     - `tool_thinking` - AI思考
     - `tool_call` - 工具调用
     - `tool_result` - 工具结果
     - `tool_error` - 工具错误
     - `doc_update` - 文档更新（触发Pinia）
     - `message_delta` - 流式文本
     - `message_done` - 消息完成
     - `error/done` - 错误/完成
   - 提供便捷函数：`thinking()`, `tool_call()`, `doc_update()` 等

6. **✅ Supabase Migration** - 数据库表创建
   - 文件位置：`migrations/003_document_changes.sql`
   - 创建表：`document_changes` - 记录所有文档修改
   - 字段包括：
     - tool_name, arguments, result
     - status (pending/applied/rejected/reverted)
     - 审计字段：created_at, applied_at, applied_by
     - 版本控制：version, parent_change_id
   - 创建视图：`task_change_history` - 变更历史查询
   - 创建索引：task_id, status, created_at, tool_name

### 🔄 进行中

7. **🔄 prompts_interactive.py 修改** - 注入文档结构到Prompt
   - **下一步操作**：修改 `build_item_chat_messages()` 函数
   - **目的**：防止AI幻觉，在系统消息中注入完整文档段落结构
   - **关键**：让AI知道有效的paragraph_id范围

### 📋 待完成

#### 阶段三：API端点集成 (0%完成)

8. **修改api_server.py** - 增强chat_with_item_stream端点
   - 导入新模块：`document_tools`, `sse_protocol`
   - 修改`chat_with_item_stream`函数：
     - 获取文档段落结构
     - 注入结构到Prompt
     - 调用`llm.chat_with_tools()`而不是普通chat
     - 执行工具调用
     - 推送SSE事件（tool_call, tool_result, doc_update等）

9. **添加变更管理API端点**
   - `GET /api/tasks/{task_id}/changes` - 获取变更列表
   - `POST /api/tasks/{task_id}/changes/{change_id}/apply` - 应用变更
   - `POST /api/tasks/{task_id}/changes/{change_id}/revert` - 回滚变更

#### 阶段四：前端实现 (0%完成)

10. **创建stores/document.js** - Pinia文档状态管理
11. **增强ChatPanel.vue** - 处理SSE工具调用事件
12. **增强DiffView.vue** - Git风格的diff显示
13. **修改DocumentViewer.vue** - 显示段落修改状态

#### 阶段五：测试与优化 (0%完成)

14-16. 测试工具调用流程、SSE事件推送、端到端集成测试

#### 阶段六：文档与部署 (0%完成)

17. 更新INTERACTION_FLOW.md，准备部署到Render/Vercel

## 技术栈确认

- ✅ 后端：Python FastAPI + Supabase
- ✅ LLM：DeepSeek/Gemini (支持Function Calling)
- ✅ 前端：Vue 3 + Pinia + Element Plus
- ✅ 协议：SSE (Server-Sent Events)
- ✅ 无需引入Vercel AI SDK或React生态工具

## 关键设计决策

1. **防止AI幻觉**：在每次工具调用前注入完整文档段落结构到Prompt
2. **严格的SSE协议**：使用枚举类型和格式化函数，确保前后端一致
3. **Diff View体验**：前端维护original和draft两个版本，支持diff显示
4. **利用Supabase MVCC**：通过version字段实现变更版本控制
5. **渐进式实施**：后端→协议→前端，每阶段可独立测试

## 如何继续实施

### 立即下一步（从第7步继续）

```python
# 修改 backend/src/contract_review/prompts_interactive.py

def build_item_chat_messages(
    # ... 现有参数 ...
    document_paragraphs: List[Dict],  # 新增：文档段落结构
    enable_tools: bool = True  # 新增：是否启用工具
) -> List[Dict[str, str]]:

    # 构建文档结构描述
    doc_structure = "\n".join([
        f"[段落 {p['id']}] {p['content'][:50]}..."
        for p in document_paragraphs[:100]
    ])

    system_message = f"""你是一位资深法务顾问...

**完整文档结构：**
{doc_structure}

**重要提示：**
1. 使用工具时，paragraph_id 必须是上述文档结构中实际存在的ID
2. 在修改前，如需参考其他条款，可使用 read_paragraph 工具
...
"""
```

### 部署前准备

1. **运行Supabase Migration**
   ```bash
   # 在Supabase Dashboard的SQL Editor中执行
   migrations/003_document_changes.sql
   ```

2. **测试后端工具系统**
   ```bash
   cd backend
   python -m pytest tests/test_document_tools.py  # 如果有测试
   ```

3. **前端依赖检查**
   ```bash
   cd frontend
   # 确认已有diff库（用于DiffView）
   npm install diff
   ```

## 文件清单

### 新建文件
- `backend/src/contract_review/document_tools.py` (277行)
- `backend/src/contract_review/sse_protocol.py` (304行)
- `migrations/003_document_changes.sql` (57行)

### 修改文件
- `backend/src/contract_review/llm_client.py` (+55行)
- `backend/src/contract_review/gemini_client.py` (+165行)
- `backend/src/contract_review/fallback_llm.py` (+94行)

### 待修改文件
- `backend/src/contract_review/prompts_interactive.py`
- `backend/api_server.py`
- `frontend/src/stores/document.js` (新建)
- `frontend/src/components/interactive/ChatPanel.vue`
- `frontend/src/components/interactive/DiffView.vue`
- `frontend/src/components/interactive/DocumentViewer.vue`

## 预估剩余工作量

- 后端API集成：2-3小时
- 前端Pinia Store：1小时
- 前端UI增强：3-4小时
- 测试与调试：2-3小时
- 文档更新：30分钟

**总计：约8-12小时（1-1.5工作日）**

## 注意事项

1. **Supabase Migration必须先执行**，否则document_changes表不存在会报错
2. **前端需要安装diff库**：`npm install diff`
3. **测试时使用小文档**（<50段落）避免token超限
4. **Render部署确保环境变量**包含LLM API Keys
5. **SSE在Nginx后需要配置** `X-Accel-Buffering: no`

---

*如果会话中断，可从"如何继续实施"部分恢复*
