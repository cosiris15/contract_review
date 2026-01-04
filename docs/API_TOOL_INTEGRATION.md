# API Server 工具调用集成指南

## 修改文件：backend/api_server.py

### 第1步：添加导入（文件顶部）

在现有的导入语句后添加：

```python
# 在文件顶部，约第60-70行附近，添加这些导入
from src.contract_review.document_tools import DOCUMENT_TOOLS, DocumentToolExecutor
from src.contract_review.sse_protocol import (
    SSEEventType,
    create_tool_thinking_event,
    create_tool_call_event,
    create_tool_result_event,
    create_tool_error_event,
    create_doc_update_event,
    create_message_delta_event,
    create_done_event,
    create_error_event,
)
```

### 第2步：修改 chat_with_item_stream 函数

**位置**：约第4943行 `@app.post("/api/interactive/{task_id}/items/{item_id}/chat/stream")`

#### 2.1 在函数开头获取文档段落（约第4970行之后）

```python
# 在 result = storage_manager.load_result(task_id) 之后添加

# 获取文档段落结构（用于工具调用验证）
doc_paragraphs = []
try:
    # 从任务中获取文档文本
    doc_text = getattr(task, 'document', '') or ''
    if doc_text:
        # 简单按换行分段（实际应该用更复杂的逻辑）
        paragraphs = doc_text.split('\n\n')
        doc_paragraphs = [
            {"id": i+1, "content": para.strip()}
            for i, para in enumerate(paragraphs)
            if para.strip()
        ]
    logger.info(f"文档包含 {len(doc_paragraphs)} 个段落")
except Exception as e:
    logger.warning(f"无法解析文档段落: {e}")
```

#### 2.2 修改 event_generator 函数（约第5029行）

将现有的 `async def event_generator():` 替换为支持工具调用的版本：

```python
async def event_generator():
    """生成 SSE 事件流（支持工具调用）"""
    full_response = ""
    updated_suggestion = ""

    try:
        # 推送思考事件
        yield create_tool_thinking_event("正在分析您的请求...")

        # 构建消息（这里调用现有的build_item_chat_messages）
        from src.contract_review.prompts_interactive import build_item_chat_messages
        messages = build_item_chat_messages(
            original_clause=original_text or (modification.original_text if modification else ""),
            current_suggestion=chat.current_suggestion or (modification.suggested_text if modification else ""),
            risk_description=risk.description if risk else "",
            user_message=request.message,
            chat_history=chat_history,
            document_summary="",
            language=getattr(task, 'language', 'zh-CN'),
        )

        # 注入文档结构到系统消息（防止AI幻觉）
        if doc_paragraphs and messages:
            from src.contract_review.prompts_interactive import format_document_structure
            doc_structure = format_document_structure(doc_paragraphs, max_paragraphs=100)

            # 在第一个系统消息后追加文档结构
            if messages[0]["role"] == "system":
                messages[0]["content"] += f"\n\n**完整文档结构（用于工具调用）：**\n{doc_structure}\n\n**重要：使用工具时，paragraph_id 必须是上述列表中实际存在的ID**"

        # 调用LLM（支持工具）
        response_text, tool_calls = await engine.llm.chat_with_tools(
            messages=messages,
            tools=DOCUMENT_TOOLS,
            temperature=0.3,
        )

        # 处理工具调用
        if tool_calls:
            tool_executor = DocumentToolExecutor(supabase)

            for tool_call in tool_calls:
                tool_id = tool_call["id"]
                tool_name = tool_call["function"]["name"]
                tool_args = json_module.loads(tool_call["function"]["arguments"])

                # 推送工具调用事件
                yield create_tool_call_event(tool_id, tool_name, tool_args)

                # 执行工具
                result = await tool_executor.execute_tool(
                    tool_call=tool_call,
                    task_id=task_id,
                    document_paragraphs=doc_paragraphs
                )

                # 推送工具结果
                if result["success"]:
                    yield create_tool_result_event(
                        tool_id,
                        True,
                        result["message"],
                        result.get("data")
                    )

                    # 如果是文档修改类工具，推送doc_update事件
                    if tool_name in ["modify_paragraph", "batch_replace_text", "insert_clause"]:
                        yield create_doc_update_event(
                            result["change_id"],
                            tool_name,
                            result["data"]
                        )
                else:
                    yield create_tool_error_event(tool_id, result["message"])

        # 流式推送AI回复文本
        if response_text:
            for word in response_text.split():
                yield create_message_delta_event(word + " ")
                await asyncio.sleep(0.01)  # 模拟打字效果

            full_response = response_text

        # 保存对话记录
        if full_response or tool_calls:
            # 添加用户消息
            interactive_manager.add_message(
                chat_id=chat.id,
                role="user",
                content=request.message,
            )

            # 添加AI回复（包含工具调用信息）
            interactive_manager.add_message(
                chat_id=chat.id,
                role="assistant",
                content=full_response or "已执行操作",
                suggestion_snapshot=updated_suggestion or chat.current_suggestion,
            )

        # 完成
        yield create_done_event(True)

    except Exception as e:
        logger.error(f"流式对话失败: {e}", exc_info=True)
        yield create_error_event(str(e))
```

### 第3步：测试修改

修改完成后，重启后端服务器：

```bash
cd backend
# 确保安装了所有依赖
pip install -r requirements.txt

# 启动服务器
python api_server.py
```

## 验证工具调用是否生效

### 方法1：查看日志

后端应该输出类似的日志：
```
INFO - 文档包含 50 个段落
INFO - 保存变更记录: change_abc123 (modify_paragraph)
```

### 方法2：使用curl测试（可选）

```bash
curl -X POST http://localhost:8000/api/interactive/TASK_ID/items/ITEM_ID/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "请修改第3段", "llm_provider": "deepseek"}'
```

应该看到SSE事件流包含 `tool_call`, `tool_result`, `doc_update` 等事件。

## 常见问题

### Q: 如果没有文档段落会怎样？
A: 代码会捕获异常，工具调用仍然可以工作，只是无法验证paragraph_id是否有效。

### Q: 工具调用失败怎么办？
A: 会推送`tool_error`事件，前端可以显示错误信息给用户。

### Q: 如何禁用工具调用？
A: 在调用`chat_with_tools`时传入空的tools列表`[]`，或者改回调用`chat`方法。

---

**下一步**：完成这个修改后，继续实施第9步：添加变更管理API端点。
