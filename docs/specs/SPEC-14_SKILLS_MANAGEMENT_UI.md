# SPEC-14: Skills 管理 API + 前端界面

## 1. 概述

当前系统缺少一个统一的 Skills 管理入口。管理员无法直观地查看：
- 系统中注册了哪些 Skills
- 每个 Skill 属于哪个领域（通用 / FIDIC / SPA 等）
- 每个 Skill 的执行后端（本地 / Refly）
- 每个 Skill 的类别（提取 / 对比 / 校验）

本 SPEC 实现：
1. 后端 Skills 管理 API 端点
2. 前端 Skills 管理页面
3. 为将来的场景拓展提供可视化基础

**前置依赖：** SPEC-12 和 SPEC-13 必须先完成。

## 2. 文件清单

### 新增文件（共 3 个）

| 文件路径 | 用途 |
|---------|------|
| `frontend/src/views/SkillsView.vue` | Skills 管理页面 |
| `frontend/src/api/skills.js` | Skills API 调用层 |
| `tests/test_skills_api.py` | Skills API 端点测试 |

### 修改文件（共 3 个）

| 文件路径 | 改动内容 |
|---------|---------|
| `backend/src/contract_review/api_gen3.py` | 新增 `/skills` 和 `/skills/{skill_id}` 端点 |
| `frontend/src/router/index.js` | 新增 `/skills` 路由 |
| `frontend/src/views/HomeView.vue` | 首页增加 Skills 管理入口链接 |

## 3. 后端 API 设计

### 3.1 端点列表

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/v3/skills` | 获取所有已注册 Skills 列表 |
| GET | `/api/v3/skills/{skill_id}` | 获取单个 Skill 详情 |
| GET | `/api/v3/skills/by-domain/{domain_id}` | 获取指定领域的 Skills |

### 3.2 响应格式

**GET `/api/v3/skills`**

```json
{
  "skills": [
    {
      "skill_id": "get_clause_context",
      "name": "获取条款上下文",
      "description": "从文档结构中提取指定条款文本",
      "backend": "local",
      "domain": "*",
      "category": "extraction",
      "is_registered": true
    },
    {
      "skill_id": "fidic_search_er",
      "name": "ER 语义检索",
      "description": "在业主方要求中做语义检索",
      "backend": "refly",
      "domain": "fidic",
      "category": "general",
      "is_registered": false
    }
  ],
  "total": 8,
  "by_domain": {
    "*": 5,
    "fidic": 3
  },
  "by_backend": {
    "local": 7,
    "refly": 1
  }
}
```

**GET `/api/v3/skills/{skill_id}`**

```json
{
  "skill_id": "get_clause_context",
  "name": "获取条款上下文",
  "description": "从文档结构中提取指定条款文本",
  "backend": "local",
  "domain": "*",
  "category": "extraction",
  "is_registered": true,
  "local_handler": "contract_review.skills.local.clause_context.get_clause_context",
  "refly_workflow_id": null,
  "used_by_checklist_items": ["1.1", "1.5", "4.1", "4.12", "8.2", "14.1", "14.2", "14.7", "17.6", "18.1", "20.1", "20.2"]
}
```

### 3.3 后端实现

**文件：** `api_gen3.py`

在现有 router 中新增端点：

```python
from .plugins.registry import list_domain_plugins, get_all_skills_for_domain

