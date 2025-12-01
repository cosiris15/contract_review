-- =====================================================
-- 迁移脚本: 添加安全存储文件名字段
-- 用于解决 Supabase Storage 不支持中文文件名的问题
-- =====================================================

-- 为 tasks 表添加新字段
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS document_storage_name TEXT;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS standard_storage_name TEXT;

-- 添加注释说明字段用途
COMMENT ON COLUMN tasks.document_storage_name IS '文档的安全存储名（UUID+扩展名），用于 Supabase Storage';
COMMENT ON COLUMN tasks.standard_storage_name IS '标准文件的安全存储名（UUID+扩展名），用于 Supabase Storage';
