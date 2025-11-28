-- 一次性创建集合并插入 29 条英文标准
-- 直接复制到 Supabase SQL Editor 执行即可

WITH new_collection AS (
  INSERT INTO standard_collections (id, name, description, material_type, language, is_preset, created_at, updated_at)
  VALUES (
    gen_random_uuid()::text,
    'General_Contract_Standards_EN',
    'General contract review standards covering party qualification, rights and obligations, payment terms, liability provisions, and more.',
    'contract',
    'en',
    true,
    NOW(),
    NOW()
  )
  RETURNING id
)
INSERT INTO review_standards (id, collection_id, category, item, description, risk_level, applicable_to, created_at, updated_at)
SELECT gen_random_uuid()::text, new_collection.id, v.category, v.item, v.description, v.risk_level, '["contract"]'::jsonb, NOW(), NOW()
FROM new_collection, (VALUES
  ('Party Qualification', 'Signatory Authority', 'Verify if the counterparty has valid business registration and operating licenses within their scope of business', 'high'),
  ('Party Qualification', 'Authorization to Sign', 'Check if the signatory has proper authorization with valid power of attorney or authorization documents', 'high'),
  ('Party Qualification', 'Performance Capability', 'Assess if the counterparty has sufficient financial resources and technical and personnel capabilities to perform', 'medium'),
  ('Rights and Obligations', 'Balance of Rights', 'Examine if rights and obligations are balanced between parties without obviously unfair terms', 'high'),
  ('Rights and Obligations', 'Core Rights Protection', 'Verify that our core rights are clearly defined and effectively protected', 'high'),
  ('Rights and Obligations', 'Obligation Scope Clarity', 'Check if our obligation scope is clearly defined avoiding ambiguous language', 'medium'),
  ('Rights and Obligations', 'Unilateral Amendment Clause', 'Check for clauses allowing counterparty to unilaterally modify the contract', 'high'),
  ('Payment Terms', 'Price and Payment Method', 'Verify price is clearly stated with payment method timing and conditions specified', 'medium'),
  ('Payment Terms', 'Price Adjustment Mechanism', 'Check for price adjustment clauses and whether adjustment conditions are reasonable', 'medium'),
  ('Payment Terms', 'Cost Allocation', 'Verify responsibility for various costs (taxes shipping etc) is clearly assigned', 'low'),
  ('Term Provisions', 'Contract Duration', 'Check if contract term is clearly specified with clear start and end dates', 'medium'),
  ('Term Provisions', 'Renewal Conditions', 'Check if renewal conditions are clear and whether automatic renewal risks exist', 'medium'),
  ('Term Provisions', 'Termination Conditions', 'Verify termination conditions are clear and we have reasonable exit mechanisms', 'high'),
  ('Term Provisions', 'Early Termination', 'Check if conditions procedures and consequences for early termination are specified', 'medium'),
  ('Liability Provisions', 'Breach of Contract', 'Verify breach liabilities are clear proportionate and penalties are reasonable', 'high'),
  ('Liability Provisions', 'Compensation Scope', 'Check if damage compensation scope is defined including indirect losses', 'medium'),
  ('Liability Provisions', 'Limitation of Liability', 'Check for liability caps and whether limits are reasonable', 'medium'),
  ('Liability Provisions', 'Exclusion Clauses', 'Review exclusion clauses for reasonableness and protection of our interests', 'high'),
  ('Dispute Resolution', 'Jurisdiction and Arbitration', 'Check if dispute resolution method favors us and venue selection is appropriate', 'medium'),
  ('Dispute Resolution', 'Governing Law', 'Verify governing law is specified and favorable to our position', 'medium'),
  ('Confidentiality', 'Scope of Confidential Information', 'Check if confidential information scope is clearly defined including necessary trade secrets', 'medium'),
  ('Confidentiality', 'Confidentiality Period', 'Check if confidentiality period is reasonable and aligns with contract term', 'low'),
  ('Intellectual Property', 'IP Ownership', 'Verify intellectual property ownership is clearly defined and our rights protected', 'high'),
  ('Intellectual Property', 'License Grant', 'Check if IP usage scope method and duration are clearly specified', 'medium'),
  ('Intellectual Property', 'Infringement Liability', 'Verify IP infringement liability is clearly addressed', 'medium'),
  ('Miscellaneous', 'Force Majeure', 'Check if force majeure clause is comprehensive with reasonable scope', 'low'),
  ('Miscellaneous', 'Notice and Service', 'Verify notice methods and addresses are clearly specified', 'low'),
  ('Miscellaneous', 'Contract Amendment', 'Check if conditions and procedures for contract amendment are specified', 'low')
) AS v(category, item, description, risk_level);
