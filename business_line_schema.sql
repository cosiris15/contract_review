-- =====================================================
-- 业务条线管理 - 数据库 Schema 更新
-- 执行顺序：请按以下顺序在 Supabase SQL Editor 中执行
-- =====================================================

-- =====================================================
-- 第一部分：创建新表
-- =====================================================

-- 1. 业务条线表 (对应 standard_collections)
CREATE TABLE business_lines (
    id TEXT PRIMARY KEY,
    user_id TEXT,                              -- NULL 表示系统预设
    name TEXT NOT NULL,                        -- 业务线名称，如"科技业务线"
    description TEXT DEFAULT '',               -- 业务线描述
    industry TEXT DEFAULT '',                  -- 所属行业
    is_preset BOOLEAN DEFAULT FALSE,           -- 是否为系统预设
    language TEXT DEFAULT 'zh-CN',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 业务背景信息表 (对应 review_standards)
CREATE TABLE business_contexts (
    id TEXT PRIMARY KEY,
    business_line_id TEXT NOT NULL REFERENCES business_lines(id) ON DELETE CASCADE,
    category TEXT NOT NULL,                    -- 分类：core_focus/typical_risks/compliance/business_practices/negotiation_priorities
    item TEXT NOT NULL,                        -- 要点名称
    description TEXT NOT NULL,                 -- 详细说明
    priority TEXT DEFAULT 'medium',            -- 重要程度: high/medium/low
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- 第二部分：创建索引
-- =====================================================

CREATE INDEX idx_business_lines_user_id ON business_lines(user_id);
CREATE INDEX idx_business_lines_is_preset ON business_lines(is_preset);
CREATE INDEX idx_business_lines_language ON business_lines(language);
CREATE INDEX idx_business_contexts_line_id ON business_contexts(business_line_id);
CREATE INDEX idx_business_contexts_category ON business_contexts(category);

-- =====================================================
-- 第三部分：创建触发器（自动更新 updated_at）
-- 注意：update_updated_at() 函数已在原 schema 中定义
-- =====================================================

CREATE TRIGGER business_lines_updated_at
    BEFORE UPDATE ON business_lines
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER business_contexts_updated_at
    BEFORE UPDATE ON business_contexts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- =====================================================
-- 第四部分：启用 Row Level Security (RLS)
-- =====================================================

ALTER TABLE business_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_contexts ENABLE ROW LEVEL SECURITY;

-- =====================================================
-- 第五部分：创建 RLS 策略
-- =====================================================

-- 业务条线表策略（预设条线所有人可见）
CREATE POLICY "Users can view own or preset business_lines" ON business_lines
    FOR SELECT USING (is_preset = TRUE OR user_id = auth.uid()::text OR user_id IS NULL);

CREATE POLICY "Users can insert own business_lines" ON business_lines
    FOR INSERT WITH CHECK (user_id = auth.uid()::text);

CREATE POLICY "Users can update own business_lines" ON business_lines
    FOR UPDATE USING (user_id = auth.uid()::text AND is_preset = FALSE);

CREATE POLICY "Users can delete own business_lines" ON business_lines
    FOR DELETE USING (user_id = auth.uid()::text AND is_preset = FALSE);

-- 业务背景表策略（通过 business_line 关联）
CREATE POLICY "Users can view contexts in accessible lines" ON business_contexts
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM business_lines
            WHERE business_lines.id = business_contexts.business_line_id
            AND (business_lines.is_preset = TRUE OR business_lines.user_id = auth.uid()::text OR business_lines.user_id IS NULL)
        )
    );

CREATE POLICY "Users can manage contexts in own lines" ON business_contexts
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM business_lines
            WHERE business_lines.id = business_contexts.business_line_id
            AND business_lines.user_id = auth.uid()::text
        )
    );

-- =====================================================
-- 第六部分：修改现有表（添加业务条线关联字段）
-- =====================================================

