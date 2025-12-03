-- =====================================================
-- 深度交互审阅模式 - 数据库迁移脚本
-- 执行方式：在 Supabase SQL Editor 中运行
-- =====================================================

-- 1. 为 tasks 表添加 review_mode 字段
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS review_mode TEXT DEFAULT 'batch';

-- 添加索引以提升查询性能
CREATE INDEX IF NOT EXISTS idx_tasks_review_mode ON tasks(review_mode);

-- 添加字段注释
COMMENT ON COLUMN tasks.review_mode IS 'batch = 标准模式, interactive = 深度交互模式';

-- 2. 创建 interactive_chats 表（存储每个条目的对话历史）
CREATE TABLE IF NOT EXISTS interactive_chats (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    item_id TEXT NOT NULL,                  -- 对应 modification.id 或 action.id
    item_type TEXT NOT NULL DEFAULT 'modification',  -- 'modification' | 'action'
    messages JSONB DEFAULT '[]',            -- 对话历史
    status TEXT DEFAULT 'pending',          -- 'pending' | 'in_progress' | 'completed'
    current_suggestion TEXT,                -- 当前最新建议
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 添加索引
CREATE INDEX IF NOT EXISTS idx_interactive_chats_task_id ON interactive_chats(task_id);
CREATE INDEX IF NOT EXISTS idx_interactive_chats_item_id ON interactive_chats(item_id);
CREATE INDEX IF NOT EXISTS idx_interactive_chats_status ON interactive_chats(status);

-- 3. 启用行级安全 (RLS)
ALTER TABLE interactive_chats ENABLE ROW LEVEL SECURITY;

-- 4. 创建 RLS 策略（通过 tasks 表关联用户）
-- 注意：使用 service_role key 时可以绕过 RLS
DROP POLICY IF EXISTS "Users can manage own chats" ON interactive_chats;
CREATE POLICY "Users can manage own chats" ON interactive_chats
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM tasks
            WHERE tasks.id = interactive_chats.task_id
            AND tasks.user_id = auth.uid()::text
        )
    );

-- 5. 添加 updated_at 自动更新触发器
-- 注意：update_updated_at 函数应该已存在（在主 schema 中创建）
DROP TRIGGER IF EXISTS interactive_chats_updated_at ON interactive_chats;
CREATE TRIGGER interactive_chats_updated_at
    BEFORE UPDATE ON interactive_chats
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- =====================================================
-- 验证脚本执行结果
-- =====================================================
-- 执行以下查询验证：
-- SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_name = 'tasks' AND column_name = 'review_mode';
-- SELECT * FROM information_schema.tables WHERE table_name = 'interactive_chats';
