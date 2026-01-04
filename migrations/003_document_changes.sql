-- Migration 003: Add document_changes table for tracking AI tool modifications
-- 用于跟踪AI工具对文档的修改，支持版本控制和回滚

-- 创建document_changes表
CREATE TABLE IF NOT EXISTS document_changes (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,

    -- 工具调用信息
    tool_name TEXT NOT NULL,
    arguments JSONB NOT NULL,
    result JSONB,

    -- 变更状态
    status TEXT NOT NULL DEFAULT 'pending',
    -- pending: 等待用户确认
    -- applied: 已应用
    -- rejected: 用户拒绝
    -- reverted: 已回滚

    -- 审计信息
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    applied_at TIMESTAMP WITH TIME ZONE,
    applied_by TEXT,

    -- 版本控制（利用Supabase MVCC）
    version INTEGER DEFAULT 1,
    parent_change_id TEXT REFERENCES document_changes(id) ON DELETE SET NULL,

    -- 外键约束
    CONSTRAINT fk_task FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- 创建索引以提高查询性能
CREATE INDEX idx_document_changes_task ON document_changes(task_id);
CREATE INDEX idx_document_changes_status ON document_changes(status);
CREATE INDEX idx_document_changes_created ON document_changes(created_at DESC);
CREATE INDEX idx_document_changes_tool ON document_changes(tool_name);

-- 创建视图：获取任务的变更历史
CREATE OR REPLACE VIEW task_change_history AS
SELECT
    dc.id,
    dc.task_id,
    dc.tool_name,
    dc.arguments,
    dc.result,
    dc.status,
    dc.created_at,
    dc.applied_at,
    dc.applied_by,
    dc.version,
    t.document_filename,
    t.our_party,
    t.created_at as task_created_at
FROM document_changes dc
JOIN tasks t ON dc.task_id = t.id
ORDER BY dc.created_at DESC;

-- 添加注释
COMMENT ON TABLE document_changes IS 'AI工具对文档的修改记录，支持版本控制和回滚';
COMMENT ON COLUMN document_changes.tool_name IS '工具名称（modify_paragraph、batch_replace_text等）';
COMMENT ON COLUMN document_changes.arguments IS '工具调用参数（JSON格式）';
COMMENT ON COLUMN document_changes.result IS '工具执行结果（JSON格式）';
COMMENT ON COLUMN document_changes.status IS '变更状态：pending/applied/rejected/reverted';
COMMENT ON COLUMN document_changes.parent_change_id IS '父变更ID，用于实现变更链';