-- 任务表新增业务条线字段
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS business_line_id TEXT REFERENCES business_lines(id);

-- 审阅结果表新增业务条线信息（用于结果记录）
ALTER TABLE review_results ADD COLUMN IF NOT EXISTS business_line_id TEXT;
ALTER TABLE review_results ADD COLUMN IF NOT EXISTS business_line_name TEXT;

-- =====================================================
-- 第七部分：插入预设业务条线数据
-- =====================================================

-- 1. 科技业务线
INSERT INTO business_lines (id, user_id, name, description, industry, is_preset, language)
VALUES (
    'preset_tech',
    NULL,
    '科技业务线',
    '适用于技术服务、软件开发、SaaS服务、技术许可等科技类业务的合同审阅。重点关注知识产权保护、技术成果归属、数据安全合规等方面。',
    '科技/互联网',
    TRUE,
    'zh-CN'
);

INSERT INTO business_contexts (id, business_line_id, category, item, description, priority) VALUES
('ctx_tech_001', 'preset_tech', 'core_focus', '知识产权归属', '明确软件著作权、专利权、技术成果的归属，特别关注定制开发场景下的权属约定，避免核心技术资产流失', 'high'),
('ctx_tech_002', 'preset_tech', 'core_focus', '源代码交付与保护', '审查源代码交付条件、交付范围、源代码托管安排，确保技术资产得到妥善保护', 'high'),
('ctx_tech_003', 'preset_tech', 'core_focus', '技术保密义务', '审查保密条款的范围、期限、违约责任，确保核心技术秘密不被泄露', 'high'),
('ctx_tech_004', 'preset_tech', 'typical_risks', '技术泄露风险', '核心算法、架构设计等技术秘密可能通过合作被对方获取或泄露给第三方', 'high'),
('ctx_tech_005', 'preset_tech', 'typical_risks', '免责条款缺失', '技术服务不可避免存在bug和缺陷，需设置合理的免责条款和责任上限，避免无限责任', 'high'),
('ctx_tech_006', 'preset_tech', 'typical_risks', '无限修改义务', '验收标准不明确可能导致陷入无限修改循环，需明确验收标准和修改次数限制', 'medium'),
('ctx_tech_007', 'preset_tech', 'typical_risks', '竞业限制过宽', '技术人员竞业限制范围过宽可能影响正常业务开展', 'medium'),
('ctx_tech_008', 'preset_tech', 'compliance', '数据安全合规', '确保合同安排符合《数据安全法》《个人信息保护法》要求，明确数据处理权限和安全责任', 'high'),
('ctx_tech_009', 'preset_tech', 'compliance', '等保合规要求', '涉及重要系统时需满足等级保护要求，明确安全等级和合规责任', 'medium'),
('ctx_tech_010', 'preset_tech', 'business_practices', '里程碑付款', '通常按开发里程碑分期付款（如30%-40%-30%），验收合格后支付尾款', 'medium'),
('ctx_tech_011', 'preset_tech', 'business_practices', '质保期安排', '一般提供3-12个月质保期，质保期内免费修复缺陷', 'medium'),
('ctx_tech_012', 'preset_tech', 'negotiation_priorities', '验收标准明确', '必须明确可量化、可测试的验收标准，避免主观判断导致的争议', 'high'),
('ctx_tech_013', 'preset_tech', 'negotiation_priorities', '责任上限设定', '争取设定合理的责任上限（如合同金额的100%-150%），避免无限责任', 'high'),
('ctx_tech_014', 'preset_tech', 'negotiation_priorities', '知识产权保留', '对于通用组件、基础框架等，应保留我方知识产权，仅授权使用', 'high');

-- 2. 电商平台业务线
INSERT INTO business_lines (id, user_id, name, description, industry, is_preset, language)
VALUES (
    'preset_ecommerce',
    NULL,
    '电商平台业务线',
    '适用于电商平台运营、商家入驻、平台服务协议、营销推广等业务的合同审阅。重点关注消费者权益保护、平台责任边界、商家管理等方面。',
    '电商/零售',
    TRUE,
    'zh-CN'
);

