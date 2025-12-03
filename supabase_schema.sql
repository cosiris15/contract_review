-- =====================================================
-- 法务文本审阅系统 - Supabase 数据库表结构
-- =====================================================

-- 1. 审阅任务表
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,  -- Clerk 用户 ID
    name TEXT NOT NULL,
    our_party TEXT NOT NULL,
    material_type TEXT NOT NULL DEFAULT 'contract',
    language TEXT NOT NULL DEFAULT 'zh-CN',
    status TEXT NOT NULL DEFAULT 'created',
    message TEXT,
    progress JSONB DEFAULT '{"stage": "idle", "percentage": 0, "message": ""}',
    document_filename TEXT,  -- 原始文件名（用于显示）
    document_storage_name TEXT,  -- 安全存储名（UUID+扩展名，用于 Storage）
    standard_filename TEXT,  -- 原始文件名（用于显示）
    standard_storage_name TEXT,  -- 安全存储名（UUID+扩展名，用于 Storage）
    standard_template TEXT,
    -- Redline 导出文件信息
    redline_filename TEXT,           -- 修订版文件原始名（用于显示）
    redline_storage_name TEXT,       -- 修订版文件存储名（UUID+.docx）
    redline_generated_at TIMESTAMPTZ, -- 修订版生成时间
    redline_applied_count INTEGER,    -- 应用的修改数量
    redline_comments_count INTEGER,   -- 添加的批注数量
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 注意：如需在已有数据库上添加这些字段，请执行以下迁移SQL：
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS redline_filename TEXT;
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS redline_storage_name TEXT;
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS redline_generated_at TIMESTAMPTZ;
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS redline_applied_count INTEGER;
-- ALTER TABLE tasks ADD COLUMN IF NOT EXISTS redline_comments_count INTEGER;

-- 2. 审阅结果表
CREATE TABLE review_results (
    id SERIAL PRIMARY KEY,
    task_id TEXT UNIQUE NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    document_name TEXT,
    document_path TEXT,
    material_type TEXT,
    our_party TEXT,
    review_standards_used TEXT,
    language TEXT DEFAULT 'zh-CN',
    risks JSONB DEFAULT '[]',
    modifications JSONB DEFAULT '[]',
    actions JSONB DEFAULT '[]',
    summary JSONB DEFAULT '{}',
    llm_model TEXT,
    prompt_version TEXT DEFAULT '1.0',
    reviewed_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 标准集合表
CREATE TABLE standard_collections (
    id TEXT PRIMARY KEY,
    user_id TEXT,  -- NULL 表示系统预设
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    material_type TEXT DEFAULT 'both',
    is_preset BOOLEAN DEFAULT FALSE,
    language TEXT DEFAULT 'zh-CN',
    usage_instruction TEXT,  -- 适用说明（AI 生成）
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 审核标准表
CREATE TABLE review_standards (
    id TEXT PRIMARY KEY,
    collection_id TEXT REFERENCES standard_collections(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    item TEXT NOT NULL,
    description TEXT NOT NULL,
    risk_level TEXT DEFAULT 'medium',
    applicable_to JSONB DEFAULT '["contract", "marketing"]',
    usage_instruction TEXT,
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. 创建索引（提升查询性能）
CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX idx_review_results_task_id ON review_results(task_id);
CREATE INDEX idx_standard_collections_user_id ON standard_collections(user_id);
CREATE INDEX idx_review_standards_collection_id ON review_standards(collection_id);
CREATE INDEX idx_review_standards_category ON review_standards(category);

-- 6. 自动更新 updated_at 的触发器函数
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 7. 为需要的表添加触发器
CREATE TRIGGER tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER standard_collections_updated_at
    BEFORE UPDATE ON standard_collections
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER review_standards_updated_at
    BEFORE UPDATE ON review_standards
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- 8. 启用 Row Level Security (RLS)
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE standard_collections ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_standards ENABLE ROW LEVEL SECURITY;

-- 9. RLS 策略：用户只能访问自己的数据（service_role 可绕过）
-- 任务表策略
CREATE POLICY "Users can view own tasks" ON tasks
    FOR SELECT USING (auth.uid()::text = user_id);
CREATE POLICY "Users can insert own tasks" ON tasks
    FOR INSERT WITH CHECK (auth.uid()::text = user_id);
CREATE POLICY "Users can update own tasks" ON tasks
    FOR UPDATE USING (auth.uid()::text = user_id);
CREATE POLICY "Users can delete own tasks" ON tasks
    FOR DELETE USING (auth.uid()::text = user_id);

-- 审阅结果策略（通过 task 关联）
CREATE POLICY "Users can view own results" ON review_results
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM tasks WHERE tasks.id = review_results.task_id AND tasks.user_id = auth.uid()::text)
    );
CREATE POLICY "Users can insert own results" ON review_results
    FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM tasks WHERE tasks.id = review_results.task_id AND tasks.user_id = auth.uid()::text)
    );
CREATE POLICY "Users can update own results" ON review_results
    FOR UPDATE USING (
        EXISTS (SELECT 1 FROM tasks WHERE tasks.id = review_results.task_id AND tasks.user_id = auth.uid()::text)
    );

-- 标准集合策略（预设集合所有人可见）
CREATE POLICY "Users can view own or preset collections" ON standard_collections
    FOR SELECT USING (is_preset = TRUE OR user_id = auth.uid()::text OR user_id IS NULL);
CREATE POLICY "Users can insert own collections" ON standard_collections
    FOR INSERT WITH CHECK (user_id = auth.uid()::text);
CREATE POLICY "Users can update own collections" ON standard_collections
    FOR UPDATE USING (user_id = auth.uid()::text AND is_preset = FALSE);
CREATE POLICY "Users can delete own collections" ON standard_collections
    FOR DELETE USING (user_id = auth.uid()::text AND is_preset = FALSE);

-- 审核标准策略（通过 collection 关联）
CREATE POLICY "Users can view standards in accessible collections" ON review_standards
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM standard_collections
            WHERE standard_collections.id = review_standards.collection_id
            AND (standard_collections.is_preset = TRUE OR standard_collections.user_id = auth.uid()::text OR standard_collections.user_id IS NULL)
        )
    );
CREATE POLICY "Users can manage standards in own collections" ON review_standards
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM standard_collections
            WHERE standard_collections.id = review_standards.collection_id
            AND standard_collections.user_id = auth.uid()::text
        )
    );