@router.get("/skills")
async def list_skills(domain_id: str | None = None):
    """获取所有已注册 Skills 列表。"""
    # 收集通用 Skills
    from .graph.builder import _GENERIC_SKILLS
    all_skills = list(_GENERIC_SKILLS)

    # 收集所有领域 Skills
    for plugin in list_domain_plugins():
        all_skills.extend(plugin.domain_skills)

    # 按 domain 过滤
    if domain_id:
        all_skills = [s for s in all_skills if s.domain in (domain_id, "*")]

    # 尝试创建 dispatcher 检查注册状态
    registered_ids = set()
    try:
        from .graph.builder import _create_dispatcher
        dispatcher = _create_dispatcher(domain_id=domain_id)
        if dispatcher:
            registered_ids = set(dispatcher.skill_ids)
    except Exception:
        pass

    # 构造响应
    skills_list = []
    by_domain = {}
    by_backend = {}
    for skill in all_skills:
        domain = getattr(skill, "domain", "*")
        category = getattr(skill, "category", "general")
        backend = skill.backend.value
        skills_list.append({
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "backend": backend,
            "domain": domain,
            "category": category,
            "is_registered": skill.skill_id in registered_ids,
        })
        by_domain[domain] = by_domain.get(domain, 0) + 1
        by_backend[backend] = by_backend.get(backend, 0) + 1

    return {
        "skills": skills_list,
        "total": len(skills_list),
        "by_domain": by_domain,
        "by_backend": by_backend,
    }


@router.get("/skills/{skill_id}")
async def get_skill_detail(skill_id: str):
    """获取单个 Skill 详情。"""
    from .graph.builder import _GENERIC_SKILLS

    # 在通用 Skills 中查找
    target = None
    for skill in _GENERIC_SKILLS:
        if skill.skill_id == skill_id:
            target = skill
            break

    # 在领域 Skills 中查找
    if not target:
        for plugin in list_domain_plugins():
            for skill in plugin.domain_skills:
                if skill.skill_id == skill_id:
                    target = skill
                    break
            if target:
                break

    if not target:
        raise HTTPException(404, f"Skill '{skill_id}' 未找到")

    # 查找哪些 checklist 条目引用了此 Skill
    used_by = []
    for plugin in list_domain_plugins():
        for item in plugin.review_checklist:
            if skill_id in item.required_skills:
                used_by.append(item.clause_id)

    return {
        "skill_id": target.skill_id,
        "name": target.name,
        "description": target.description,
        "backend": target.backend.value,
        "domain": getattr(target, "domain", "*"),
        "category": getattr(target, "category", "general"),
        "is_registered": True,
        "local_handler": target.local_handler,
        "refly_workflow_id": target.refly_workflow_id,
        "used_by_checklist_items": used_by,
    }


@router.get("/skills/by-domain/{domain_id}")
async def get_skills_by_domain(domain_id: str):
    """获取指定领域的 Skills（含通用 Skills）。"""
    from .graph.builder import _GENERIC_SKILLS
    all_skills = get_all_skills_for_domain(domain_id, generic_skills=_GENERIC_SKILLS)

    return {
        "domain_id": domain_id,
        "skills": [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "backend": s.backend.value,
                "domain": getattr(s, "domain", "*"),
                "category": getattr(s, "category", "general"),
            }
            for s in all_skills
        ],
        "total": len(all_skills),
    }
```

**注意：** `/skills/by-domain/{domain_id}` 路由必须在 `/skills/{skill_id}` 之前注册，否则 `by-domain` 会被当作 `skill_id` 匹配。

## 4. 前端设计

### 4.1 API 调用层

**文件：** `frontend/src/api/skills.js`

```javascript
import axios from 'axios'

const API_BASE_URL = import.meta.env.PROD
  ? 'https://contract-review-z9te.onrender.com/api/v3'
  : '/api/v3'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

export async function fetchSkills(domainId = null) {
  const params = domainId ? { domain_id: domainId } : {}
  const resp = await api.get('/skills', { params })
  return resp.data
}

export async function fetchSkillDetail(skillId) {
  const resp = await api.get(`/skills/${skillId}`)
  return resp.data
}