INSERT INTO business_contexts (id, business_line_id, category, item, description, priority) VALUES
('ctx_ecom_001', 'preset_ecommerce', 'core_focus', '消费者权益保护', '确保合同条款符合《消费者权益保护法》要求，不含侵害消费者合法权益的格式条款', 'high'),
('ctx_ecom_002', 'preset_ecommerce', 'core_focus', '平台责任边界', '明确平台作为交易中介的责任范围，区分平台责任与商家责任，避免过度承担连带责任', 'high'),
('ctx_ecom_003', 'preset_ecommerce', 'core_focus', '商家准入与管理', '审查商家资质要求、违规处理机制、保证金制度，确保平台有效管控风险', 'high'),
('ctx_ecom_004', 'preset_ecommerce', 'typical_risks', '虚假宣传连带责任', '商家违规宣传（如虚假广告、误导性描述）可能导致平台承担连带责任', 'high'),
('ctx_ecom_005', 'preset_ecommerce', 'typical_risks', '假冒伪劣商品责任', '平台对假冒伪劣商品的审核义务和连带赔偿责任', 'high'),
('ctx_ecom_006', 'preset_ecommerce', 'typical_risks', '用户数据泄露', '大量用户个人信息和交易数据面临泄露风险，需明确数据安全责任', 'high'),
('ctx_ecom_007', 'preset_ecommerce', 'typical_risks', '价格欺诈投诉', '先涨后降、虚假折扣等价格欺诈行为的合规风险', 'medium'),
('ctx_ecom_008', 'preset_ecommerce', 'compliance', '电商法合规', '符合《电子商务法》关于平台经营者义务、消费者权益保护等规定', 'high'),
('ctx_ecom_009', 'preset_ecommerce', 'compliance', '广告法合规', '商品描述和营销内容符合《广告法》要求，避免绝对化用语等违规内容', 'high'),
('ctx_ecom_010', 'preset_ecommerce', 'compliance', '七天无理由退货', '确保符合七天无理由退货规定，明确例外情形', 'medium'),
('ctx_ecom_011', 'preset_ecommerce', 'business_practices', '保证金制度', '商家入驻通常需缴纳保证金，用于违规处罚和消费者赔付', 'medium'),
('ctx_ecom_012', 'preset_ecommerce', 'business_practices', '平台服务费', '通常按交易额收取一定比例的平台服务费（如3%-10%）', 'medium'),
('ctx_ecom_013', 'preset_ecommerce', 'negotiation_priorities', '免责条款有效性', '确保平台免责条款不因违反强制性规定而无效', 'high'),
('ctx_ecom_014', 'preset_ecommerce', 'negotiation_priorities', '争议解决机制', '建立有效的消费者投诉处理和争议解决机制', 'medium');

-- 3. 金融业务线
INSERT INTO business_lines (id, user_id, name, description, industry, is_preset, language)
VALUES (
    'preset_finance',
    NULL,
    '金融业务线',
    '适用于金融服务、投融资、信贷、支付结算等业务的合同审阅。重点关注资金安全、合规审批、担保措施、利率风险等方面。',
    '金融',
    TRUE,
    'zh-CN'
);

