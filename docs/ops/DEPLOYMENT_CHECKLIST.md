# 部署前检查清单

## 1. 环境变量验证

### Render后端环境变量
```bash
# LLM API Keys
DEEPSEEK_API_KEY=sk-xxx
GEMINI_API_KEY=xxx

# Supabase配置
CONTRACT_DB_URL=https://xxx.supabase.co
CONTRACT_DB_KEY=eyJxxx...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJxxx...

# 可选配置
PYTHON_VERSION=3.11
```

### Vercel前端环境变量
```bash
# 如果前端有特殊配置需求
VITE_API_BASE_URL=https://contract-review-z9te.onrender.com
```

---

## 2. 代码部署确认

### 后端（Render）
- ✅ 最新commit已推送到GitHub: `18d1438`
- ⚠️ Render需要触发重新部署以拉取最新代码
- ⚠️ 检查部署日志是否有错误

### 前端（Vercel）
- ⚠️ 需要确认前端是否已部署最新代码
- ⚠️ 检查build日志

---

## 3. 数据库迁移确认

### Supabase
- ✅ migrations/003_document_changes.sql 已执行
- ⚠️ 验证表存在：

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'document_changes'
ORDER BY ordinal_position;
```

预期结果：11个列（id, task_id, tool_name, arguments, result, status, created_at, applied_at, applied_by, version, parent_change_id）

---

## 4. API端点可用性测试

### 测试chat_with_item_stream端点
```bash
# 需要替换实际的task_id和item_id
curl -X POST https://contract-review-z9te.onrender.com/api/interactive/{task_id}/items/{item_id}/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "message": "请帮我分析这个条款",
    "llm_provider": "deepseek"
  }'
```

预期：返回SSE流，包含data:开头的事件

### 测试变更管理API
```bash
# 获取变更列表
curl -X GET https://contract-review-z9te.onrender.com/api/tasks/{task_id}/changes \
  -H "Authorization: Bearer YOUR_TOKEN"
```

预期：返回JSON `{"task_id": "...", "changes": [...], "total": 0}`

---

## 5. 前端配置检查

### 确认API地址
打开 `frontend/src/api/interactive.js`，确认：
```javascript
const API_BASE_URL = 'https://contract-review-z9te.onrender.com/api'
```

### 确认document store已引入
检查构建后的文件是否包含document store相关代码

---

## 6. SSE配置检查（如果使用Nginx）

如果Render前面有Nginx代理，需要配置：
```nginx
location /api/interactive {
    proxy_pass http://backend;
    proxy_set_header X-Accel-Buffering no;  # 关键！
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

---

## 部署步骤

1. **触发后端重新部署**
   - 登录Render Dashboard
   - 找到contract-review项目
   - 点击"Manual Deploy" → "Deploy latest commit"
   - 等待部署完成（约3-5分钟）
   - 检查部署日志是否有错误

2. **触发前端重新部署**（如果需要）
   - Vercel通常自动部署
   - 检查部署状态

3. **验证部署成功**
   - 访问后端健康检查端点：`https://contract-review-z9te.onrender.com/health` 或 `/`
   - 访问前端首页，确认可正常访问

---

## 部署后立即测试

### 快速冒烟测试
1. 登录系统
2. 创建一个测试任务（上传小文档）
3. 进入交互式审阅
4. 在ChatPanel输入简单消息（不涉及工具调用）："你好"
5. 确认AI能正常回复

### 工具调用测试
1. 在ChatPanel输入："请修改第1段，把'甲方'改成'我方'"
2. 打开浏览器Console（F12）
3. 观察：
   - 是否显示 `Tool called: modify_paragraph`
   - 是否显示 `Tool result: ...`
   - 是否有ElMessage提示
4. 打开Supabase，检查document_changes表是否有新记录

---

## 常见问题排查

### 问题1：AI不调用工具，直接文本回复
**可能原因**：
- LLM没有收到tools参数
- 文档段落结构未注入

**排查**：
- 检查后端日志是否显示"文档包含 X 个段落"
- 检查llm.chat_with_tools是否被正确调用

### 问题2：SSE事件不推送
**可能原因**：
- Nginx缓冲未关闭
- 前端EventSource连接失败

**排查**：
- 检查Network tab，是否有event-stream请求
- 检查Response Headers是否有`X-Accel-Buffering: no`

### 问题3：工具调用失败
**可能原因**：
- paragraph_id无效
- Supabase连接失败

**排查**：
- 检查后端日志的错误信息
- 检查document_changes表权限

---

## 成功标准

✅ **部署成功**：
- 后端和前端都可访问
- 环境变量正确配置
- 数据库表存在

✅ **工具调用功能正常**：
- AI能识别修改意图并调用工具
- 后端成功执行工具并保存到数据库
- 前端收到SSE事件并显示提示
- Supabase有变更记录

✅ **变更管理功能正常**：
- 可以查询变更列表
- 可以应用/回滚变更

---

**预计部署+测试总时长：1-2小时**