export async function fetchSkillsByDomain(domainId) {
  const resp = await api.get(`/skills/by-domain/${domainId}`)
  return resp.data
}
```

### 4.2 Skills 管理页面

**文件：** `frontend/src/views/SkillsView.vue`

页面布局：
- 顶部：标题 + 统计摘要（总数、按来源分布、按类别分布）
- 筛选栏：按领域筛选（全部 / 通用 / FIDIC / ...）、按来源筛选（全部 / 本地 / Refly）
- 主体：Skills 卡片列表，每张卡片显示：
  - Skill 名称
  - 描述
  - 标签：领域（通用/FIDIC）、来源（本地/Refly）、类别（提取/对比/校验）
  - 注册状态指示器（绿色已注册 / 灰色未注册）
  - 点击展开详情：handler 路径、引用此 Skill 的 checklist 条目

```vue
<template>
  <div class="skills-view">
    <div class="page-header">
      <h2>Skills 管理</h2>
      <div class="stats" v-if="data">
        <span class="stat-item">共 {{ data.total }} 个 Skills</span>
        <span class="stat-item" v-for="(count, backend) in data.by_backend" :key="backend">
          {{ backendLabel(backend) }}: {{ count }}
        </span>
      </div>
    </div>

    <div class="filter-bar">
      <select v-model="filterDomain">
        <option value="">全部领域</option>
        <option value="*">通用</option>
        <option v-for="d in domains" :key="d.domain_id" :value="d.domain_id">
          {{ d.name }}
        </option>
      </select>
      <select v-model="filterBackend">
        <option value="">全部来源</option>
        <option value="local">本地</option>
        <option value="refly">Refly</option>
      </select>
    </div>

    <div class="skills-grid">
      <div
        v-for="skill in filteredSkills"
        :key="skill.skill_id"
        class="skill-card"
        :class="{ 'not-registered': !skill.is_registered }"
        @click="toggleDetail(skill.skill_id)"
      >
        <div class="skill-header">
          <span class="skill-name">{{ skill.name }}</span>
          <span class="status-dot" :class="skill.is_registered ? 'active' : 'inactive'" />
        </div>
        <p class="skill-desc">{{ skill.description }}</p>
        <div class="skill-tags">
          <span class="tag domain">{{ domainLabel(skill.domain) }}</span>
          <span class="tag backend">{{ backendLabel(skill.backend) }}</span>
          <span class="tag category">{{ categoryLabel(skill.category) }}</span>
        </div>

        <div v-if="expandedSkill === skill.skill_id && skillDetail" class="skill-detail">
          <div v-if="skillDetail.local_handler">
            <strong>Handler:</strong> {{ skillDetail.local_handler }}
          </div>
          <div v-if="skillDetail.refly_workflow_id">
            <strong>Workflow:</strong> {{ skillDetail.refly_workflow_id }}
          </div>
          <div v-if="skillDetail.used_by_checklist_items?.length">
            <strong>被引用条款:</strong> {{ skillDetail.used_by_checklist_items.join(', ') }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
```

**Script 部分核心逻辑：**

```javascript
import { ref, computed, onMounted } from 'vue'
import { fetchSkills, fetchSkillDetail } from '@/api/skills'

// 响应式状态
const data = ref(null)
const domains = ref([])
const filterDomain = ref('')
const filterBackend = ref('')
const expandedSkill = ref(null)
const skillDetail = ref(null)

// 计算属性：筛选后的 Skills
const filteredSkills = computed(() => {
  if (!data.value) return []
  return data.value.skills.filter(s => {
    if (filterDomain.value && s.domain !== filterDomain.value) return false
    if (filterBackend.value && s.backend !== filterBackend.value) return false
    return true
  })
})

// 标签映射
function domainLabel(domain) {
  if (domain === '*') return '通用'
  return domain.toUpperCase()
}
function backendLabel(backend) {
  return backend === 'local' ? '本地' : 'Refly'
}
function categoryLabel(category) {
  const map = { extraction: '提取', comparison: '对比', validation: '校验', general: '通用' }
  return map[category] || category
}

// 展开详情
async function toggleDetail(skillId) {
  if (expandedSkill.value === skillId) {
    expandedSkill.value = null
    skillDetail.value = null
    return
  }
  expandedSkill.value = skillId
  try {
    skillDetail.value = await fetchSkillDetail(skillId)
  } catch {
    skillDetail.value = null
  }
}
```

**样式要点：**
- 使用 CSS Grid 布局，每行 2-3 张卡片
- 卡片有轻微阴影和圆角，与现有 Gen3 组件风格一致
- 未注册的 Skill 卡片使用半透明样式
- 标签使用不同颜色区分：领域（蓝色）、来源（绿色/紫色）、类别（橙色）

### 4.3 路由注册

**文件：** `frontend/src/router/index.js`

在 routes 数组中新增：

```javascript
{
  path: '/skills',
  name: 'Skills',
  component: lazyLoadView(() => import('@/views/SkillsView.vue'), 'SkillsView'),
  meta: { title: 'Skills 管理' }
},
```

### 4.4 首页入口

**文件：** `frontend/src/views/HomeView.vue`

在现有导航区域中增加一个入口链接，指向 `/skills`，标题为"Skills 管理"，描述为"查看和管理审阅技能"。具体位置参照现有的导航卡片风格。

## 5. 测试

### 5.1 测试文件：`tests/test_skills_api.py`

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytest.importorskip("langgraph")


@pytest.fixture
def app():
    from fastapi import FastAPI
    from contract_review.api_gen3 import router
    from contract_review.plugins.fidic import register_fidic_plugin
    from contract_review.plugins.registry import clear_plugins

    test_app = FastAPI()
    test_app.include_router(router)
    clear_plugins()
    register_fidic_plugin()
    return test_app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_skills(client):
    resp = await client.get("/api/v3/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert "skills" in data
    assert "total" in data
    assert data["total"] >= 1  # 至少有 get_clause_context
    assert "by_domain" in data
    assert "by_backend" in data


@pytest.mark.asyncio
async def test_list_skills_filter_by_domain(client):
    resp = await client.get("/api/v3/skills", params={"domain_id": "fidic"})
    assert resp.status_code == 200
    data = resp.json()
    # 应包含通用 Skills（domain="*"）和 FIDIC Skills
    domains = {s["domain"] for s in data["skills"]}
    assert "*" in domains or "fidic" in domains


@pytest.mark.asyncio
async def test_get_skill_detail(client):
    resp = await client.get("/api/v3/skills/get_clause_context")
    assert resp.status_code == 200
    data = resp.json()
    assert data["skill_id"] == "get_clause_context"
    assert data["backend"] == "local"
    assert "used_by_checklist_items" in data
    assert isinstance(data["used_by_checklist_items"], list)


@pytest.mark.asyncio
async def test_get_skill_detail_not_found(client):
    resp = await client.get("/api/v3/skills/nonexistent_skill")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_skills_by_domain(client):
    resp = await client.get("/api/v3/skills/by-domain/fidic")
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain_id"] == "fidic"
    assert data["total"] >= 1
    assert isinstance(data["skills"], list)


@pytest.mark.asyncio
async def test_get_skills_by_unknown_domain(client):
    resp = await client.get("/api/v3/skills/by-domain/unknown")
    assert resp.status_code == 200
    data = resp.json()
    # 未知领域应至少返回通用 Skills
    assert data["total"] >= 0
```

## 6. 约束

1. 不修改已有测试用例
2. 不修改 `redline_generator.py`
3. Skills API 为只读端点，不支持通过 API 创建/删除 Skills
4. 前端页面风格与现有 Gen3 组件保持一致
5. `/skills/by-domain/{domain_id}` 路由必须在 `/skills/{skill_id}` 之前注册
6. 运行 `PYTHONPATH=backend/src python -m pytest tests/ -x -q` 确认全部通过

## 7. 验收标准

1. `GET /api/v3/skills` 返回所有 Skills 列表，含统计信息
2. `GET /api/v3/skills/{skill_id}` 返回 Skill 详情，含 `used_by_checklist_items`
3. `GET /api/v3/skills/by-domain/{domain_id}` 返回指定领域 Skills
4. 前端 `/skills` 页面可正常访问，展示 Skills 卡片列表
5. 筛选功能正常工作（按领域、按来源）
6. 点击卡片可展开详情
7. 所有测试通过