INSERT INTO business_contexts (id, business_line_id, category, item, description, priority) VALUES
('ctx_fin_001', 'preset_finance', 'core_focus', '资金安全保障', '确保资金流转路径清晰、账户管理规范，设置必要的资金监管措施', 'high'),
('ctx_fin_002', 'preset_finance', 'core_focus', '担保措施完备', '审查担保方式（抵押、质押、保证）的有效性、可执行性，确保债权得到充分保障', 'high'),
('ctx_fin_003', 'preset_finance', 'core_focus', '利率与费用合规', '确保利率、手续费等符合监管要求，避免被认定为高利贷或违规收费', 'high'),
('ctx_fin_004', 'preset_finance', 'typical_risks', '合规牌照风险', '相关金融业务是否需要牌照，是否存在无照经营风险', 'high'),
('ctx_fin_005', 'preset_finance', 'typical_risks', '资金挪用风险', '交易对手挪用资金或资金链断裂导致损失', 'high'),
('ctx_fin_006', 'preset_finance', 'typical_risks', '担保无效风险', '担保物权属不清、抵押登记不全导致担保无效', 'high'),
('ctx_fin_007', 'preset_finance', 'typical_risks', '关联交易风险', '关联方交易可能被认定为利益输送或逃废债', 'medium'),
('ctx_fin_008', 'preset_finance', 'compliance', '金融监管合规', '符合央行、银保监会、证监会等监管机构的相关规定', 'high'),
('ctx_fin_009', 'preset_finance', 'compliance', '反洗钱要求', '符合反洗钱法规要求，履行客户身份识别、交易记录保存等义务', 'high'),
('ctx_fin_010', 'preset_finance', 'compliance', '信息披露要求', '涉及公众投资者时需满足信息披露合规要求', 'medium'),
('ctx_fin_011', 'preset_finance', 'business_practices', '尽职调查', '重大交易前进行充分的尽职调查，了解交易对手资信状况', 'high'),
('ctx_fin_012', 'preset_finance', 'business_practices', '分期放款', '根据项目进度或条件成就情况分期放款，控制资金风险', 'medium'),
('ctx_fin_013', 'preset_finance', 'negotiation_priorities', '提前还款条款', '明确提前还款的条件、程序和违约金（如有）', 'medium'),
('ctx_fin_014', 'preset_finance', 'negotiation_priorities', '违约事件与救济', '详细约定违约事件定义和债权人的救济措施', 'high');

-- 4. 人力资源业务线
INSERT INTO business_lines (id, user_id, name, description, industry, is_preset, language)
VALUES (
    'preset_hr',
    NULL,
    '人力资源业务线',
    '适用于劳动合同、外包服务、猎头服务、培训服务等人力资源业务的合同审阅。重点关注劳动合规、竞业限制、社保公积金等方面。',
    '人力资源',
    TRUE,
    'zh-CN'
);

INSERT INTO business_contexts (id, business_line_id, category, item, description, priority) VALUES
('ctx_hr_001', 'preset_hr', 'core_focus', '劳动关系认定', '明确用工形式（劳动关系/劳务关系/外包），避免事实劳动关系认定风险', 'high'),
('ctx_hr_002', 'preset_hr', 'core_focus', '竞业限制合理性', '竞业限制的范围、期限、补偿金应合理，避免条款被认定无效', 'high'),
('ctx_hr_003', 'preset_hr', 'core_focus', '保密义务设定', '明确保密信息范围、保密期限、违约责任，保护商业秘密', 'high'),
('ctx_hr_004', 'preset_hr', 'typical_risks', '违法解除风险', '解除劳动合同程序不当或理由不充分导致违法解除赔偿', 'high'),
('ctx_hr_005', 'preset_hr', 'typical_risks', '社保公积金欠缴', '未依法缴纳社保公积金面临补缴和行政处罚风险', 'high'),
('ctx_hr_006', 'preset_hr', 'typical_risks', '加班费争议', '加班认定和加班费计算不规范导致劳动争议', 'medium'),
('ctx_hr_007', 'preset_hr', 'typical_risks', '工伤责任承担', '外包/派遣用工中工伤责任主体不明确', 'medium'),
('ctx_hr_008', 'preset_hr', 'compliance', '劳动法合规', '符合《劳动法》《劳动合同法》关于工时、休假、报酬等强制性规定', 'high'),
('ctx_hr_009', 'preset_hr', 'compliance', '劳务派遣合规', '劳务派遣需符合临时性、辅助性、替代性要求和比例限制', 'high'),
('ctx_hr_010', 'preset_hr', 'business_practices', '试用期约定', '试用期期限与劳动合同期限匹配，试用期工资不低于法定标准', 'medium'),
('ctx_hr_011', 'preset_hr', 'business_practices', '培训服务期', '专项培训可约定服务期，但违约金不得超过培训费用', 'medium'),
('ctx_hr_012', 'preset_hr', 'negotiation_priorities', '竞业补偿标准', '竞业限制补偿金应不低于离职前12个月平均工资的30%', 'high'),
('ctx_hr_013', 'preset_hr', 'negotiation_priorities', '解除条件明确', '明确可以解除劳动合同的具体情形，避免笼统约定', 'medium');

