# 法务文本审阅系统 (Contract Review)

使用 LLM 从法务角度审阅合同、营销材料等文本，按照审核标准找出风险点并提供处理建议。

## 功能特性

- **智能风险识别**：基于用户上传的审核标准自动识别文本中的法务风险点
- **修改建议**：针对每个风险点提供具体的文本修改建议（当前文本 → 建议文本）
- **行动建议**：除文本修改外还应采取的其他措施
- **在线编辑**：支持用户在线查看和修改审阅结果
- **多格式导出**：支持导出为 JSON、Excel、CSV 格式

## 技术栈

### 后端
- Python 3.10+
- FastAPI
- Pydantic
- DeepSeek LLM API

### 前端
- Vue 3
- Element Plus
- Pinia
- Vite

## 快速开始

### 1. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 配置 API Key

确保 `backend/config/deepseek_config.yaml` 中配置了正确的 DeepSeek API Key：

```yaml
llm:
  api_key: "your-api-key-here"
```

或通过环境变量设置：

```bash
export DEEPSEEK_API_KEY="your-api-key-here"
```

### 3. 启动后端服务

```bash
cd backend
python api_server.py
```

后端服务将在 http://localhost:8000 启动。

### 4. 安装前端依赖

```bash
cd frontend
npm install
```

### 5. 启动前端开发服务器

```bash
npm run dev
```

前端将在 http://localhost:3000 启动，并自动代理 API 请求到后端。

## 使用说明

### 1. 创建审阅任务

1. 在首页点击「新建审阅任务」
2. 填写任务名称和我方身份
3. 选择材料类型（合同/营销材料）

### 2. 上传文件

1. 上传待审阅的文档（支持 .md, .txt, .docx, .pdf）
2. 上传审核标准或选择默认模板

### 3. 开始审阅

点击「开始审阅」，系统将调用 LLM 进行三阶段审阅：
- 风险识别
- 修改建议生成
- 行动建议生成

### 4. 查看和编辑结果

- 在「风险点」页签查看所有识别出的风险
- 在「修改建议」页签查看和编辑修改建议
- 在「行动建议」页签确认需要采取的行动

### 5. 导出结果

支持导出为：
- Excel（单 Sheet 合并格式）
- CSV
- JSON
- Markdown 报告

## 审核标准格式

### 结构化表格格式（推荐）

Excel 或 CSV 文件，包含以下列：

| 列名 | 必填 | 说明 |
|-----|------|------|
| 审核分类 | 是 | 如：主体资格、权利义务、费用条款 |
| 审核要点 | 是 | 具体的审核检查项 |
| 详细说明 | 是 | 对审核要点的详细解释 |
| 风险等级 | 否 | 高/中/低，默认为"中" |
| 适用材料类型 | 否 | 合同/营销材料/全部 |

### 文本格式

也支持 Markdown 或 Word 格式的审核标准文档。

## 目录结构

```
contract_review/
├── backend/
│   ├── src/contract_review/    # 核心业务逻辑
│   │   ├── config.py           # 配置管理
│   │   ├── models.py           # 数据模型
│   │   ├── llm_client.py       # LLM 客户端
│   │   ├── document_loader.py  # 文档加载器
│   │   ├── standard_parser.py  # 审核标准解析器
│   │   ├── prompts.py          # Prompt 模板
│   │   ├── review_engine.py    # 审阅引擎
│   │   ├── result_formatter.py # 结果格式化器
│   │   ├── tasks.py            # 任务管理
│   │   └── storage.py          # 存储管理
│   ├── api_server.py           # FastAPI 服务
│   ├── config/                 # 配置文件
│   ├── templates/              # 默认审核标准模板
│   ├── tasks/                  # 任务数据存储
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/              # 页面组件
│   │   ├── components/         # 通用组件
│   │   ├── store/              # Pinia 状态管理
│   │   ├── api/                # API 封装
│   │   └── router/             # 路由配置
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## API 文档

启动后端服务后，访问 http://localhost:8000/docs 查看完整的 API 文档。

## 许可证

MIT License