-- 5. 品牌营销业务线
INSERT INTO business_lines (id, user_id, name, description, industry, is_preset, language)
VALUES (
    'preset_marketing',
    NULL,
    '品牌营销业务线',
    '适用于广告投放、品牌合作、营销推广、代言合作等业务的合同审阅。重点关注品牌形象保护、广告合规、效果承诺等方面。',
    '广告/营销',
    TRUE,
    'zh-CN'
);

INSERT INTO business_contexts (id, business_line_id, category, item, description, priority) VALUES
('ctx_mkt_001', 'preset_marketing', 'core_focus', '品牌形象保护', '明确品牌使用规范、形象维护义务，防止品牌价值受损', 'high'),
('ctx_mkt_002', 'preset_marketing', 'core_focus', '内容审核权', '确保我方对营销内容有审核权和否决权，避免违规内容发布', 'high'),
('ctx_mkt_003', 'preset_marketing', 'core_focus', '知识产权授权', '明确商标、肖像、作品等知识产权的授权范围、期限和地域', 'high'),
('ctx_mkt_004', 'preset_marketing', 'typical_risks', '代言人负面事件', '代言人出现负面新闻或违法行为时的解约权和损失赔偿', 'high'),
('ctx_mkt_005', 'preset_marketing', 'typical_risks', '虚假宣传责任', '广告内容涉及虚假宣传被行政处罚或消费者索赔', 'high'),
('ctx_mkt_006', 'preset_marketing', 'typical_risks', '效果承诺纠纷', '营销效果未达预期引发的费用争议', 'medium'),
('ctx_mkt_007', 'preset_marketing', 'typical_risks', '竞品排他冲突', '排他条款过宽影响正常商业合作', 'medium'),
('ctx_mkt_008', 'preset_marketing', 'compliance', '广告法合规', '广告内容符合《广告法》规定，避免绝对化用语、虚假承诺等', 'high'),
('ctx_mkt_009', 'preset_marketing', 'compliance', '代言人资质', '代言人身份符合法规要求（如医疗广告不得使用代言人）', 'high'),
('ctx_mkt_010', 'preset_marketing', 'business_practices', 'KPI考核机制', '明确可量化的效果考核指标和结算方式', 'medium'),
('ctx_mkt_011', 'preset_marketing', 'business_practices', '素材交付标准', '明确创意素材的规格、数量、交付时间要求', 'medium'),
('ctx_mkt_012', 'preset_marketing', 'negotiation_priorities', '解约权设置', '设置因代言人负面事件或效果不达标的单方解约权', 'high'),
('ctx_mkt_013', 'preset_marketing', 'negotiation_priorities', '竞品排他范围', '竞品排他范围应明确具体，避免过于宽泛', 'medium');

-- =====================================================
-- 完成提示
-- =====================================================
-- 执行完成后，请验证：
-- 1. SELECT * FROM business_lines; -- 应有5条预设业务线
-- 2. SELECT COUNT(*) FROM business_contexts; -- 应有约65条背景信息
-- 3. SELECT * FROM tasks LIMIT 1; -- 确认 business_line_id 字段已添加
-- =====================================================
