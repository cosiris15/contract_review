"""
FastAPI 服务入口

提供法务文本审阅系统的 RESTful API。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

# 加载 .env 文件（本地开发用）
from dotenv import load_dotenv
load_dotenv()
from typing import List, Optional

import httpx
import jwt
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.contract_review.config import get_settings, load_settings
from src.contract_review.document_loader import load_document, load_document_async
from src.contract_review.ocr_service import OCRService, init_ocr_service, get_ocr_service
from src.contract_review.models import (
    MaterialType,
    ModificationSuggestion,
    ReviewResult,
    ReviewStandard,
    ReviewTask,
    StandardRecommendation,
)
from src.contract_review.result_formatter import ResultFormatter, generate_summary_report
from src.contract_review.review_engine import ReviewEngine
from src.contract_review.standard_library import StandardLibraryManager
from src.contract_review.business_library import BusinessLibraryManager
from src.contract_review.redline_generator import generate_redline_document
from src.contract_review.standard_parser import parse_standard_file
from src.contract_review.storage import StorageManager
from src.contract_review.tasks import TaskManager
from src.contract_review.supabase_tasks import SupabaseTaskManager
from src.contract_review.supabase_storage import SupabaseStorageManager
from src.contract_review.supabase_business import SupabaseBusinessManager
from src.contract_review.supabase_standards import SupabaseStandardLibraryManager
from src.contract_review.prompts import (
    build_usage_instruction_messages,
    build_standard_recommendation_messages,
    build_standard_modification_messages,
    build_merge_special_requirements_messages,
    build_collection_recommendation_messages,
    build_collection_usage_instruction_messages,
)
from src.contract_review.llm_client import LLMClient
from src.contract_review.fallback_llm import FallbackLLMClient, create_fallback_client
from src.contract_review.quota_service import get_quota_service, QuotaInfo
from src.contract_review.interactive_engine import InteractiveReviewEngine
from src.contract_review.supabase_interactive import get_interactive_manager, InteractiveChat, ChatMessage
from src.contract_review.document_preprocessor import DocumentPreprocessor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 加载配置
settings = load_settings()

# 创建 FastAPI 应用
app = FastAPI(
    title="法务文本审阅系统 API",
    description="使用 LLM 从法务角度审阅合同、营销材料等文本",
    version="1.0.0",
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],  # 允许前端访问自定义响应头
)


# 全局异常处理器 - 确保异常响应也包含 CORS 头
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"未捕获的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误: {str(exc)}"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


# 初始化管理器
# 检查是否配置了 Contract 业务数据库，如果是则使用 Supabase 版本
USE_SUPABASE = bool(os.getenv("CONTRACT_DB_URL") and os.getenv("CONTRACT_DB_KEY"))

if USE_SUPABASE:
    logger.info("使用 Supabase 存储后端")
    task_manager = SupabaseTaskManager()
    storage_manager = SupabaseStorageManager()
else:
    logger.info("使用本地文件存储后端")
    task_manager = TaskManager(settings.review.tasks_dir)
    storage_manager = StorageManager(settings.review.tasks_dir)

formatter = ResultFormatter()

# 标准库目录（本地文件存储备选方案）
STANDARD_LIBRARY_DIR = Path(settings.review.tasks_dir).parent / "data" / "standard_library"

# 标准库管理器和业务条线管理器（根据存储后端选择）
if USE_SUPABASE:
    standard_library_manager = SupabaseStandardLibraryManager()
    business_library_manager = SupabaseBusinessManager()
    logger.info("标准库使用 Supabase 存储后端")
else:
    standard_library_manager = StandardLibraryManager(STANDARD_LIBRARY_DIR)
    BUSINESS_LIBRARY_DIR = Path(settings.review.tasks_dir).parent / "data" / "business_library"
    business_library_manager = BusinessLibraryManager(BUSINESS_LIBRARY_DIR)
    logger.info("标准库使用本地文件存储后端")

# LLM 客户端（带 fallback 机制）
# 默认使用 DeepSeek，失败时自动切换到 Gemini
llm_client = create_fallback_client(settings, primary_provider="deepseek")

# OCR 服务初始化（用于图片和扫描 PDF 识别）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
QWEN_OCR_MODEL = os.getenv("QWEN_OCR_MODEL", "qwen-vl-ocr-2025-11-20")

if DASHSCOPE_API_KEY:
    logger.info("OCR 服务已配置（阿里云 DashScope）")
    init_ocr_service(api_key=DASHSCOPE_API_KEY, model=QWEN_OCR_MODEL)
else:
    logger.warning("OCR 服务未配置（DASHSCOPE_API_KEY 未设置），图片和扫描 PDF 将无法处理")

# 默认模板目录
TEMPLATES_DIR = settings.review.templates_dir

# ==================== Clerk 身份验证 ====================

# 从环境变量加载 Clerk 配置
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
# Clerk JWKS URL（用于验证 JWT）
CLERK_JWKS_URL = None

# HTTP Bearer 认证
security = HTTPBearer(auto_error=False)

# 缓存 JWKS
_jwks_cache = None
_jwks_cache_time = 0
JWKS_CACHE_DURATION = 3600  # 1小时


async def get_clerk_jwks():
    """获取 Clerk 的 JWKS（JSON Web Key Set）用于验证 JWT"""
    global _jwks_cache, _jwks_cache_time, CLERK_JWKS_URL

    import time
    current_time = time.time()

    # 如果缓存有效，直接返回
    if _jwks_cache and (current_time - _jwks_cache_time) < JWKS_CACHE_DURATION:
        return _jwks_cache

    # 从 CLERK_SECRET_KEY 推断 JWKS URL
    # Clerk 的 publishable key 格式: pk_test_xxx 或 pk_live_xxx
    # 对应的 JWKS URL: https://{frontend_api}/.well-known/jwks.json
    if not CLERK_JWKS_URL:
        # 尝试从环境变量获取 frontend API
        clerk_frontend_api = os.getenv("CLERK_FRONTEND_API", "")
        if clerk_frontend_api:
            CLERK_JWKS_URL = f"https://{clerk_frontend_api}/.well-known/jwks.json"
        else:
            # 从 publishable key 中提取（base64 解码）
            publishable_key = os.getenv("CLERK_PUBLISHABLE_KEY", os.getenv("VITE_CLERK_PUBLISHABLE_KEY", ""))
            if publishable_key and publishable_key.startswith("pk_"):
                try:
                    import base64
                    # pk_test_xxx 格式，xxx 是 base64 编码的 frontend API
                    encoded_part = publishable_key.split("_")[-1]
                    # 添加 padding
                    padding = 4 - len(encoded_part) % 4
                    if padding != 4:
                        encoded_part += "=" * padding
                    frontend_api = base64.b64decode(encoded_part).decode("utf-8").rstrip("$")
                    CLERK_JWKS_URL = f"https://{frontend_api}/.well-known/jwks.json"
                except Exception as e:
                    logger.warning(f"无法从 publishable key 解析 JWKS URL: {e}")

    if not CLERK_JWKS_URL:
        raise HTTPException(status_code=500, detail="Clerk JWKS URL 未配置")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(CLERK_JWKS_URL, timeout=10.0)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = current_time
            return _jwks_cache
    except Exception as e:
        logger.error(f"获取 Clerk JWKS 失败: {e}")
        raise HTTPException(status_code=500, detail="无法验证身份凭证")


def get_signing_key(jwks: dict, kid: str):
    """从 JWKS 中获取签名密钥"""
    from jwt import algorithms

    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return algorithms.RSAAlgorithm.from_jwk(key)

    raise HTTPException(status_code=401, detail="无法找到匹配的签名密钥")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    验证 Clerk JWT Token 并返回用户 ID

    从请求头 Authorization: Bearer <token> 中提取并验证 Token。
    成功返回 user_id，失败抛出 401 异常。
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # 先解码 header 获取 kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise HTTPException(status_code=401, detail="Invalid token header")

        # 获取 JWKS 并找到对应的公钥
        jwks = await get_clerk_jwks()
        signing_key = get_signing_key(jwks, kid)

        # 验证并解码 token
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            options={
                "verify_aud": False,  # Clerk 不使用 audience
                "verify_iss": False,  # issuer 验证可选
            },
        )

        # 获取用户 ID（Clerk 使用 sub 字段）
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: missing user ID")

        return user_id

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token 验证失败: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"身份验证异常: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")

# 启动时将预设模板导入标准库（如果尚未导入）
try:
    imported_count = standard_library_manager.import_preset_templates(TEMPLATES_DIR)
    if imported_count > 0:
        logger.info(f"已将 {imported_count} 个预设模板导入标准库")
except Exception as e:
    logger.warning(f"导入预设模板失败: {e}")

# 启动时迁移无归属的风险点
try:
    migrated_count = standard_library_manager.migrate_orphan_standards()
    if migrated_count > 0:
        logger.info(f"已迁移 {migrated_count} 条无归属风险点到默认集合")
except Exception as e:
    logger.warning(f"迁移无归属风险点失败: {e}")


# ==================== 请求/响应模型 ====================

class CreateTaskRequest(BaseModel):
    name: str
    our_party: str
    material_type: MaterialType = "contract"
    language: str = "zh-CN"  # 审阅语言: "zh-CN" 或 "en"


class TaskResponse(BaseModel):
    id: str
    name: str
    our_party: str
    material_type: str
    language: str = "zh-CN"
    status: str
    message: Optional[str] = None
    document_filename: Optional[str] = None
    standard_filename: Optional[str] = None
    created_at: str
    updated_at: str

    @classmethod
    def from_task(cls, task: ReviewTask) -> "TaskResponse":
        return cls(
            id=task.id,
            name=task.name,
            our_party=task.our_party,
            material_type=task.material_type,
            language=getattr(task, 'language', 'zh-CN'),
            status=task.status,
            message=task.message,
            document_filename=task.document_filename,
            standard_filename=task.standard_filename,
            created_at=task.created_at.isoformat(),
            updated_at=task.updated_at.isoformat(),
        )


class TaskStatusResponse(BaseModel):
    status: str
    message: Optional[str] = None
    progress: dict


class UpdateModificationRequest(BaseModel):
    user_confirmed: Optional[bool] = None
    user_modified_text: Optional[str] = None


class UpdateActionRequest(BaseModel):
    user_confirmed: Optional[bool] = None
    description: Optional[str] = None
    action_type: Optional[str] = None
    urgency: Optional[str] = None
    responsible_party: Optional[str] = None
    deadline_suggestion: Optional[str] = None


# ---------- 标准制作相关模型 ----------

class StandardCreationRequest(BaseModel):
    """标准制作请求"""
    document_type: str  # "contract" | "marketing" | "both"
    business_scenario: str  # 业务场景描述
    focus_areas: List[str]  # 核心关注点列表
    our_role: Optional[str] = None  # 我方角色
    industry: Optional[str] = None  # 行业领域
    special_risks: Optional[str] = None  # 特殊风险提示
    reference_material: Optional[str] = None  # 参考材料文本
    language: str = "zh-CN"  # 语言: "zh-CN" 或 "en"


class GeneratedStandard(BaseModel):
    """生成的标准"""
    category: str
    item: str
    description: str
    risk_level: str
    applicable_to: List[str]
    usage_instruction: str


class StandardCreationResponse(BaseModel):
    """标准制作响应"""
    collection_name: str  # AI生成的集合名称
    standards: List[GeneratedStandard]
    generation_summary: str


class TemplateInfo(BaseModel):
    name: str
    filename: str
    description: str


# ---------- 标准库相关模型 ----------

class StandardResponse(BaseModel):
    """标准响应"""
    id: str
    category: str
    item: str
    description: str
    risk_level: str
    applicable_to: List[str]
    usage_instruction: Optional[str] = None
    tags: List[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CreateStandardRequest(BaseModel):
    """创建标准请求"""
    category: str
    item: str
    description: str
    risk_level: str = "medium"
    applicable_to: List[str] = ["contract", "marketing"]
    usage_instruction: Optional[str] = None
    tags: List[str] = []


class UpdateStandardRequest(BaseModel):
    """更新标准请求"""
    category: Optional[str] = None
    item: Optional[str] = None
    description: Optional[str] = None
    risk_level: Optional[str] = None
    applicable_to: Optional[List[str]] = None
    usage_instruction: Optional[str] = None
    tags: Optional[List[str]] = None


class BatchCreateStandardsRequest(BaseModel):
    """批量创建标准请求"""
    standards: List[CreateStandardRequest]


class StandardPreviewResponse(BaseModel):
    """标准预览响应"""
    standards: List[StandardResponse]
    total_count: int
    parse_warnings: List[str] = []


class SaveToLibraryRequest(BaseModel):
    """保存到标准库请求"""
    collection_name: str  # 集合名称（必填）
    collection_description: str = ""  # 集合描述
    material_type: str = "both"  # 材料类型
    language: str = "zh-CN"  # 语言 ("zh-CN" 或 "en")
    standards: List[CreateStandardRequest]


class StandardLibraryStatsResponse(BaseModel):
    """标准库统计信息"""
    total: int
    by_category: dict
    by_risk_level: dict
    by_material_type: dict
    updated_at: Optional[str] = None


class GenerateUsageInstructionRequest(BaseModel):
    """生成适用说明请求"""
    standard_ids: List[str]
    sample_document_text: Optional[str] = None


class UsageInstructionResult(BaseModel):
    """适用说明生成结果"""
    standard_id: str
    usage_instruction: str


class RecommendStandardsRequest(BaseModel):
    """推荐标准请求"""
    document_text: str
    material_type: str = "contract"


class StandardRecommendationResponse(BaseModel):
    """标准推荐响应"""
    standard_id: str
    relevance_score: float
    match_reason: str
    standard: StandardResponse


# ---------- 标准集合推荐模型 ----------

class RecommendCollectionsRequest(BaseModel):
    """推荐标准集合请求"""
    document_text: str  # 文档内容（前1000字）
    material_type: str = "contract"


class CollectionRecommendationItem(BaseModel):
    """集合推荐项"""
    collection_id: str
    collection_name: str
    relevance_score: float  # 0-1
    match_reason: str
    standard_count: int
    usage_instruction: Optional[str] = None


# ==================== 任务管理 API ====================

@app.post("/api/tasks", response_model=TaskResponse)
async def create_task(
    request: CreateTaskRequest,
    user_id: str = Depends(get_current_user),
):
    """创建审阅任务（需要登录）"""
    print(f"User {user_id} is creating a new task...")
    if USE_SUPABASE:
        task = task_manager.create_task(
            name=request.name,
            our_party=request.our_party,
            user_id=user_id,
            material_type=request.material_type,
            language=request.language,
        )
    else:
        task = task_manager.create_task(
            name=request.name,
            our_party=request.our_party,
            material_type=request.material_type,
            language=request.language,
        )
    logger.info(f"创建任务: {task.id} - {task.name} (language={request.language}) by user {user_id}")
    return TaskResponse.from_task(task)


@app.get("/api/tasks", response_model=List[TaskResponse])
async def list_tasks(
    limit: int = Query(default=100, ge=1, le=500),
    user_id: str = Depends(get_current_user),
):
    """获取任务列表（需要登录，只返回当前用户的任务）"""
    if USE_SUPABASE:
        tasks = task_manager.list_tasks(user_id=user_id, limit=limit)
    else:
        tasks = task_manager.list_tasks(limit=limit)
    return [TaskResponse.from_task(t) for t in tasks]


@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """获取任务详情"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskResponse.from_task(task)


@app.delete("/api/tasks/{task_id}")
async def delete_task(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """删除任务（需要登录）"""
    if USE_SUPABASE:
        success = task_manager.delete_task(task_id, user_id)
    else:
        success = task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"message": "删除成功"}


class TaskUpdateRequest(BaseModel):
    name: Optional[str] = None
    our_party: Optional[str] = None
    material_type: Optional[str] = None
    language: Optional[str] = None


@app.patch("/api/tasks/{task_id}")
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    user_id: str = Depends(get_current_user),
):
    """更新任务基本信息（需要登录）"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证用户权限
    if USE_SUPABASE:
        task_owner = task_manager.get_task_user_id(task_id)
        if task_owner != user_id:
            raise HTTPException(status_code=403, detail="无权访问此任务")

    # 构建更新数据
    update_data = {}
    if request.name is not None:
        update_data["name"] = request.name
    if request.our_party is not None:
        update_data["our_party"] = request.our_party
    if request.material_type is not None:
        update_data["material_type"] = request.material_type
    if request.language is not None:
        update_data["language"] = request.language

    if not update_data:
        return TaskResponse.from_task(task)

    # 更新任务
    if USE_SUPABASE:
        updated_task = task_manager.update_task(task_id, update_data)
    else:
        # 本地模式：直接更新内存中的任务
        for key, value in update_data.items():
            setattr(task, key, value)
        updated_task = task

    if not updated_task:
        raise HTTPException(status_code=500, detail="更新失败")

    return TaskResponse.from_task(updated_task)


@app.get("/api/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """获取任务状态和进度"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return TaskStatusResponse(
        status=task.status,
        message=task.message,
        progress={
            "stage": task.progress.stage,
            "percentage": task.progress.percentage,
            "message": task.progress.message,
        },
    )


# ==================== 文件上传 API ====================

# 文件大小限制（MB）
MAX_DOCUMENT_SIZE_MB = 10  # 待审阅文档最大 10MB
MAX_STANDARD_SIZE_MB = 5   # 审核标准最大 5MB


@app.post("/api/tasks/{task_id}/document")
async def upload_document(
    task_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """上传待审阅文档（需要登录）"""
    print(f"User {user_id} is uploading document to task {task_id}...")
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查文件类型
    suffix = Path(file.filename).suffix.lower()
    allowed = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".docx", ".xlsx", ".md", ".txt"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。支持的格式: PDF、图片、Word、Excel、Markdown",
        )

    content = await file.read()

    # 检查文件大小
    file_size_mb = len(content) / (1024 * 1024)
    if file_size_mb > MAX_DOCUMENT_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（{file_size_mb:.1f}MB）。待审阅文档最大支持 {MAX_DOCUMENT_SIZE_MB}MB",
        )
    if USE_SUPABASE:
        task_manager.save_document(task_id, user_id, file.filename, content)
    else:
        task_manager.save_document(task_id, file.filename, content)

    logger.info(f"任务 {task_id} 上传文档: {file.filename}")
    return {"message": "上传成功", "filename": file.filename}


@app.post("/api/tasks/{task_id}/standard")
async def upload_standard(
    task_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """上传审核标准（需要登录）"""
    print(f"User {user_id} is uploading standard to task {task_id}...")
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查文件类型
    suffix = Path(file.filename).suffix.lower()
    allowed = {".xlsx", ".xls", ".csv", ".docx", ".md", ".txt"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。支持的格式: {', '.join(allowed)}",
        )

    content = await file.read()

    # 检查文件大小
    file_size_mb = len(content) / (1024 * 1024)
    if file_size_mb > MAX_STANDARD_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（{file_size_mb:.1f}MB）。审核标准文件最大支持 {MAX_STANDARD_SIZE_MB}MB",
        )

    if USE_SUPABASE:
        task_manager.save_standard(task_id, user_id, file.filename, content)
    else:
        task_manager.save_standard(task_id, file.filename, content)

    logger.info(f"任务 {task_id} 上传审核标准: {file.filename}")
    return {"message": "上传成功", "filename": file.filename}


@app.post("/api/tasks/{task_id}/standard/template")
async def use_template(
    task_id: str,
    template_name: str = Query(...),
    user_id: str = Depends(get_current_user),
):
    """使用默认模板作为审核标准（需要登录）"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 查找模板
    template_path = TEMPLATES_DIR / f"{template_name}.xlsx"
    if not template_path.exists():
        template_path = TEMPLATES_DIR / f"{template_name}.csv"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="模板不存在")

    # 复制模板到任务目录
    content = template_path.read_bytes()
    if USE_SUPABASE:
        task_manager.save_standard(task_id, user_id, template_path.name, content)
    else:
        task_manager.save_standard(task_id, template_path.name, content)

    # 更新任务
    task.standard_template = template_name
    task_manager.update_task(task)

    return {"message": "模板应用成功", "template": template_name}


# ==================== 审阅执行 API ====================

async def run_review(
    task_id: str,
    user_id: str,
    llm_provider: str = "deepseek",
    business_line_id: Optional[str] = None,
    special_requirements: Optional[str] = None,
):
    """后台执行审阅任务

    Args:
        task_id: 任务 ID
        user_id: 用户 ID（用于 Supabase 存储路径）
        llm_provider: LLM 提供者，可选 "deepseek" 或 "gemini"
        business_line_id: 业务条线 ID（可选，用于获取业务上下文）
        special_requirements: 本次特殊要求（可选，直接传递给LLM）
    """
    task = task_manager.get_task(task_id)
    if not task:
        return

    try:
        # 更新状态
        task.update_status("reviewing", "正在准备审阅...")
        task_manager.update_task(task)

        # 获取文档
        if USE_SUPABASE:
            doc_path = task_manager.get_document_path(task_id, user_id)
        else:
            doc_path = task_manager.get_document_path(task_id)
        if not doc_path:
            raise ValueError("未上传文档")

        # 获取审核标准
        if USE_SUPABASE:
            std_path = task_manager.get_standard_path(task_id, user_id)
        else:
            std_path = task_manager.get_standard_path(task_id)
        if not std_path:
            raise ValueError("未上传审核标准")

        # 加载文档（使用异步版本支持 OCR）
        ocr_service = get_ocr_service()
        suffix = doc_path.suffix.lower()

        # 检查是否需要 OCR 但未配置
        if suffix in {".jpg", ".jpeg", ".png", ".webp"} and not ocr_service:
            raise ValueError("处理图片文件需要配置 OCR 服务（DASHSCOPE_API_KEY）")

        document = await load_document_async(doc_path, ocr_service=ocr_service)

        # 解析审核标准
        standard_set = parse_standard_file(std_path)

        # 获取业务上下文（如果指定了业务条线）
        business_context = None
        if business_line_id:
            business_line = business_library_manager.get_business_line(business_line_id)
            if business_line:
                business_context = {
                    "business_line_id": business_line.id,
                    "business_line_name": business_line.name,
                    "name": business_line.name,  # prompts.py 使用 "name" 键
                    "industry": business_line.industry,
                    "contexts": business_line.contexts,  # 直接传递 BusinessContext 对象列表
                }
                logger.info(f"使用业务条线: {business_line.name} ({len(business_line.contexts)} 条背景信息)")

        # 进度回调
        def progress_callback(stage: str, percentage: int, message: str):
            task.update_progress(stage, percentage, message)
            task_manager.update_task(task)

        # 执行审阅（根据 llm_provider 选择模型）
        engine = ReviewEngine(settings, llm_provider=llm_provider)
        result = await engine.review_document(
            document=document,
            standards=standard_set.standards,
            our_party=task.our_party,
            material_type=task.material_type,
            task_id=task_id,
            language=getattr(task, 'language', 'zh-CN'),
            progress_callback=progress_callback,
            business_context=business_context,
            special_requirements=special_requirements,
        )

        # 保存结果
        if USE_SUPABASE:
            storage_manager.save_result(result)
        else:
            task_dir = settings.review.tasks_dir / task_id
            storage_manager.save_result(result, task_dir)

        # 更新任务
        task.result = result
        task.update_status("completed", "审阅完成")
        task_manager.update_task(task)

        # 审阅成功完成后扣除配额
        try:
            quota_service = get_quota_service()
            await quota_service.deduct_quota(user_id, task_id=task_id)
            logger.info(f"任务 {task_id} 配额扣除成功")
        except Exception as quota_error:
            logger.error(f"任务 {task_id} 配额扣除失败: {quota_error}")

        logger.info(f"任务 {task_id} 审阅完成，发现 {len(result.risks)} 个风险点")

    except Exception as e:
        logger.error(f"任务 {task_id} 审阅失败: {e}")
        task.update_status("failed", str(e))
        task_manager.update_task(task)


@app.post("/api/tasks/{task_id}/review")
async def start_review(
    task_id: str,
    background_tasks: BackgroundTasks,
    llm_provider: str = Query(default="deepseek", regex="^(deepseek|gemini)$"),
    business_line_id: Optional[str] = Query(default=None, description="业务条线ID（可选）"),
    special_requirements: Optional[str] = Query(default=None, description="本次特殊要求（可选，优先级最高）"),
    user_id: str = Depends(get_current_user),
):
    """开始审阅（需要登录）

    Args:
        task_id: 任务 ID
        llm_provider: LLM 提供者，可选 "deepseek"（初级）或 "gemini"（高级）
        business_line_id: 业务条线 ID（可选，用于提供业务上下文）
        special_requirements: 本次特殊要求（可选，直接传递给LLM，优先级最高）
    """
    print(f"User {user_id} is starting review for task {task_id}...")

    # 检查配额（在执行任何操作之前）
    quota_service = get_quota_service()
    await quota_service.check_quota(user_id)

    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status == "reviewing":
        raise HTTPException(status_code=400, detail="任务正在审阅中")

    # 检查文件
    if not task.document_filename:
        raise HTTPException(status_code=400, detail="请先上传待审阅文档")
    if not task.standard_filename:
        raise HTTPException(status_code=400, detail="请先上传审核标准")

    # 如果选择 Gemini，检查 API Key 是否配置
    if llm_provider == "gemini" and not settings.gemini.api_key:
        raise HTTPException(status_code=400, detail="高级智能模式未配置，请联系管理员")

    # 验证业务条线（如果提供了）
    if business_line_id:
        business_line = business_library_manager.get_business_line(business_line_id)
        if not business_line:
            raise HTTPException(status_code=400, detail="指定的业务条线不存在")
        logger.info(f"任务 {task_id} 将使用业务条线: {business_line.name}")

    # 启动后台任务，传递参数
    background_tasks.add_task(run_review, task_id, user_id, llm_provider, business_line_id, special_requirements)

    task.update_status("reviewing", "审阅任务已启动")
    task.update_progress("analyzing", 0, "正在启动...")
    task_manager.update_task(task)

    return {"message": "审阅任务已启动"}


# ==================== 配额管理 API ====================

class QuotaResponse(BaseModel):
    """配额信息响应"""
    user_id: str
    product_id: str
    plan_tier: str
    credits_balance: int
    total_usage: int
    billing_enabled: bool


@app.get("/api/quota", response_model=QuotaResponse)
async def get_quota(user_id: str = Depends(get_current_user)):
    """获取当前用户的配额信息"""
    quota_service = get_quota_service()
    quota = await quota_service.get_or_create_quota(user_id)

    return QuotaResponse(
        user_id=quota.user_id,
        product_id=quota.product_id,
        plan_tier=quota.plan_tier,
        credits_balance=quota.credits_balance,
        total_usage=quota.total_usage,
        billing_enabled=quota_service.is_enabled(),
    )


# ==================== 语言检测 API ====================

class LanguageDetectionRequest(BaseModel):
    text: str


class LanguageDetectionResponse(BaseModel):
    detected_language: str
    confidence: float


@app.post("/api/detect-language", response_model=LanguageDetectionResponse)
async def detect_language(request: LanguageDetectionRequest):
    """检测文档语言（基于中文字符比例）"""
    text = request.text[:5000]  # 只检测前5000字符

    # 统计中文字符数量
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # 统计非空白字符总数
    total_chars = len([c for c in text if c.strip()])

    if total_chars == 0:
        return LanguageDetectionResponse(
            detected_language="zh-CN",
            confidence=0.5
        )

    chinese_ratio = chinese_chars / total_chars

    # 阈值：15%以上中文字符判定为中文
    if chinese_ratio > 0.15:
        return LanguageDetectionResponse(
            detected_language="zh-CN",
            confidence=min(chinese_ratio * 2, 0.95)
        )
    else:
        return LanguageDetectionResponse(
            detected_language="en",
            confidence=min((1 - chinese_ratio), 0.95)
        )


# ==================== 文档预处理 API ====================

class PartyInfo(BaseModel):
    role: str  # 甲方、乙方、出租人等
    name: str  # 具体名称
    description: str = ""  # 角色描述


class PreprocessRequest(BaseModel):
    task_id: str


class PreprocessResponse(BaseModel):
    parties: List[PartyInfo]
    suggested_name: str
    language: str
    document_type: str = ""
    document_preview: str = ""  # 文档开头内容预览，方便用户判断身份


@app.post("/api/tasks/{task_id}/preprocess", response_model=PreprocessResponse)
async def preprocess_document(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    预处理文档，识别合同各方和文档类型

    用于简化用户操作：上传文档后自动识别各方，让用户选择而非手动输入
    """
    task_manager = SupabaseTaskManager()
    storage_manager = SupabaseStorageManager()

    # 获取任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证用户权限
    task_owner = task_manager.get_task_user_id(task_id)
    if task_owner != user_id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    # 检查是否有文档
    if not task.document_filename:
        raise HTTPException(status_code=400, detail="请先上传文档")

    # 读取文档内容
    try:
        # 获取文档路径（会自动从 Supabase Storage 下载到本地临时目录）
        if USE_SUPABASE:
            doc_path = task_manager.get_document_path(task_id, user_id)
        else:
            doc_path = task_manager.get_document_path(task_id)

        if not doc_path or not doc_path.exists():
            raise HTTPException(status_code=400, detail="文档文件不存在")

        # 读取文档内容
        document = await load_document_async(doc_path, ocr_service=get_ocr_service())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取文档失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取文档失败: {str(e)}")

    # 执行预处理
    try:
        preprocessor = DocumentPreprocessor(settings)
        result = await preprocessor.preprocess(document.text)

        # 提取文档开头内容作为预览（前1500字符）
        document_preview = document.text[:1500].strip()
        if len(document.text) > 1500:
            document_preview += "\n\n..."

        return PreprocessResponse(
            parties=[PartyInfo(**p) for p in result.get("parties", [])],
            suggested_name=result.get("suggested_name", "未命名文档"),
            language=result.get("language", "zh-CN"),
            document_type=result.get("document_type", ""),
            document_preview=document_preview,
        )
    except Exception as e:
        logger.error(f"文档预处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"文档预处理失败: {str(e)}")


# ==================== 结果管理 API ====================

@app.get("/api/tasks/{task_id}/result")
async def get_result(task_id: str):
    """获取审阅结果"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if USE_SUPABASE:
        result = storage_manager.load_result(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        result = storage_manager.load_result(task_dir)

    if not result:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    return result.model_dump(mode="json")


@app.patch("/api/tasks/{task_id}/result/modifications/{modification_id}")
async def update_modification(
    task_id: str,
    modification_id: str,
    request: UpdateModificationRequest,
):
    """更新修改建议（用户确认或修改文本）"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if USE_SUPABASE:
        result = storage_manager.load_result(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        result = storage_manager.load_result(task_dir)

    if not result:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    # 查找并更新修改建议
    found = False
    for mod in result.modifications:
        if mod.id == modification_id:
            if request.user_confirmed is not None:
                mod.user_confirmed = request.user_confirmed
            if request.user_modified_text is not None:
                mod.user_modified_text = request.user_modified_text
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="修改建议不存在")

    # 保存更新
    if USE_SUPABASE:
        storage_manager.update_result(task_id, result)
    else:
        storage_manager.update_result(task_dir, result)

    return {"message": "更新成功"}


@app.patch("/api/tasks/{task_id}/result/actions/{action_id}")
async def update_action(
    task_id: str,
    action_id: str,
    request: UpdateActionRequest = None,
    user_confirmed: Optional[bool] = Query(None)  # 保持向后兼容
):
    """更新行动建议（支持编辑所有字段）"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if USE_SUPABASE:
        result = storage_manager.load_result(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        result = storage_manager.load_result(task_dir)

    if not result:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    # 查找并更新行动建议
    found = False
    for action in result.actions:
        if action.id == action_id:
            # 支持旧的query参数方式（向后兼容）
            if user_confirmed is not None:
                action.user_confirmed = user_confirmed
            # 支持新的body方式
            if request:
                if request.user_confirmed is not None:
                    action.user_confirmed = request.user_confirmed
                if request.description is not None:
                    action.description = request.description
                if request.action_type is not None:
                    action.action_type = request.action_type
                if request.urgency is not None:
                    action.urgency = request.urgency
                if request.responsible_party is not None:
                    action.responsible_party = request.responsible_party
                if request.deadline_suggestion is not None:
                    action.deadline_suggestion = request.deadline_suggestion
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="行动建议不存在")

    # 保存更新
    if USE_SUPABASE:
        storage_manager.update_result(task_id, result)
    else:
        storage_manager.update_result(task_dir, result)

    return {"message": "更新成功"}


# ==================== 导出 API ====================

@app.get("/api/tasks/{task_id}/export/json")
async def export_json(task_id: str):
    """导出 JSON"""
    if USE_SUPABASE:
        json_content = storage_manager.export_to_json(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        json_content = storage_manager.export_to_json(task_dir)

    if not json_content:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    return Response(
        content=json_content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="review_result_{task_id}.json"'
        },
    )


@app.get("/api/tasks/{task_id}/export/excel")
async def export_excel(task_id: str):
    """导出 Excel"""
    if USE_SUPABASE:
        excel_content = storage_manager.export_to_excel(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        excel_content = storage_manager.export_to_excel(task_dir)

    if not excel_content:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    return Response(
        content=excel_content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="review_result_{task_id}.xlsx"'
        },
    )


@app.get("/api/tasks/{task_id}/export/csv")
async def export_csv(task_id: str):
    """导出 CSV"""
    if USE_SUPABASE:
        csv_content = storage_manager.export_to_csv(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        csv_content = storage_manager.export_to_csv(task_dir)

    if not csv_content:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="review_result_{task_id}.csv"'
        },
    )


@app.get("/api/tasks/{task_id}/export/report")
async def export_report(task_id: str):
    """导出 Markdown 摘要报告"""
    if USE_SUPABASE:
        result = storage_manager.load_result(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        result = storage_manager.load_result(task_dir)

    if not result:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    report = generate_summary_report(result)

    return Response(
        content=report,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="review_report_{task_id}.md"'
        },
    )


class ExportRedlineRequest(BaseModel):
    """导出 Redline 文档请求"""
    modification_ids: Optional[List[str]] = None  # 要应用的修改 ID，空则使用已确认的
    include_comments: bool = False  # 是否将行动建议作为批注添加


# ==================== Redline 异步导出相关 ====================

from dataclasses import dataclass
from typing import Dict
from datetime import datetime, timedelta
import threading

@dataclass
class RedlineExportJob:
    """Redline 导出任务"""
    task_id: str
    user_id: str
    status: str  # pending, processing, completed, failed
    progress: int  # 0-100
    message: str
    document_bytes: Optional[bytes] = None
    filename: Optional[str] = None
    created_at: datetime = None
    completed_at: datetime = None
    error: Optional[str] = None
    # 统计信息
    applied_count: int = 0
    skipped_count: int = 0
    comments_added: int = 0
    comments_skipped: int = 0
    # 模拟进度相关
    estimated_total_seconds: int = 180  # 预计总时长（默认3分钟）
    processing_started_at: Optional[datetime] = None  # 开始处理时间

# 内存缓存存储导出任务（键: task_id）
_redline_export_jobs: Dict[str, RedlineExportJob] = {}
_redline_jobs_lock = threading.Lock()

def _cleanup_old_jobs():
    """清理超过1小时的导出任务"""
    with _redline_jobs_lock:
        now = datetime.now()
        expired_keys = [
            k for k, v in _redline_export_jobs.items()
            if v.created_at and (now - v.created_at) > timedelta(hours=1)
        ]
        for k in expired_keys:
            del _redline_export_jobs[k]


async def _update_simulated_progress(job: RedlineExportJob):
    """
    模拟进度更新
    在实际处理期间（30%→89%），根据预估时间线性增加进度
    """
    import asyncio

    if not job.processing_started_at:
        return

    while job.status == "processing" and job.progress < 90:
        elapsed = (datetime.now() - job.processing_started_at).total_seconds()
        # 预估时间的80%用于30%→90%的进度（60%进度范围）
        estimated_processing_time = job.estimated_total_seconds * 0.8

        if elapsed < estimated_processing_time:
            # 线性进度：30% + (elapsed / estimated_processing_time) * 59%
            simulated_progress = 30 + int((elapsed / estimated_processing_time) * 59)
            # 确保不超过89%，留给真正完成时的90%
            job.progress = min(simulated_progress, 89)

            # 更新消息，显示预计剩余时间
            remaining = max(0, estimated_processing_time - elapsed)
            if remaining > 60:
                job.message = f"正在应用修改... 预计还需 {int(remaining / 60)} 分钟"
            elif remaining > 10:
                job.message = f"正在应用修改... 预计还需 {int(remaining)} 秒"
            else:
                job.message = "正在应用修改... 即将完成"

        await asyncio.sleep(2)  # 每2秒更新一次


async def _persist_redline_to_storage(job: RedlineExportJob):
    """
    将生成的 Redline 文件持久化到 Supabase Storage
    """
    if not USE_SUPABASE or not job.document_bytes:
        logger.info("跳过 Redline 持久化：未启用 Supabase 或无文件内容")
        return

    try:
        from uuid import uuid4
        from src.contract_review.supabase_client import get_supabase_client, get_storage_bucket

        # 生成安全的存储文件名
        safe_filename = f"{uuid4().hex}.docx"
        storage_path = f"{job.user_id}/{job.task_id}/redlines/{safe_filename}"

        supabase = get_supabase_client()
        bucket = get_storage_bucket()

        # 删除之前的 redline 文件（如果存在）
        try:
            existing = supabase.storage.from_(bucket).list(f"{job.user_id}/{job.task_id}/redlines")
            if existing:
                old_paths = [f"{job.user_id}/{job.task_id}/redlines/{f['name']}" for f in existing]
                if old_paths:
                    supabase.storage.from_(bucket).remove(old_paths)
        except Exception as e:
            logger.warning(f"清理旧 Redline 文件时出错: {e}")

        # 上传新文件
        supabase.storage.from_(bucket).upload(
            storage_path,
            job.document_bytes,
            file_options={
                "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "upsert": "true"
            }
        )

        # 更新 tasks 表
        supabase.table("tasks").update({
            "redline_filename": job.filename,
            "redline_storage_name": safe_filename,
            "redline_generated_at": datetime.now().isoformat(),
            "redline_applied_count": job.applied_count,
            "redline_comments_count": job.comments_added,
        }).eq("id", job.task_id).execute()

        logger.info(f"Redline 文件已持久化: {storage_path}")

    except Exception as e:
        logger.error(f"Redline 持久化失败: {e}", exc_info=True)
        # 不抛出异常，允许导出继续完成


async def _run_redline_export(
    job: RedlineExportJob,
    doc_path: Path,
    result: ReviewResult,
    request: Optional[ExportRedlineRequest],
):
    """后台执行 Redline 导出"""
    import asyncio
    import concurrent.futures

    try:
        job.status = "processing"
        job.progress = 10
        job.message = "正在准备文档..."

        # 筛选要应用的修改
        if request and request.modification_ids:
            modifications = [
                m for m in result.modifications
                if m.id in request.modification_ids
            ]
            filter_confirmed = False
        else:
            modifications = result.modifications
            filter_confirmed = True

        include_comments = request.include_comments if request else False

        job.progress = 30
        job.message = "正在应用修改... 预计需要 2-3 分钟"
        job.processing_started_at = datetime.now()

        # 启动模拟进度更新任务
        progress_task = asyncio.create_task(_update_simulated_progress(job))

        # 在线程池中执行同步阻塞操作
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            redline_result = await loop.run_in_executor(
                executor,
                lambda: generate_redline_document(
                    docx_path=doc_path,
                    modifications=modifications,
                    author="十行助理",
                    filter_confirmed=filter_confirmed,
                    actions=result.actions if include_comments else None,
                    risks=result.risks if include_comments else None,
                    include_comments=include_comments,
                )
            )

        # 取消进度更新任务
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        job.progress = 90
        job.message = "正在完成导出..."

        if not redline_result.success:
            error_msg = "; ".join(redline_result.skipped_reasons[:3])
            job.status = "failed"
            job.error = f"生成失败: {error_msg}"
            job.message = job.error
            return

        # 生成文件名
        original_name = doc_path.stem
        filename = f"{original_name}_redline.docx"

        # 保存结果
        job.document_bytes = redline_result.document_bytes
        job.filename = filename
        job.applied_count = redline_result.applied_count
        job.skipped_count = redline_result.skipped_count
        job.comments_added = redline_result.comments_added
        job.comments_skipped = redline_result.comments_skipped

        # 持久化到 Supabase Storage
        await _persist_redline_to_storage(job)

        job.status = "completed"
        job.progress = 100
        job.message = "导出完成"
        job.completed_at = datetime.now()

        logger.info(
            f"任务 {job.task_id} Redline 导出完成: 应用 {redline_result.applied_count} 条修改，"
            f"添加 {redline_result.comments_added} 条批注"
        )

    except Exception as e:
        logger.error(f"Redline 导出失败: {e}", exc_info=True)
        job.status = "failed"
        job.error = str(e)
        job.message = f"导出失败: {str(e)}"


@app.post("/api/tasks/{task_id}/export/redline/start")
async def start_redline_export(
    task_id: str,
    background_tasks: BackgroundTasks,
    request: ExportRedlineRequest = None,
    user_id: str = Depends(get_current_user),
):
    """
    启动后台 Redline 导出任务（需要登录）

    返回任务状态，前端可以轮询 /status 端点查询进度。
    """
    # 清理过期任务
    _cleanup_old_jobs()

    # 检查是否已有进行中的任务
    with _redline_jobs_lock:
        existing_job = _redline_export_jobs.get(task_id)
        if existing_job and existing_job.status in ("pending", "processing"):
            return {
                "job_id": task_id,
                "status": existing_job.status,
                "progress": existing_job.progress,
                "message": existing_job.message,
            }

    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查原始文档
    if USE_SUPABASE:
        doc_path = task_manager.get_document_path(task_id, user_id)
    else:
        doc_path = task_manager.get_document_path(task_id)
    if not doc_path:
        raise HTTPException(status_code=400, detail="未找到原始文档")

    if doc_path.suffix.lower() != '.docx':
        raise HTTPException(
            status_code=400,
            detail=f"Redline 导出只支持 .docx 格式，当前文档格式为 {doc_path.suffix}"
        )

    # 获取审阅结果
    if USE_SUPABASE:
        result = storage_manager.load_result(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        result = storage_manager.load_result(task_dir)

    if not result:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    # 检查是否有内容可导出
    if request and request.modification_ids:
        confirmed_count = len(request.modification_ids)
    else:
        confirmed_count = sum(1 for m in result.modifications if m.user_confirmed)

    include_comments = request.include_comments if request else False
    has_actions = bool(result.actions) if include_comments else False

    if confirmed_count == 0 and not has_actions:
        raise HTTPException(status_code=400, detail="没有已确认的修改建议或行动建议")

    # 创建导出任务
    job = RedlineExportJob(
        task_id=task_id,
        user_id=user_id,
        status="pending",
        progress=0,
        message="正在排队...",
        created_at=datetime.now(),
    )

    with _redline_jobs_lock:
        _redline_export_jobs[task_id] = job

    # 启动后台任务
    background_tasks.add_task(_run_redline_export, job, doc_path, result, request)

    return {
        "job_id": task_id,
        "status": "pending",
        "progress": 0,
        "message": "导出任务已启动",
    }


@app.get("/api/tasks/{task_id}/export/redline/status")
async def get_redline_export_status(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    查询 Redline 导出任务状态（需要登录）
    """
    with _redline_jobs_lock:
        job = _redline_export_jobs.get(task_id)

    if not job:
        return {
            "job_id": task_id,
            "status": "not_found",
            "progress": 0,
            "message": "没有找到导出任务",
        }

    response = {
        "job_id": task_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
    }

    if job.status == "completed":
        response["applied_count"] = job.applied_count
        response["skipped_count"] = job.skipped_count
        response["comments_added"] = job.comments_added
        response["comments_skipped"] = job.comments_skipped
        response["filename"] = job.filename
    elif job.status == "failed":
        response["error"] = job.error

    return response


@app.get("/api/tasks/{task_id}/export/redline/download")
async def download_redline_export(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    下载已完成的 Redline 导出文件（需要登录）
    """
    with _redline_jobs_lock:
        job = _redline_export_jobs.get(task_id)

    if not job:
        raise HTTPException(status_code=404, detail="没有找到导出任务")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail=f"导出任务未完成，当前状态: {job.status}")

    if not job.document_bytes:
        raise HTTPException(status_code=500, detail="导出文件丢失")

    # URL 编码文件名以支持中文
    from urllib.parse import quote
    filename_encoded = quote(job.filename or "redline.docx")
    content_disposition = f"attachment; filename*=UTF-8''{filename_encoded}"

    return Response(
        content=job.document_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": content_disposition,
            "X-Redline-Applied": str(job.applied_count),
            "X-Redline-Skipped": str(job.skipped_count),
            "X-Comments-Added": str(job.comments_added),
            "X-Comments-Skipped": str(job.comments_skipped),
        },
    )


# ==================== 持久化 Redline 文件 API ====================

@app.get("/api/tasks/{task_id}/redline/info")
async def get_redline_info(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    获取任务的 Redline 文件信息（如果已生成并持久化）
    """
    if not USE_SUPABASE:
        return {"exists": False, "message": "持久化存储未启用"}

    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查任务是否有持久化的 redline 文件
    if not task.redline_storage_name:
        return {"exists": False}

    return {
        "exists": True,
        "filename": task.redline_filename,
        "generated_at": task.redline_generated_at.isoformat() if task.redline_generated_at else None,
        "applied_count": task.redline_applied_count,
        "comments_count": task.redline_comments_count,
    }


@app.get("/api/tasks/{task_id}/redline/download-persisted")
async def download_persisted_redline(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    下载已持久化的 Redline 文件
    """
    if not USE_SUPABASE:
        raise HTTPException(status_code=400, detail="持久化存储未启用")

    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if not task.redline_storage_name:
        raise HTTPException(status_code=404, detail="没有找到已生成的 Redline 文件")

    try:
        from src.contract_review.supabase_client import get_supabase_client, get_storage_bucket

        supabase = get_supabase_client()
        bucket = get_storage_bucket()
        storage_path = f"{user_id}/{task_id}/redlines/{task.redline_storage_name}"

        file_bytes = supabase.storage.from_(bucket).download(storage_path)

        from urllib.parse import quote
        filename_encoded = quote(task.redline_filename or "redline.docx")
        content_disposition = f"attachment; filename*=UTF-8''{filename_encoded}"

        return Response(
            content=file_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": content_disposition,
                "X-Redline-Applied": str(task.redline_applied_count or 0),
                "X-Comments-Added": str(task.redline_comments_count or 0),
            },
        )
    except Exception as e:
        logger.error(f"下载 Redline 文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="下载失败")


# ==================== 原同步导出 API（保留兼容性）====================

@app.post("/api/tasks/{task_id}/export/redline")
async def export_redline(
    task_id: str,
    request: ExportRedlineRequest = None,
    user_id: str = Depends(get_current_user),
):
    """
    导出带修订标记的 Word 文档（需要登录）

    将用户确认的修改建议以 Track Changes 形式应用到原始文档。
    可选择将行动建议作为批注添加到对应风险点位置。
    只支持 .docx 格式的原始文档。
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查原始文档
    if USE_SUPABASE:
        doc_path = task_manager.get_document_path(task_id, user_id)
    else:
        doc_path = task_manager.get_document_path(task_id)
    if not doc_path:
        raise HTTPException(status_code=400, detail="未找到原始文档")

    if doc_path.suffix.lower() != '.docx':
        raise HTTPException(
            status_code=400,
            detail=f"Redline 导出只支持 .docx 格式，当前文档格式为 {doc_path.suffix}"
        )

    # 获取审阅结果
    if USE_SUPABASE:
        result = storage_manager.load_result(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        result = storage_manager.load_result(task_dir)

    if not result:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    # 筛选要应用的修改
    if request and request.modification_ids:
        # 使用指定的修改 ID
        modifications = [
            m for m in result.modifications
            if m.id in request.modification_ids
        ]
        filter_confirmed = False
    else:
        # 使用已确认的修改
        modifications = result.modifications
        filter_confirmed = True

    # 是否包含批注
    include_comments = request.include_comments if request else False

    # 检查是否有内容可导出
    confirmed_mods = [m for m in modifications if m.user_confirmed] if filter_confirmed else modifications
    has_actions = bool(result.actions) if include_comments else False

    if not confirmed_mods and not has_actions:
        raise HTTPException(status_code=400, detail="没有已确认的修改建议或行动建议")

    # 生成 Redline 文档
    try:
        redline_result = generate_redline_document(
            docx_path=doc_path,
            modifications=modifications,
            author="十行助理",
            filter_confirmed=filter_confirmed,
            actions=result.actions if include_comments else None,
            risks=result.risks if include_comments else None,
            include_comments=include_comments,
        )
    except Exception as e:
        logger.error(f"生成 Redline 文档时发生异常: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"生成 Redline 文档时发生内部错误: {str(e)}"
        )

    if not redline_result.success:
        error_msg = "; ".join(redline_result.skipped_reasons[:3])
        raise HTTPException(
            status_code=400,
            detail=f"生成 Redline 文档失败: {error_msg}"
        )

    # 生成文件名（处理中文文件名）
    original_name = doc_path.stem
    filename = f"{original_name}_redline.docx"

    # URL 编码文件名以支持中文（RFC 5987）
    from urllib.parse import quote
    filename_encoded = quote(filename)
    # 使用 filename* 参数支持 UTF-8 编码的文件名
    content_disposition = f"attachment; filename*=UTF-8''{filename_encoded}"

    logger.info(
        f"任务 {task_id} 导出 Redline: 应用 {redline_result.applied_count} 条修改，"
        f"添加 {redline_result.comments_added} 条批注，"
        f"跳过 {redline_result.skipped_count + redline_result.comments_skipped} 条"
    )

    # 构建响应头
    response_headers = {
        "Content-Disposition": content_disposition,
        "X-Redline-Applied": str(redline_result.applied_count),
        "X-Redline-Skipped": str(redline_result.skipped_count),
        "X-Comments-Added": str(redline_result.comments_added),
        "X-Comments-Skipped": str(redline_result.comments_skipped),
    }

    # 添加跳过原因摘要（最多3条，方便前端显示）
    if redline_result.skipped_reasons:
        # 简化原因描述，只保留关键信息
        brief_reasons = []
        for reason in redline_result.skipped_reasons[:3]:
            # 截取关键部分
            if len(reason) > 80:
                reason = reason[:77] + "..."
            brief_reasons.append(reason)
        response_headers["X-Redline-Skipped-Reasons"] = "; ".join(brief_reasons)

    return Response(
        content=redline_result.document_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=response_headers,
    )


@app.get("/api/tasks/{task_id}/export/redline/preview")
async def preview_redline(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    预览 Redline 导出信息（需要登录）

    返回可以导出的修改建议数量、行动建议数量和状态。
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查原始文档格式
    if USE_SUPABASE:
        doc_path = task_manager.get_document_path(task_id, user_id)
    else:
        doc_path = task_manager.get_document_path(task_id)
    can_export = doc_path and doc_path.suffix.lower() == '.docx'

    # 获取审阅结果
    if USE_SUPABASE:
        result = storage_manager.load_result(task_id)
    else:
        task_dir = settings.review.tasks_dir / task_id
        result = storage_manager.load_result(task_dir)

    if not result:
        return {
            "can_export": False,
            "reason": "暂无审阅结果",
            "total_modifications": 0,
            "confirmed_modifications": 0,
            "total_actions": 0,
        }

    confirmed_count = sum(1 for m in result.modifications if m.user_confirmed)
    actions_count = len(result.actions) if result.actions else 0
    confirmed_actions_count = sum(1 for a in result.actions if a.user_confirmed) if result.actions else 0

    # 检查有多少已确认的行动建议可以作为批注（有关联风险点且风险点有原文）
    commentable_actions = 0
    if result.actions and result.risks:
        risk_map = {r.id: r for r in result.risks}
        for action in result.actions:
            # 只统计用户已确认的行动建议
            if not action.user_confirmed:
                continue
            for risk_id in action.related_risk_ids:
                risk = risk_map.get(risk_id)
                if risk and risk.location and risk.location.original_text:
                    commentable_actions += 1
                    break

    return {
        "can_export": can_export and (confirmed_count > 0 or commentable_actions > 0),
        "reason": None if can_export else "原始文档不是 .docx 格式",
        "total_modifications": len(result.modifications),
        "confirmed_modifications": confirmed_count,
        "total_actions": actions_count,
        "confirmed_actions": confirmed_actions_count,
        "commentable_actions": commentable_actions,
        "document_format": doc_path.suffix.lower() if doc_path else None,
    }


# ==================== 模板 API ====================

@app.get("/api/templates", response_model=List[TemplateInfo])
async def list_templates():
    """获取可用的审核标准模板列表"""
    templates = []

    if TEMPLATES_DIR.exists():
        for f in TEMPLATES_DIR.iterdir():
            if f.suffix.lower() in {".xlsx", ".csv"}:
                # 从文件名推断描述
                name = f.stem
                if "contract" in name.lower() or "合同" in name:
                    desc = "通用合同审核标准模板"
                elif "marketing" in name.lower() or "营销" in name:
                    desc = "营销材料合规检查标准模板"
                else:
                    desc = "审核标准模板"

                templates.append(TemplateInfo(
                    name=name,
                    filename=f.name,
                    description=desc,
                ))

    return templates


@app.get("/api/templates/{template_name}")
async def download_template(template_name: str):
    """下载模板文件"""
    template_path = TEMPLATES_DIR / f"{template_name}.xlsx"
    if not template_path.exists():
        template_path = TEMPLATES_DIR / f"{template_name}.csv"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="模板不存在")

    return FileResponse(
        template_path,
        filename=template_path.name,
        media_type="application/octet-stream",
    )


# ==================== 标准库管理 API ====================

def _standard_to_response(s: ReviewStandard) -> StandardResponse:
    """将 ReviewStandard 转换为 StandardResponse"""
    return StandardResponse(
        id=s.id,
        category=s.category,
        item=s.item,
        description=s.description,
        risk_level=s.risk_level,
        applicable_to=list(s.applicable_to),
        usage_instruction=s.usage_instruction,
        tags=list(s.tags),
        created_at=s.created_at.isoformat() if s.created_at else None,
        updated_at=s.updated_at.isoformat() if s.updated_at else None,
    )


@app.get("/api/standard-library", response_model=StandardLibraryStatsResponse)
async def get_standard_library_stats():
    """获取标准库统计信息"""
    stats = standard_library_manager.get_stats()
    return StandardLibraryStatsResponse(**stats)


@app.get("/api/standard-library/standards", response_model=List[StandardResponse])
async def list_library_standards(
    category: Optional[str] = Query(default=None, description="按分类筛选"),
    material_type: Optional[str] = Query(default=None, description="按材料类型筛选"),
    keyword: Optional[str] = Query(default=None, description="搜索关键词"),
):
    """获取标准库中的所有标准"""
    standards = standard_library_manager.list_standards(
        category=category,
        material_type=material_type,
        keyword=keyword,
    )
    return [_standard_to_response(s) for s in standards]


@app.post("/api/standard-library/standards", response_model=StandardResponse)
async def create_library_standard(request: CreateStandardRequest):
    """添加单条标准到标准库"""
    standard = ReviewStandard(
        category=request.category,
        item=request.item,
        description=request.description,
        risk_level=request.risk_level,
        applicable_to=request.applicable_to,
        usage_instruction=request.usage_instruction,
        tags=request.tags,
    )
    standard_id = standard_library_manager.add_standard(standard)

    # 重新获取以返回完整信息
    created = standard_library_manager.get_standard(standard_id)
    logger.info(f"创建标准: {standard_id} - {request.item}")
    return _standard_to_response(created)


@app.post("/api/standard-library/standards/batch")
async def batch_create_library_standards(request: BatchCreateStandardsRequest):
    """批量添加标准到标准库"""
    standards = []
    for req in request.standards:
        standard = ReviewStandard(
            category=req.category,
            item=req.item,
            description=req.description,
            risk_level=req.risk_level,
            applicable_to=req.applicable_to,
            usage_instruction=req.usage_instruction,
            tags=req.tags,
        )
        standards.append(standard)

    ids = standard_library_manager.add_standards_batch(standards)
    logger.info(f"批量创建 {len(ids)} 条标准")
    return {"message": f"成功添加 {len(ids)} 条标准", "ids": ids}


@app.get("/api/standard-library/standards/{standard_id}", response_model=StandardResponse)
async def get_library_standard(standard_id: str):
    """获取单条标准详情"""
    standard = standard_library_manager.get_standard(standard_id)
    if not standard:
        raise HTTPException(status_code=404, detail="标准不存在")
    return _standard_to_response(standard)


@app.put("/api/standard-library/standards/{standard_id}", response_model=StandardResponse)
async def update_library_standard(standard_id: str, request: UpdateStandardRequest):
    """更新标准"""
    updates = {k: v for k, v in request.model_dump().items() if v is not None}

    success = standard_library_manager.update_standard(standard_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="标准不存在")

    updated = standard_library_manager.get_standard(standard_id)
    logger.info(f"更新标准: {standard_id}")
    return _standard_to_response(updated)


@app.delete("/api/standard-library/standards/{standard_id}")
async def delete_library_standard(standard_id: str):
    """删除标准"""
    success = standard_library_manager.delete_standard(standard_id)
    if not success:
        raise HTTPException(status_code=404, detail="标准不存在")

    logger.info(f"删除标准: {standard_id}")
    return {"message": "删除成功"}


@app.get("/api/standard-library/categories")
async def get_library_categories():
    """获取所有分类"""
    categories = standard_library_manager.get_categories()
    return {"categories": categories}


@app.get("/api/standard-library/export")
async def export_library(format: str = Query(default="csv", regex="^(csv|json)$")):
    """导出标准库"""
    if format == "csv":
        content = standard_library_manager.export_to_csv()
        media_type = "text/csv"
        filename = "standard_library.csv"
    else:
        content = standard_library_manager.export_to_json()
        media_type = "application/json"
        filename = "standard_library.json"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/standard-library/import")
async def import_to_library(
    file: UploadFile = File(...),
    replace: bool = Query(default=False, description="是否替换现有库"),
):
    """从文件导入标准到标准库"""
    import tempfile

    # 检查文件类型
    suffix = Path(file.filename).suffix.lower()
    allowed = {".xlsx", ".xls", ".csv", ".docx", ".md", ".txt"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。支持的格式: {', '.join(allowed)}",
        )

    # 保存临时文件并解析
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 解析标准文件
        standard_set = parse_standard_file(tmp_path)

        # 导入到标准库
        imported_count, warnings = standard_library_manager.import_from_parsed_standards(
            standard_set.standards,
            replace=replace,
        )

        logger.info(f"导入标准: {imported_count} 条，来自 {file.filename}")

        return {
            "message": f"成功导入 {imported_count} 条标准",
            "imported_count": imported_count,
            "warnings": warnings,
        }
    finally:
        tmp_path.unlink()


# ==================== 标准集合 API ====================

class CollectionResponse(BaseModel):
    """标准集合响应"""
    id: str
    name: str
    description: str
    usage_instruction: Optional[str] = None
    material_type: str
    is_preset: bool
    language: str = "zh-CN"
    standard_count: int
    standards: Optional[List[StandardResponse]] = None


class CollectionWithStandardsResponse(BaseModel):
    """标准集合（包含标准列表）响应"""
    id: str
    name: str
    description: str
    material_type: str
    is_preset: bool
    language: str = "zh-CN"
    standard_count: int
    standards: List[StandardResponse]


def _collection_to_response(collection, standards: list = None) -> CollectionResponse:
    """将集合转换为响应格式"""
    # 通过 collection_id 关联计算标准数量
    library = standard_library_manager._load_library()
    standard_count = len([s for s in library.standards if s.collection_id == collection.id])

    response = CollectionResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        usage_instruction=getattr(collection, 'usage_instruction', None),
        material_type=collection.material_type,
        is_preset=collection.is_preset,
        language=getattr(collection, 'language', 'zh-CN'),
        standard_count=standard_count,
        standards=None,
    )
    if standards:
        response.standards = [_standard_to_response(s) for s in standards]
    return response


@app.get("/api/standard-library/collections", response_model=List[CollectionResponse])
async def list_collections(
    material_type: Optional[str] = None,
    language: Optional[str] = Query(default=None, description="按语言筛选 (zh-CN 或 en)")
):
    """获取所有标准集合"""
    collections = standard_library_manager.list_collections(language=language)

    # 按材料类型筛选
    if material_type:
        collections = [c for c in collections if c.material_type == material_type or c.material_type == "both"]

    return [_collection_to_response(c) for c in collections]


@app.post("/api/standard-library/collections/recommend", response_model=List[CollectionRecommendationItem])
async def recommend_collections(request: RecommendCollectionsRequest):
    """
    根据文档内容推荐标准集合（使用 LLM）

    分析文档内容，根据各集合的 usage_instruction 推荐最适合的审核标准集合。
    """
    import json
    import re

    # 获取所有可用集合
    collections = standard_library_manager.list_collections()

    # 按材料类型筛选
    if request.material_type:
        collections = [
            c for c in collections
            if c.material_type == request.material_type or c.material_type == "both"
        ]

    if not collections:
        return []

    # 准备集合数据供 LLM 分析
    collections_for_llm = []
    for c in collections:
        # 计算标准数量
        library = standard_library_manager._load_library()
        standard_count = len([s for s in library.standards if s.collection_id == c.id])

        collections_for_llm.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "usage_instruction": getattr(c, 'usage_instruction', None),
            "standard_count": standard_count,
        })

    try:
        # 构建 Prompt
        messages = build_collection_recommendation_messages(
            document_text=request.document_text[:1000],
            material_type=request.material_type,
            collections=collections_for_llm,
        )

        # 调用 LLM
        response = await llm_client.chat(messages, max_output_tokens=1000)

        # 解析 JSON 响应
        response = response.strip()
        # 移除可能的 markdown 代码块
        response = re.sub(r"```json\s*", "", response)
        response = re.sub(r"```\s*$", "", response)

        # 尝试找到 JSON 数组
        start = response.find("[")
        end = response.rfind("]")
        if start != -1 and end != -1:
            response = response[start:end + 1]

        recommendations = json.loads(response)

        # 构建响应
        results = []
        collection_map = {c.id: c for c in collections}
        collection_count_map = {c["id"]: c["standard_count"] for c in collections_for_llm}

        for rec in recommendations:
            collection_id = rec.get("collection_id")
            collection = collection_map.get(collection_id)
            if collection:
                results.append(CollectionRecommendationItem(
                    collection_id=collection_id,
                    collection_name=collection.name,
                    relevance_score=float(rec.get("relevance_score", 0)),
                    match_reason=rec.get("match_reason", ""),
                    standard_count=collection_count_map.get(collection_id, 0),
                    usage_instruction=getattr(collection, 'usage_instruction', None),
                ))

        # 按相关性排序
        results.sort(key=lambda x: x.relevance_score, reverse=True)

        logger.info(f"推荐 {len(results)} 个标准集合")
        return results

    except json.JSONDecodeError as e:
        logger.error(f"解析 LLM 响应失败: {e}")
        raise HTTPException(status_code=500, detail="LLM 响应解析失败")
    except Exception as e:
        logger.error(f"推荐集合失败: {e}")
        raise HTTPException(status_code=500, detail=f"推荐失败: {str(e)}")


@app.get("/api/standard-library/collections/{collection_id}", response_model=CollectionWithStandardsResponse)
async def get_collection(collection_id: str):
    """获取单个集合（包含标准列表）"""
    result = standard_library_manager.get_collection_with_standards(collection_id)
    if result is None:
        raise HTTPException(status_code=404, detail="集合不存在")

    collection = result["collection"]
    standards = result["standards"]

    return CollectionWithStandardsResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        material_type=collection.material_type,
        is_preset=collection.is_preset,
        language=getattr(collection, 'language', 'zh-CN'),
        standard_count=len(standards),
        standards=[_standard_to_response(s) for s in standards],
    )


# ---------- 集合创建/更新/删除 ----------

class CreateCollectionRequest(BaseModel):
    """创建集合请求"""
    name: str
    description: str = ""
    material_type: str = "both"
    language: str = "zh-CN"  # "zh-CN" 或 "en"


class UpdateCollectionRequest(BaseModel):
    """更新集合请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    usage_instruction: Optional[str] = None
    material_type: Optional[str] = None
    language: Optional[str] = None


@app.post("/api/standard-library/collections", response_model=CollectionResponse)
async def create_collection(request: CreateCollectionRequest):
    """创建新的标准集合"""
    collection = standard_library_manager.add_collection(
        name=request.name,
        description=request.description,
        material_type=request.material_type,
        is_preset=False,
        language=request.language,
    )
    logger.info(f"创建标准集合: {collection.id} - {collection.name} (language={request.language})")
    return _collection_to_response(collection)


@app.put("/api/standard-library/collections/{collection_id}", response_model=CollectionResponse)
async def update_collection(collection_id: str, request: UpdateCollectionRequest):
    """更新集合信息"""
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有提供要更新的字段")

    success = standard_library_manager.update_collection(collection_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="集合不存在")

    collection = standard_library_manager.get_collection(collection_id)
    return _collection_to_response(collection)


@app.post("/api/standard-library/collections/{collection_id}/generate-usage-instruction")
async def generate_collection_usage_instruction(collection_id: str):
    """为集合生成适用说明（使用 LLM）"""
    # 获取集合信息
    result = standard_library_manager.get_collection_with_standards(collection_id)
    if result is None:
        raise HTTPException(status_code=404, detail="集合不存在")

    collection = result["collection"]
    standards = result["standards"]

    try:
        # 构建标准列表摘要
        standards_data = [
            {"category": s.category, "item": s.item}
            for s in standards
        ]

        # 获取集合语言
        language = getattr(collection, 'language', 'zh-CN')

        # 构建 Prompt
        messages = build_collection_usage_instruction_messages(
            collection_name=collection.name,
            collection_description=collection.description or "",
            material_type=collection.material_type,
            standards=standards_data,
            language=language,
        )

        # 调用 LLM
        usage_instruction = await llm_client.chat(messages, max_output_tokens=300)
        usage_instruction = usage_instruction.strip()

        # 更新集合
        standard_library_manager.update_collection(
            collection_id,
            {"usage_instruction": usage_instruction}
        )

        logger.info(f"为集合 {collection_id} 生成适用说明")

        return {
            "collection_id": collection_id,
            "usage_instruction": usage_instruction,
        }

    except Exception as e:
        logger.error(f"生成集合适用说明失败: {collection_id} - {e}")
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


@app.delete("/api/standard-library/collections/{collection_id}")
async def delete_collection(collection_id: str, force: bool = False):
    """删除集合（连同删除所有风险点）"""
    success = standard_library_manager.delete_collection(collection_id, force=force)
    if not success:
        raise HTTPException(status_code=400, detail="集合不存在或为系统预设不可删除")
    return {"message": "删除成功"}


# ---------- 集合内标准管理 ----------

@app.get("/api/standard-library/collections/{collection_id}/standards", response_model=List[StandardResponse])
async def list_collection_standards(
    collection_id: str,
    category: Optional[str] = None,
    risk_level: Optional[str] = None,
    keyword: Optional[str] = None,
):
    """获取集合内的标准列表（支持筛选）"""
    collection = standard_library_manager.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="集合不存在")

    standards = standard_library_manager.list_collection_standards(
        collection_id=collection_id,
        category=category,
        risk_level=risk_level,
        keyword=keyword,
    )
    return [_standard_to_response(s) for s in standards]


@app.post("/api/standard-library/collections/{collection_id}/standards", response_model=StandardResponse)
async def add_standard_to_collection(collection_id: str, request: CreateStandardRequest):
    """向集合中添加单条标准"""
    collection = standard_library_manager.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="集合不存在")

    standard = ReviewStandard(
        category=request.category,
        item=request.item,
        description=request.description,
        risk_level=request.risk_level,
        applicable_to=request.applicable_to,
        usage_instruction=request.usage_instruction,
        tags=request.tags,
    )

    standard_id = standard_library_manager.add_standard_to_collection(collection_id, standard)
    created = standard_library_manager.get_standard(standard_id)
    return _standard_to_response(created)


@app.get("/api/standard-library/collections/{collection_id}/categories", response_model=List[str])
async def get_collection_categories(collection_id: str):
    """获取集合内的所有分类"""
    collection = standard_library_manager.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="集合不存在")

    return standard_library_manager.get_collection_categories(collection_id)


# ==================== 标准制作 API ====================

@app.post("/api/standards/create-from-business", response_model=StandardCreationResponse)
async def create_standards_from_business(request: StandardCreationRequest):
    """根据业务信息生成审阅标准（使用 Gemini）"""
    from src.contract_review.gemini_client import GeminiClient
    from src.contract_review.prompts import get_standard_creation_prompts

    # 检查 Gemini API Key 是否配置
    if not settings.gemini.api_key:
        raise HTTPException(
            status_code=500,
            detail="Gemini API Key 未配置，请设置环境变量 GEMINI_API_KEY"
        )

    # 验证必填字段
    if not request.business_scenario or not request.business_scenario.strip():
        raise HTTPException(status_code=400, detail="业务场景描述不能为空")
    if not request.focus_areas:
        raise HTTPException(status_code=400, detail="请至少选择一个核心关注点")

    # 获取语言对应的提示词
    language = request.language if request.language in ("zh-CN", "en") else "zh-CN"
    prompts = get_standard_creation_prompts(language)

    # 创建 Gemini 客户端
    gemini_client = GeminiClient(
        api_key=settings.gemini.api_key,
        model=settings.gemini.model,
        timeout=settings.gemini.timeout,
    )

    # 构建业务信息
    business_info = {
        "document_type": request.document_type,
        "business_scenario": request.business_scenario,
        "focus_areas": request.focus_areas,
        "our_role": request.our_role,
        "industry": request.industry,
        "special_risks": request.special_risks,
        "reference_material": request.reference_material,
        "language": language,
    }

    try:
        # 调用 Gemini 生成标准
        result = await gemini_client.generate_standards(
            business_info=business_info,
            system_prompt=prompts["system"],
            user_prompt_template=prompts["user"],
        )

        # 转换为响应格式
        standards = []
        for s in result.get("standards", []):
            # 根据 document_type 设置 applicable_to
            if request.document_type == "both":
                applicable_to = ["contract", "marketing"]
            elif request.document_type == "contract":
                applicable_to = ["contract"]
            else:
                applicable_to = ["marketing"]

            # 优先使用 LLM 生成的 applicable_to，否则使用默认值
            final_applicable_to = s.get("applicable_to", applicable_to)

            standards.append(GeneratedStandard(
                category=s.get("category", "未分类"),
                item=s.get("item", ""),
                description=s.get("description", ""),
                risk_level=s.get("risk_level", "medium"),
                applicable_to=final_applicable_to,
                usage_instruction=s.get("usage_instruction", ""),
            ))

        # AI 生成的集合名称（如果没有则根据业务场景生成默认名称）
        collection_name = result.get("collection_name", "")
        if not collection_name:
            # 根据业务场景生成默认名称
            industry = request.industry or ""
            scenario = request.business_scenario[:20] if request.business_scenario else ""
            collection_name = f"{industry}{scenario}审核标准".strip()

        logger.info(f"成功生成 {len(standards)} 条审阅标准，集合名称: {collection_name}")

        return StandardCreationResponse(
            collection_name=collection_name,
            standards=standards,
            generation_summary=result.get("generation_summary", f"成功生成 {len(standards)} 条审阅标准"),
        )

    except Exception as e:
        logger.error(f"生成审阅标准失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"生成审阅标准失败: {str(e)}"
        )


# ==================== 标准预览与入库 API ====================

@app.post("/api/standards/preview", response_model=StandardPreviewResponse)
async def preview_standards(file: UploadFile = File(...)):
    """预览上传的标准文件（解析但不保存）"""
    import tempfile

    # 检查文件类型
    suffix = Path(file.filename).suffix.lower()
    allowed = {".xlsx", ".xls", ".csv", ".docx", ".md", ".txt"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。支持的格式: {', '.join(allowed)}",
        )

    # 保存临时文件并解析
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # 解析标准文件
        standard_set = parse_standard_file(tmp_path)

        # 转换为响应格式
        standards = [_standard_to_response(s) for s in standard_set.standards]

        logger.info(f"预览标准文件: {file.filename}，共 {len(standards)} 条")

        return StandardPreviewResponse(
            standards=standards,
            total_count=len(standards),
            parse_warnings=[],
        )
    except Exception as e:
        logger.error(f"解析标准文件失败: {e}")
        raise HTTPException(status_code=400, detail=f"解析文件失败: {str(e)}")
    finally:
        tmp_path.unlink()


@app.post("/api/standards/save-to-library")
async def save_standards_to_library(request: SaveToLibraryRequest):
    """将预览的标准保存到标准库（创建新集合）"""
    if not request.collection_name or not request.collection_name.strip():
        raise HTTPException(status_code=400, detail="集合名称不能为空")

    if not request.standards:
        raise HTTPException(status_code=400, detail="至少需要一条标准")

    # 1. 创建集合
    collection = standard_library_manager.add_collection(
        name=request.collection_name.strip(),
        description=request.collection_description,
        material_type=request.material_type,
        is_preset=False,
        language=request.language,
    )

    # 2. 创建标准并关联到集合
    standards = []
    for req in request.standards:
        standard = ReviewStandard(
            category=req.category,
            item=req.item,
            description=req.description,
            risk_level=req.risk_level,
            applicable_to=req.applicable_to,
            usage_instruction=req.usage_instruction,
            tags=req.tags,
        )
        standards.append(standard)

    # 3. 批量添加到集合
    standard_ids = standard_library_manager.add_standards_to_collection(collection.id, standards)

    logger.info(f"保存到标准库: 集合 {collection.name}，共 {len(standard_ids)} 条标准")

    return {
        "message": f"成功创建标准集「{collection.name}」，包含 {len(standard_ids)} 条标准",
        "collection_id": collection.id,
        "collection_name": collection.name,
        "imported_count": len(standard_ids),
    }


# ==================== LLM 相关 API ====================

# 批量生成使用说明的最大标准数量
MAX_BATCH_USAGE_INSTRUCTION = 20


@app.post("/api/standards/generate-usage-instruction")
async def generate_usage_instruction(request: GenerateUsageInstructionRequest):
    """为指定标准生成适用说明（使用 LLM）"""
    # 限制单次处理的标准数量
    if len(request.standard_ids) > MAX_BATCH_USAGE_INSTRUCTION:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多处理 {MAX_BATCH_USAGE_INSTRUCTION} 个标准，当前请求 {len(request.standard_ids)} 个",
        )

    results = []
    errors = []

    for standard_id in request.standard_ids:
        standard = standard_library_manager.get_standard(standard_id)
        if not standard:
            errors.append(f"标准不存在: {standard_id}")
            continue

        try:
            # 构建 Prompt
            messages = build_usage_instruction_messages(
                standard=standard,
                sample_document_text=request.sample_document_text or "",
            )

            # 调用 LLM
            usage_instruction = await llm_client.chat(messages, max_output_tokens=200)
            usage_instruction = usage_instruction.strip()

            # 更新标准
            standard_library_manager.update_standard(
                standard_id,
                {"usage_instruction": usage_instruction}
            )

            results.append(UsageInstructionResult(
                standard_id=standard_id,
                usage_instruction=usage_instruction,
            ))

            logger.info(f"为标准 {standard_id} 生成适用说明")

        except Exception as e:
            logger.error(f"生成适用说明失败: {standard_id} - {e}")
            errors.append(f"生成失败 ({standard_id}): {str(e)}")

    return {
        "results": [r.model_dump() for r in results],
        "errors": errors,
        "success_count": len(results),
    }


# 推荐标准时的文档长度限制和标准数量限制
MAX_RECOMMEND_DOC_CHARS = 10000  # 最多使用文档前 10000 字符
MAX_RECOMMEND_STANDARDS = 50     # 最多考虑 50 个标准


@app.post("/api/standards/recommend", response_model=List[StandardRecommendationResponse])
async def recommend_standards(request: RecommendStandardsRequest):
    """根据文档内容推荐审核标准（使用 LLM）"""
    import json
    import re

    # 获取适用该材料类型的所有标准
    available_standards = standard_library_manager.list_standards(
        material_type=request.material_type
    )

    if not available_standards:
        return []

    # 限制标准数量（优先使用高风险标准）
    if len(available_standards) > MAX_RECOMMEND_STANDARDS:
        # 按风险等级排序：high > medium > low
        risk_order = {"high": 0, "medium": 1, "low": 2}
        available_standards = sorted(
            available_standards,
            key=lambda s: risk_order.get(s.risk_level, 1)
        )[:MAX_RECOMMEND_STANDARDS]
        logger.info(f"推荐标准：标准数量 {len(available_standards)} 超过限制，已截取前 {MAX_RECOMMEND_STANDARDS} 个高优先级标准")

    # 限制文档长度
    doc_text = request.document_text
    if len(doc_text) > MAX_RECOMMEND_DOC_CHARS:
        doc_text = doc_text[:MAX_RECOMMEND_DOC_CHARS]
        logger.info(f"推荐标准：文档长度超过限制，已截取前 {MAX_RECOMMEND_DOC_CHARS} 字符")

    try:
        # 构建 Prompt
        messages = build_standard_recommendation_messages(
            document_text=doc_text,
            material_type=request.material_type,
            available_standards=available_standards,
        )

        # 调用 LLM
        response = await llm_client.chat(messages, max_output_tokens=2000)

        # 解析 JSON 响应
        response = response.strip()
        # 移除可能的 markdown 代码块
        response = re.sub(r"```json\s*", "", response)
        response = re.sub(r"```\s*$", "", response)

        # 尝试找到 JSON 数组
        start = response.find("[")
        end = response.rfind("]")
        if start != -1 and end != -1:
            response = response[start:end + 1]

        recommendations = json.loads(response)

        # 构建响应
        results = []
        for rec in recommendations:
            standard_id = rec.get("standard_id")
            standard = standard_library_manager.get_standard(standard_id)
            if standard:
                results.append(StandardRecommendationResponse(
                    standard_id=standard_id,
                    relevance_score=float(rec.get("relevance_score", 0)),
                    match_reason=rec.get("match_reason", ""),
                    standard=_standard_to_response(standard),
                ))

        # 按相关性排序
        results.sort(key=lambda x: x.relevance_score, reverse=True)

        logger.info(f"推荐 {len(results)} 条标准")
        return results

    except json.JSONDecodeError as e:
        logger.error(f"解析 LLM 响应失败: {e}")
        raise HTTPException(status_code=500, detail="LLM 响应解析失败")
    except Exception as e:
        logger.error(f"推荐标准失败: {e}")
        raise HTTPException(status_code=500, detail=f"推荐失败: {str(e)}")


class AIModifyStandardRequest(BaseModel):
    """AI 辅助修改标准请求"""
    instruction: str  # 用户的自然语言修改指令


class AIModifyStandardResponse(BaseModel):
    """AI 辅助修改标准响应"""
    category: str
    item: str
    description: str
    risk_level: str
    applicable_to: List[str]
    usage_instruction: Optional[str] = None
    modification_summary: str


# ---------- 特殊要求整合相关模型 ----------

class MergedStandardItem(BaseModel):
    """整合后的单条标准"""
    id: Optional[str] = None  # 原标准ID，新增时为null
    category: str
    item: str
    description: str
    risk_level: str
    change_type: str  # unchanged | modified | added | removed
    change_reason: Optional[str] = None  # 修改原因


class MergeSummary(BaseModel):
    """整合摘要"""
    total_original: int
    total_merged: int
    added_count: int
    modified_count: int
    removed_count: int
    unchanged_count: int


class MergeSpecialRequirementsRequest(BaseModel):
    """整合特殊要求请求"""
    standards: List[CreateStandardRequest]  # 基础标准列表
    special_requirements: str  # 用户输入的特殊要求
    our_party: str  # 我方身份
    material_type: str = "contract"  # 材料类型


class MergeSpecialRequirementsResponse(BaseModel):
    """整合特殊要求响应"""
    merged_standards: List[MergedStandardItem]
    summary: MergeSummary
    merge_notes: str  # 整合说明


class PresetTemplateInfo(BaseModel):
    """预设模板信息"""
    id: str
    name: str
    description: str
    material_type: str
    standard_count: int
    standards: List[StandardResponse]


@app.post("/api/standards/{standard_id}/ai-modify", response_model=AIModifyStandardResponse)
async def ai_modify_standard(standard_id: str, request: AIModifyStandardRequest):
    """
    使用 AI 辅助修改审核标准

    用户提供自然语言指令，AI 理解意图后生成修改建议。
    此接口只生成建议，不直接保存，用户需确认后再保存。
    """
    import json
    import re

    # 获取当前标准
    standard = standard_library_manager.get_standard(standard_id)
    if not standard:
        raise HTTPException(status_code=404, detail="标准不存在")

    if not request.instruction or not request.instruction.strip():
        raise HTTPException(status_code=400, detail="请输入修改要求")

    try:
        # 构建 Prompt
        messages = build_standard_modification_messages(
            standard=standard,
            user_instruction=request.instruction.strip(),
        )

        # 调用 LLM
        response = await llm_client.chat(messages, max_output_tokens=1000)

        # 解析 JSON 响应
        response = response.strip()
        # 移除可能的 markdown 代码块
        response = re.sub(r"```json\s*", "", response)
        response = re.sub(r"```\s*$", "", response)

        # 尝试找到 JSON 对象
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1:
            response = response[start:end + 1]

        modified = json.loads(response)

        # 验证必要字段
        required_fields = ["category", "item", "description", "risk_level", "applicable_to", "modification_summary"]
        for field in required_fields:
            if field not in modified:
                raise ValueError(f"响应缺少必要字段: {field}")

        # 验证 risk_level
        if modified["risk_level"] not in ["high", "medium", "low"]:
            modified["risk_level"] = standard.risk_level

        # 验证 applicable_to
        valid_types = {"contract", "marketing"}
        modified["applicable_to"] = [
            t for t in modified.get("applicable_to", [])
            if t in valid_types
        ]
        if not modified["applicable_to"]:
            modified["applicable_to"] = list(standard.applicable_to)

        logger.info(f"AI 辅助修改标准 {standard_id}: {modified.get('modification_summary', '')}")

        return AIModifyStandardResponse(
            category=modified["category"],
            item=modified["item"],
            description=modified["description"],
            risk_level=modified["risk_level"],
            applicable_to=modified["applicable_to"],
            usage_instruction=modified.get("usage_instruction"),
            modification_summary=modified["modification_summary"],
        )

    except json.JSONDecodeError as e:
        logger.error(f"解析 AI 修改响应失败: {e}")
        raise HTTPException(status_code=500, detail="AI 响应解析失败，请重试")
    except ValueError as e:
        logger.error(f"AI 修改响应验证失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"AI 辅助修改失败: {e}")
        raise HTTPException(status_code=500, detail=f"修改失败: {str(e)}")


# ==================== 预设模板 API ====================

@app.get("/api/preset-templates", response_model=List[PresetTemplateInfo])
async def get_preset_templates():
    """
    获取预设模板列表（从 templates 目录读取）

    预设模板是系统内置的标准模板，用户可以直接选择使用。
    """
    templates = []

    if TEMPLATES_DIR.exists():
        for f in TEMPLATES_DIR.iterdir():
            if f.suffix.lower() in {".xlsx", ".csv"}:
                try:
                    # 解析模板文件
                    standard_set = parse_standard_file(f)

                    # 根据文件名确定材料类型和描述
                    name = f.stem
                    if "contract" in name.lower() or "合同" in name:
                        material_type = "contract"
                        description = "通用合同审核标准，涵盖主体资格、权利义务、费用条款等关键审核要点"
                    elif "marketing" in name.lower() or "营销" in name:
                        material_type = "marketing"
                        description = "营销材料合规审核标准，涵盖广告法、消费者权益保护等合规要点"
                    else:
                        material_type = "contract"
                        description = "审核标准模板"

                    # 将标准转换为响应格式
                    standards_response = []
                    for s in standard_set.standards:
                        standards_response.append(StandardResponse(
                            id=s.id or "",
                            category=s.category,
                            item=s.item,
                            description=s.description,
                            risk_level=s.risk_level,
                            applicable_to=list(s.applicable_to),
                            usage_instruction=s.usage_instruction,
                            tags=list(s.tags) if s.tags else [],
                        ))

                    templates.append(PresetTemplateInfo(
                        id=name,
                        name=name,
                        description=description,
                        material_type=material_type,
                        standard_count=len(standard_set.standards),
                        standards=standards_response,
                    ))
                except Exception as e:
                    logger.error(f"解析模板文件失败 {f.name}: {e}")
                    continue

    return templates


@app.get("/api/preset-templates/{template_id}", response_model=PresetTemplateInfo)
async def get_preset_template(template_id: str):
    """获取单个预设模板的详细信息"""
    template_path = TEMPLATES_DIR / f"{template_id}.xlsx"
    if not template_path.exists():
        template_path = TEMPLATES_DIR / f"{template_id}.csv"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="模板不存在")

    try:
        standard_set = parse_standard_file(template_path)

        name = template_path.stem
        if "contract" in name.lower() or "合同" in name:
            material_type = "contract"
            description = "通用合同审核标准，涵盖主体资格、权利义务、费用条款等关键审核要点"
        elif "marketing" in name.lower() or "营销" in name:
            material_type = "marketing"
            description = "营销材料合规审核标准，涵盖广告法、消费者权益保护等合规要点"
        else:
            material_type = "contract"
            description = "审核标准模板"

        standards_response = []
        for s in standard_set.standards:
            standards_response.append(StandardResponse(
                id=s.id or "",
                category=s.category,
                item=s.item,
                description=s.description,
                risk_level=s.risk_level,
                applicable_to=list(s.applicable_to),
                usage_instruction=s.usage_instruction,
                tags=list(s.tags) if s.tags else [],
            ))

        return PresetTemplateInfo(
            id=name,
            name=name,
            description=description,
            material_type=material_type,
            standard_count=len(standard_set.standards),
            standards=standards_response,
        )
    except Exception as e:
        logger.error(f"获取模板失败 {template_id}: {e}")
        raise HTTPException(status_code=500, detail=f"获取模板失败: {str(e)}")


# ==================== 特殊要求整合 API ====================

@app.post("/api/standards/merge-special-requirements", response_model=MergeSpecialRequirementsResponse)
async def merge_special_requirements(request: MergeSpecialRequirementsRequest):
    """
    整合特殊要求到审核标准（使用 LLM）

    将用户输入的项目特殊要求整合到选定的基础标准中，
    LLM 会根据特殊要求对标准进行新增、修改或删除。
    """
    import json
    import re

    if not request.special_requirements or not request.special_requirements.strip():
        raise HTTPException(status_code=400, detail="请输入特殊要求")

    if not request.standards:
        raise HTTPException(status_code=400, detail="请选择基础标准")

    # 将请求中的标准转换为 ReviewStandard 对象
    base_standards = []
    for i, s in enumerate(request.standards):
        base_standards.append(ReviewStandard(
            id=f"std_{i+1}",
            category=s.category,
            item=s.item,
            description=s.description,
            risk_level=s.risk_level,
            applicable_to=s.applicable_to,
        ))

    try:
        # 构建 Prompt
        messages = build_merge_special_requirements_messages(
            standards=base_standards,
            special_requirements=request.special_requirements.strip(),
            our_party=request.our_party,
            material_type=request.material_type,
        )

        # 调用 LLM
        response = await llm_client.chat(messages, max_output_tokens=4000)

        # 解析 JSON 响应
        response = response.strip()
        # 移除可能的 markdown 代码块
        response = re.sub(r"```json\s*", "", response)
        response = re.sub(r"```\s*$", "", response)

        # 尝试找到 JSON 对象
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1:
            response = response[start:end + 1]

        result = json.loads(response)

        # 验证响应结构
        if "merged_standards" not in result:
            raise ValueError("响应缺少 merged_standards 字段")

        # 构建响应
        merged_standards = []
        for s in result.get("merged_standards", []):
            merged_standards.append(MergedStandardItem(
                id=s.get("id"),
                category=s.get("category", ""),
                item=s.get("item", ""),
                description=s.get("description", ""),
                risk_level=s.get("risk_level", "medium"),
                change_type=s.get("change_type", "unchanged"),
                change_reason=s.get("change_reason"),
            ))

        summary_data = result.get("summary", {})
        summary = MergeSummary(
            total_original=summary_data.get("total_original", len(request.standards)),
            total_merged=summary_data.get("total_merged", len(merged_standards)),
            added_count=summary_data.get("added_count", 0),
            modified_count=summary_data.get("modified_count", 0),
            removed_count=summary_data.get("removed_count", 0),
            unchanged_count=summary_data.get("unchanged_count", 0),
        )

        merge_notes = result.get("merge_notes", "已完成特殊要求整合")

        logger.info(f"整合特殊要求: {summary.modified_count} 修改, {summary.added_count} 新增, {summary.removed_count} 删除")

        return MergeSpecialRequirementsResponse(
            merged_standards=merged_standards,
            summary=summary,
            merge_notes=merge_notes,
        )

    except json.JSONDecodeError as e:
        logger.error(f"解析 LLM 响应失败: {e}")
        raise HTTPException(status_code=500, detail="AI 响应解析失败，请重试")
    except ValueError as e:
        logger.error(f"响应验证失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"整合特殊要求失败: {e}")
        raise HTTPException(status_code=500, detail=f"整合失败: {str(e)}")


# ==================== 业务条线管理 API ====================

class BusinessLineCreate(BaseModel):
    """创建业务条线请求"""
    name: str
    description: str = ""
    industry: str = ""
    language: str = "zh-CN"


class BusinessLineUpdate(BaseModel):
    """更新业务条线请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None


class BusinessContextCreate(BaseModel):
    """创建业务背景信息请求"""
    category: str  # core_focus, typical_risks, compliance, business_practices, negotiation_priorities
    item: str
    description: str
    priority: str = "medium"  # high, medium, low
    tags: List[str] = []


class BusinessContextUpdate(BaseModel):
    """更新业务背景信息请求"""
    category: Optional[str] = None
    item: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None


class BusinessContextBatchCreate(BaseModel):
    """批量创建业务背景信息请求"""
    contexts: List[BusinessContextCreate]


class BusinessLineResponse(BaseModel):
    """业务条线响应"""
    id: str
    name: str
    description: str
    industry: str
    is_preset: bool
    language: str
    context_count: int
    created_at: str
    updated_at: str


class BusinessContextResponse(BaseModel):
    """业务背景信息响应"""
    id: str
    business_line_id: str
    category: str
    item: str
    description: str
    priority: str
    tags: List[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BusinessLineDetailResponse(BusinessLineResponse):
    """业务条线详情响应（含背景信息）"""
    contexts: List[BusinessContextResponse]


@app.get("/api/business-lines", response_model=List[BusinessLineResponse])
async def list_business_lines(
    language: Optional[str] = Query(default=None),
    include_preset: bool = Query(default=True),
    user_id: str = Depends(get_current_user),
):
    """获取业务条线列表（需要登录）"""
    lines = business_library_manager.list_business_lines(
        user_id=user_id,
        language=language,
        include_preset=include_preset,
    )
    return [
        BusinessLineResponse(
            id=line.id,
            name=line.name,
            description=line.description,
            industry=line.industry,
            is_preset=line.is_preset,
            language=line.language,
            context_count=line.context_count,
            created_at=line.created_at.isoformat() if line.created_at else "",
            updated_at=line.updated_at.isoformat() if line.updated_at else "",
        )
        for line in lines
    ]


@app.get("/api/business-lines/{line_id}", response_model=BusinessLineDetailResponse)
async def get_business_line(
    line_id: str,
    user_id: str = Depends(get_current_user),
):
    """获取业务条线详情（含背景信息）"""
    line = business_library_manager.get_business_line(line_id)
    if not line:
        raise HTTPException(status_code=404, detail="业务条线不存在")

    return BusinessLineDetailResponse(
        id=line.id,
        name=line.name,
        description=line.description,
        industry=line.industry,
        is_preset=line.is_preset,
        language=line.language,
        context_count=line.context_count,
        created_at=line.created_at.isoformat() if line.created_at else "",
        updated_at=line.updated_at.isoformat() if line.updated_at else "",
        contexts=[
            BusinessContextResponse(
                id=ctx.id,
                business_line_id=ctx.business_line_id or "",
                category=ctx.category,
                item=ctx.item,
                description=ctx.description,
                priority=ctx.priority,
                tags=ctx.tags,
                created_at=ctx.created_at.isoformat() if ctx.created_at else None,
                updated_at=ctx.updated_at.isoformat() if ctx.updated_at else None,
            )
            for ctx in line.contexts
        ],
    )


@app.post("/api/business-lines", response_model=BusinessLineResponse)
async def create_business_line(
    request: BusinessLineCreate,
    user_id: str = Depends(get_current_user),
):
    """创建业务条线（需要登录）"""
    line = business_library_manager.create_business_line(
        name=request.name,
        user_id=user_id,
        description=request.description,
        industry=request.industry,
        is_preset=False,  # 用户创建的不能是预设
        language=request.language,
    )
    return BusinessLineResponse(
        id=line.id,
        name=line.name,
        description=line.description,
        industry=line.industry,
        is_preset=line.is_preset,
        language=line.language,
        context_count=0,
        created_at=line.created_at.isoformat() if line.created_at else "",
        updated_at=line.updated_at.isoformat() if line.updated_at else "",
    )


@app.put("/api/business-lines/{line_id}", response_model=BusinessLineResponse)
async def update_business_line(
    line_id: str,
    request: BusinessLineUpdate,
    user_id: str = Depends(get_current_user),
):
    """更新业务条线（需要登录）"""
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    line = business_library_manager.update_business_line(line_id, updates)
    if not line:
        raise HTTPException(status_code=404, detail="业务条线不存在或无法编辑")

    # 获取更新后的完整业务线信息（含 context_count）
    updated_line = business_library_manager.get_business_line(line_id)
    context_count = updated_line.context_count if updated_line else 0
    return BusinessLineResponse(
        id=line.id,
        name=line.name,
        description=line.description,
        industry=line.industry,
        is_preset=line.is_preset,
        language=line.language,
        context_count=context_count,
        created_at=line.created_at.isoformat() if line.created_at else "",
        updated_at=line.updated_at.isoformat() if line.updated_at else "",
    )


@app.delete("/api/business-lines/{line_id}")
async def delete_business_line(
    line_id: str,
    user_id: str = Depends(get_current_user),
):
    """删除业务条线（需要登录）"""
    success = business_library_manager.delete_business_line(line_id)
    if not success:
        raise HTTPException(status_code=404, detail="业务条线不存在或无法删除")
    return {"message": "删除成功"}


# ==================== 业务背景信息管理 API ====================

@app.get("/api/business-lines/{line_id}/contexts", response_model=List[BusinessContextResponse])
async def list_business_contexts(
    line_id: str,
    category: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user),
):
    """获取业务条线的背景信息列表"""
    contexts = business_library_manager.list_contexts(line_id, category=category)
    return [
        BusinessContextResponse(
            id=ctx.id,
            business_line_id=ctx.business_line_id or "",
            category=ctx.category,
            item=ctx.item,
            description=ctx.description,
            priority=ctx.priority,
            tags=ctx.tags,
            created_at=ctx.created_at.isoformat() if ctx.created_at else None,
            updated_at=ctx.updated_at.isoformat() if ctx.updated_at else None,
        )
        for ctx in contexts
    ]


@app.post("/api/business-lines/{line_id}/contexts", response_model=BusinessContextResponse)
async def add_business_context(
    line_id: str,
    request: BusinessContextCreate,
    user_id: str = Depends(get_current_user),
):
    """添加业务背景信息（需要登录）"""
    from src.contract_review.models import BusinessContext

    # 检查业务条线是否存在
    line = business_library_manager.get_business_line(line_id)
    if not line:
        raise HTTPException(status_code=404, detail="业务条线不存在")

    # 预设业务条线不能添加内容
    if line.is_preset:
        raise HTTPException(status_code=400, detail="预设业务条线不能添加内容")

    context = BusinessContext(
        business_line_id=line_id,
        category=request.category,
        item=request.item,
        description=request.description,
        priority=request.priority,
        tags=request.tags,
    )

    context_id = business_library_manager.add_context(context)
    created_ctx = business_library_manager.get_context(context_id)

    return BusinessContextResponse(
        id=created_ctx.id,
        business_line_id=created_ctx.business_line_id or "",
        category=created_ctx.category,
        item=created_ctx.item,
        description=created_ctx.description,
        priority=created_ctx.priority,
        tags=created_ctx.tags,
        created_at=created_ctx.created_at.isoformat() if created_ctx.created_at else None,
        updated_at=created_ctx.updated_at.isoformat() if created_ctx.updated_at else None,
    )


@app.post("/api/business-lines/{line_id}/contexts/batch")
async def add_business_contexts_batch(
    line_id: str,
    request: BusinessContextBatchCreate,
    user_id: str = Depends(get_current_user),
):
    """批量添加业务背景信息（需要登录）"""
    from src.contract_review.models import BusinessContext

    # 检查业务条线是否存在
    line = business_library_manager.get_business_line(line_id)
    if not line:
        raise HTTPException(status_code=404, detail="业务条线不存在")

    if line.is_preset:
        raise HTTPException(status_code=400, detail="预设业务条线不能添加内容")

    contexts = [
        BusinessContext(
            business_line_id=line_id,
            category=ctx.category,
            item=ctx.item,
            description=ctx.description,
            priority=ctx.priority,
            tags=ctx.tags,
        )
        for ctx in request.contexts
    ]

    ids = business_library_manager.add_contexts_batch(contexts)
    return {"message": f"成功添加 {len(ids)} 条背景信息", "ids": ids}


@app.put("/api/business-contexts/{context_id}", response_model=BusinessContextResponse)
async def update_business_context(
    context_id: str,
    request: BusinessContextUpdate,
    user_id: str = Depends(get_current_user),
):
    """更新业务背景信息（需要登录）"""
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    ctx = business_library_manager.update_context(context_id, updates)
    if not ctx:
        raise HTTPException(status_code=404, detail="背景信息不存在或无法编辑")

    return BusinessContextResponse(
        id=ctx.id,
        business_line_id=ctx.business_line_id or "",
        category=ctx.category,
        item=ctx.item,
        description=ctx.description,
        priority=ctx.priority,
        tags=ctx.tags,
        created_at=ctx.created_at.isoformat() if ctx.created_at else None,
        updated_at=ctx.updated_at.isoformat() if ctx.updated_at else None,
    )


@app.delete("/api/business-contexts/{context_id}")
async def delete_business_context(
    context_id: str,
    user_id: str = Depends(get_current_user),
):
    """删除业务背景信息（需要登录）"""
    success = business_library_manager.delete_context(context_id)
    if not success:
        raise HTTPException(status_code=404, detail="背景信息不存在或无法删除")
    return {"message": "删除成功"}


@app.get("/api/business-categories")
async def get_business_categories(
    language: str = Query(default="zh-CN"),
):
    """获取业务背景分类列表"""
    categories = business_library_manager.get_categories()
    display_names = business_library_manager.get_category_display_names(language)
    return [
        {"id": cat, "name": display_names.get(cat, cat)}
        for cat in categories
    ]


# ==================== 深度交互审阅模式 API ====================

class QuickReviewRequest(BaseModel):
    """快速初审请求"""
    llm_provider: str = "deepseek"


class UnifiedReviewRequest(BaseModel):
    """统一审阅请求

    支持两种模式：
    1. use_standards=False: AI 自主审阅（无预设标准）
    2. use_standards=True: 基于已上传的审核标准审阅
    """
    llm_provider: str = "deepseek"
    use_standards: bool = False  # 是否使用审核标准
    business_line_id: Optional[str] = None  # 业务条线 ID（可选）
    special_requirements: Optional[str] = None  # 本次特殊要求（可选）


class InteractiveItemResponse(BaseModel):
    """单个交互条目响应"""
    id: str
    item_id: str
    item_type: str
    risk_level: str = "medium"
    original_text: str
    current_suggestion: str
    chat_status: str
    message_count: int
    last_updated: Optional[str] = None


class InteractiveItemsResponse(BaseModel):
    """任务的所有交互条目响应"""
    task_id: str
    items: List[InteractiveItemResponse]
    summary: dict


class ChatRequest(BaseModel):
    """对话消息请求"""
    message: str
    llm_provider: str = "deepseek"


class ChatResponse(BaseModel):
    """对话响应"""
    item_id: str
    assistant_reply: str
    updated_suggestion: str
    chat_status: str
    messages: List[dict]


class CompleteItemRequest(BaseModel):
    """完成条目请求"""
    final_suggestion: Optional[str] = None


async def run_unified_review(
    task_id: str,
    user_id: str,
    llm_provider: str = "deepseek",
    use_standards: bool = False,
    business_line_id: Optional[str] = None,
    special_requirements: Optional[str] = None,
):
    """后台执行统一审阅任务

    支持两种模式：
    1. use_standards=False: AI 自主审阅
    2. use_standards=True: 基于审核标准审阅
    """
    task = task_manager.get_task(task_id)
    if not task:
        logger.error(f"任务不存在: {task_id}")
        return

    try:
        # 更新状态
        if use_standards:
            task.update_status("reviewing", "正在基于审核标准进行审阅...")
        else:
            task.update_status("reviewing", "正在进行 AI 自主审阅...")
        task.review_mode = "interactive"  # 统一使用交互模式
        task_manager.update_task(task)

        # 获取文档路径
        doc_storage_name = task.document_storage_name
        if not doc_storage_name:
            raise ValueError("文档未上传")

        # 下载文档
        doc_content = storage_manager.download_document(task_id, doc_storage_name)
        if not doc_content:
            raise ValueError("无法下载文档")

        # 保存临时文件
        import tempfile
        suffix = Path(doc_storage_name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(doc_content)
            tmp_path = tmp.name

        try:
            # 加载文档
            ocr_service = get_ocr_service()
            document = await load_document_async(tmp_path, ocr_service=ocr_service)

            # 加载审核标准（如果需要）
            review_standards = None
            if use_standards:
                std_storage_name = task.standard_storage_name
                if not std_storage_name:
                    raise ValueError("使用标准模式但未上传审核标准")

                std_content = storage_manager.download_standard(task_id, std_storage_name)
                if not std_content:
                    raise ValueError("无法下载审核标准文件")

                # 保存临时标准文件
                std_suffix = Path(std_storage_name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=std_suffix) as std_tmp:
                    std_tmp.write(std_content)
                    std_tmp_path = std_tmp.name

                try:
                    from src.contract_review.standard_parser import parse_standard_file
                    standard_set = parse_standard_file(std_tmp_path)
                    review_standards = standard_set.standards
                    logger.info(f"已加载 {len(review_standards)} 条审核标准")
                finally:
                    if os.path.exists(std_tmp_path):
                        os.remove(std_tmp_path)

            # 获取业务上下文（如果指定了业务条线）
            business_context = None
            if business_line_id:
                business_line = business_library_manager.get_business_line(business_line_id)
                if business_line:
                    business_context = {
                        "business_line_id": business_line.id,
                        "business_line_name": business_line.name,
                        "name": business_line.name,
                        "industry": business_line.industry,
                        "contexts": business_line.contexts,
                    }
                    logger.info(f"使用业务条线: {business_line.name}")

            # 进度回调
            def progress_callback(stage: str, percentage: int, message: str):
                task.update_progress(stage, percentage, message)
                task_manager.update_task(task)

            # 创建交互审阅引擎并执行统一审阅
            engine = InteractiveReviewEngine(settings, llm_provider=llm_provider)
            result = await engine.unified_review(
                document=document,
                our_party=task.our_party,
                material_type=task.material_type,
                task_id=task_id,
                language=getattr(task, 'language', 'zh-CN'),
                review_standards=review_standards,
                business_context=business_context,
                special_requirements=special_requirements,
                progress_callback=progress_callback,
            )

            # 保存结果
            storage_manager.save_result(result)

            # 为所有条目创建对话记录（支持后续对话打磨）
            interactive_manager = get_interactive_manager()
            modifications_data = [
                {
                    "id": mod.id,
                    "original_text": mod.original_text,
                    "suggested_text": mod.suggested_text,
                    "modification_reason": mod.modification_reason,
                    "priority": mod.priority,
                }
                for mod in result.modifications
            ]
            actions_data = [
                {
                    "id": action.id,
                    "action_type": action.action_type,
                    "description": action.description,
                    "urgency": action.urgency,
                }
                for action in result.actions
            ]
            interactive_manager.initialize_chats_for_task(
                task_id=task_id,
                modifications=modifications_data,
                actions=actions_data,
            )

            # 更新任务
            task.result = result
            task.update_status("completed", "审阅完成")
            task_manager.update_task(task)

            # 扣除配额
            quota_service = get_quota_service()
            await quota_service.deduct_quota(user_id, task_id=task_id)

            logger.info(f"任务 {task_id} 统一审阅完成，发现 {len(result.risks)} 个风险点")

        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except Exception as e:
        logger.error(f"任务 {task_id} 统一审阅失败: {e}")
        task.update_status("failed", str(e))
        task_manager.update_task(task)


@app.post("/api/tasks/{task_id}/unified-review")
async def start_unified_review(
    task_id: str,
    request: UnifiedReviewRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """
    启动统一审阅（支持可选标准）

    这是新的统一审阅入口，支持两种模式：
    - use_standards=False（默认）: AI 自主审阅，无需上传审核标准
    - use_standards=True: 基于已上传的审核标准进行审阅

    无论哪种模式，审阅完成后都会进入交互式结果页面，支持逐条对话打磨。
    """
    # 检查配额
    quota_service = get_quota_service()
    try:
        await quota_service.check_quota(user_id)
    except Exception as e:
        raise HTTPException(status_code=402, detail=str(e))

    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status == "reviewing":
        raise HTTPException(status_code=400, detail="任务正在审阅中")

    if not task.document_filename:
        raise HTTPException(status_code=400, detail="请先上传待审阅文档")

    # 如果使用标准模式，检查是否已上传标准
    if request.use_standards and not task.standard_filename:
        raise HTTPException(status_code=400, detail="使用标准模式需要先上传审核标准")

    # 验证业务条线（如果提供了）
    if request.business_line_id:
        business_line = business_library_manager.get_business_line(request.business_line_id)
        if not business_line:
            raise HTTPException(status_code=400, detail="指定的业务条线不存在")
        logger.info(f"任务 {task_id} 将使用业务条线: {business_line.name}")

    # 设置审阅模式
    task.review_mode = "interactive"
    task.update_status("reviewing", "正在启动审阅...")
    task.update_progress("analyzing", 0, "正在启动...")
    task_manager.update_task(task)

    # 启动后台任务
    background_tasks.add_task(
        run_unified_review,
        task_id,
        user_id,
        request.llm_provider,
        request.use_standards,
        request.business_line_id,
        request.special_requirements,
    )

    return {
        "message": "审阅已启动",
        "task_id": task_id,
        "mode": "with_standards" if request.use_standards else "ai_autonomous"
    }


async def run_quick_review(
    task_id: str,
    user_id: str,
    llm_provider: str = "deepseek",
):
    """后台执行快速初审任务"""
    task = task_manager.get_task(task_id)
    if not task:
        logger.error(f"任务不存在: {task_id}")
        return

    try:
        # 更新状态
        task.update_status("reviewing", "正在进行快速初审...")
        task.review_mode = "interactive"
        task_manager.update_task(task)

        # 获取文档路径
        doc_storage_name = task.document_storage_name
        if not doc_storage_name:
            raise ValueError("文档未上传")

        # 下载文档
        doc_content = storage_manager.download_document(task_id, doc_storage_name)
        if not doc_content:
            raise ValueError("无法下载文档")

        # 保存临时文件
        import tempfile
        suffix = Path(doc_storage_name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(doc_content)
            tmp_path = tmp.name

        try:
            # 加载文档
            ocr_service = get_ocr_service()
            document = await load_document_async(tmp_path, ocr_service=ocr_service)

            # 进度回调
            def progress_callback(stage: str, percentage: int, message: str):
                task.update_progress(stage, percentage, message)
                task_manager.update_task(task)

            # 创建交互审阅引擎
            engine = InteractiveReviewEngine(settings, llm_provider=llm_provider)

            # 执行快速初审
            result = await engine.quick_review(
                document=document,
                our_party=task.our_party,
                material_type=task.material_type,
                task_id=task_id,
                language=getattr(task, 'language', 'zh-CN'),
                progress_callback=progress_callback,
            )

            # 保存结果
            storage_manager.save_result(result)

            # 为所有条目创建对话记录
            interactive_manager = get_interactive_manager()
            modifications_data = [
                {
                    "id": mod.id,
                    "original_text": mod.original_text,
                    "suggested_text": mod.suggested_text,
                    "modification_reason": mod.modification_reason,
                    "priority": mod.priority,
                }
                for mod in result.modifications
            ]
            actions_data = [
                {
                    "id": action.id,
                    "action_type": action.action_type,
                    "description": action.description,
                    "urgency": action.urgency,
                }
                for action in result.actions
            ]
            interactive_manager.initialize_chats_for_task(
                task_id=task_id,
                modifications=modifications_data,
                actions=actions_data,
            )

            # 更新任务
            task.result = result
            task.update_status("completed", "快速初审完成")
            task_manager.update_task(task)

            # 扣除配额
            quota_service = get_quota_service()
            await quota_service.deduct_quota(user_id, task_id=task_id)

            logger.info(f"任务 {task_id} 快速初审完成")

        finally:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except Exception as e:
        logger.error(f"任务 {task_id} 快速初审失败: {e}")
        task.update_status("failed", str(e))
        task_manager.update_task(task)


@app.post("/api/tasks/{task_id}/quick-review")
async def start_quick_review(
    task_id: str,
    request: QuickReviewRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
):
    """
    启动快速初审（深度交互模式）

    无需预设审核标准，AI 自主发现问题。
    """
    # 检查配额
    quota_service = get_quota_service()
    try:
        await quota_service.check_quota(user_id)
    except Exception as e:
        raise HTTPException(status_code=402, detail=str(e))

    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status == "reviewing":
        raise HTTPException(status_code=400, detail="任务正在审阅中")

    if not task.document_filename:
        raise HTTPException(status_code=400, detail="请先上传待审阅文档")

    # 设置审阅模式
    task.review_mode = "interactive"
    task.update_status("reviewing", "正在启动快速初审...")
    task.update_progress("analyzing", 0, "正在启动...")
    task_manager.update_task(task)

    # 启动后台任务
    background_tasks.add_task(
        run_quick_review,
        task_id,
        user_id,
        request.llm_provider,
    )

    return {"message": "快速初审已启动", "task_id": task_id}


@app.get("/api/interactive/{task_id}/items", response_model=InteractiveItemsResponse)
async def get_interactive_items(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """获取任务的所有交互条目及对话状态"""
    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取审阅结果
    result = storage_manager.get_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="审阅结果不存在")

    # 获取对话记录
    interactive_manager = get_interactive_manager()
    chats = interactive_manager.get_chats_by_task(task_id)
    chat_map = {chat.item_id: chat for chat in chats}

    # 构建响应
    items = []

    # 处理修改建议
    for mod in result.modifications:
        chat = chat_map.get(mod.id)
        # 查找关联的风险点获取风险等级
        risk_level = "medium"
        for risk in result.risks:
            if risk.id == mod.risk_id:
                risk_level = risk.risk_level
                break

        items.append(InteractiveItemResponse(
            id=chat.id if chat else f"temp_{mod.id}",
            item_id=mod.id,
            item_type="modification",
            risk_level=risk_level,
            original_text=mod.original_text[:200] + ("..." if len(mod.original_text) > 200 else ""),
            current_suggestion=chat.current_suggestion if chat else mod.suggested_text,
            chat_status=chat.status if chat else "pending",
            message_count=len(chat.messages) if chat else 0,
            last_updated=chat.updated_at.isoformat() if chat else None,
        ))

    # 获取统计
    summary = interactive_manager.get_task_chat_summary(task_id)

    return InteractiveItemsResponse(
        task_id=task_id,
        items=items,
        summary=summary,
    )


@app.get("/api/interactive/{task_id}/items/{item_id}")
async def get_interactive_item_detail(
    task_id: str,
    item_id: str,
    user_id: str = Depends(get_current_user),
):
    """获取单个条目的详细信息和对话历史"""
    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取审阅结果
    result = storage_manager.get_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="审阅结果不存在")

    # 查找条目
    modification = None
    risk = None
    for mod in result.modifications:
        if mod.id == item_id:
            modification = mod
            # 查找关联的风险点
            for r in result.risks:
                if r.id == mod.risk_id:
                    risk = r
                    break
            break

    if not modification:
        raise HTTPException(status_code=404, detail="条目不存在")

    # 获取对话记录
    interactive_manager = get_interactive_manager()
    chat = interactive_manager.get_chat_by_item(task_id, item_id)

    return {
        "task_id": task_id,
        "item_id": item_id,
        "item_type": "modification",
        "original_text": modification.original_text,
        "current_suggestion": chat.current_suggestion if chat else modification.suggested_text,
        "modification_reason": modification.modification_reason,
        "priority": modification.priority,
        "risk": {
            "id": risk.id if risk else None,
            "level": risk.risk_level if risk else "medium",
            "type": risk.risk_type if risk else "",
            "description": risk.description if risk else "",
        } if risk else None,
        "chat": {
            "id": chat.id,
            "status": chat.status,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
                    "suggestion_snapshot": msg.suggestion_snapshot,
                }
                for msg in chat.messages
            ],
        } if chat else None,
    }


@app.post("/api/interactive/{task_id}/items/{item_id}/chat", response_model=ChatResponse)
async def chat_with_item(
    task_id: str,
    item_id: str,
    request: ChatRequest,
    user_id: str = Depends(get_current_user),
):
    """与特定条目进行对话，打磨修改建议"""
    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取审阅结果
    result = storage_manager.get_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="审阅结果不存在")

    # 查找条目
    modification = None
    risk = None
    for mod in result.modifications:
        if mod.id == item_id:
            modification = mod
            for r in result.risks:
                if r.id == mod.risk_id:
                    risk = r
                    break
            break

    if not modification:
        raise HTTPException(status_code=404, detail="条目不存在")

    # 获取或创建对话记录
    interactive_manager = get_interactive_manager()
    chat = interactive_manager.get_chat_by_item(task_id, item_id)

    if not chat:
        # 创建新的对话记录
        chat = interactive_manager.create_chat(
            task_id=task_id,
            item_id=item_id,
            item_type="modification",
            initial_suggestion=modification.suggested_text,
        )

    # 准备对话历史
    chat_history = [
        {"role": msg.role, "content": msg.content}
        for msg in chat.messages
    ]

    # 创建引擎并调用
    engine = InteractiveReviewEngine(settings, llm_provider=request.llm_provider)

    try:
        response = await engine.refine_item(
            original_clause=modification.original_text,
            current_suggestion=chat.current_suggestion or modification.suggested_text,
            risk_description=risk.description if risk else modification.modification_reason,
            user_message=request.message,
            chat_history=chat_history,
            document_summary="",  # TODO: 可以添加文档摘要
            language=getattr(task, 'language', 'zh-CN'),
        )
    except Exception as e:
        logger.error(f"对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"对话失败: {str(e)}")

    # 添加用户消息
    interactive_manager.add_message(
        chat_id=chat.id,
        role="user",
        content=request.message,
    )

    # 添加 AI 回复
    updated_chat = interactive_manager.add_message(
        chat_id=chat.id,
        role="assistant",
        content=response["assistant_reply"],
        suggestion_snapshot=response["updated_suggestion"],
    )

    # 同步更新 review_results 中的建议
    for mod in result.modifications:
        if mod.id == item_id:
            mod.suggested_text = response["updated_suggestion"]
            break
    storage_manager.save_result(result)

    # 构建响应
    return ChatResponse(
        item_id=item_id,
        assistant_reply=response["assistant_reply"],
        updated_suggestion=response["updated_suggestion"],
        chat_status=updated_chat.status if updated_chat else "in_progress",
        messages=[
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            for msg in (updated_chat.messages if updated_chat else [])
        ],
    )


@app.post("/api/interactive/{task_id}/items/{item_id}/chat/stream")
async def chat_with_item_stream(
    task_id: str,
    item_id: str,
    request: ChatRequest,
    user_id: str = Depends(get_current_user),
):
    """
    流式与特定条目进行对话（SSE）

    返回 Server-Sent Events 流，格式：
    - data: {"type": "chunk", "content": "文本片段"}
    - data: {"type": "suggestion", "content": "更新后的建议"}
    - data: {"type": "done", "content": "完整回复"}
    - data: {"type": "error", "content": "错误信息"}
    """
    import json as json_module

    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取审阅结果
    result = storage_manager.get_result(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="审阅结果不存在")

    # 查找条目
    modification = None
    risk = None
    for mod in result.modifications:
        if mod.id == item_id:
            modification = mod
            for r in result.risks:
                if r.id == mod.risk_id:
                    risk = r
                    break
            break

    if not modification:
        raise HTTPException(status_code=404, detail="条目不存在")

    # 获取或创建对话记录
    interactive_manager = get_interactive_manager()
    chat = interactive_manager.get_chat_by_item(task_id, item_id)

    if not chat:
        # 创建新的对话记录
        chat = interactive_manager.create_chat(
            task_id=task_id,
            item_id=item_id,
            item_type="modification",
            initial_suggestion=modification.suggested_text,
        )

    # 准备对话历史
    chat_history = [
        {"role": msg.role, "content": msg.content}
        for msg in chat.messages
    ]

    # 创建引擎
    engine = InteractiveReviewEngine(settings, llm_provider=request.llm_provider)

    async def event_generator():
        """生成 SSE 事件流"""
        full_response = ""
        updated_suggestion = ""

        try:
            async for event in engine.refine_item_stream(
                original_clause=modification.original_text,
                current_suggestion=chat.current_suggestion or modification.suggested_text,
                risk_description=risk.description if risk else modification.modification_reason,
                user_message=request.message,
                chat_history=chat_history,
                document_summary="",
                language=getattr(task, 'language', 'zh-CN'),
            ):
                event_type = event.get("type", "chunk")
                content = event.get("content", "")

                if event_type == "done":
                    full_response = content
                elif event_type == "suggestion":
                    updated_suggestion = content
                elif event_type == "error":
                    yield f"data: {json_module.dumps({'type': 'error', 'content': content}, ensure_ascii=False)}\n\n"
                    return

                yield f"data: {json_module.dumps({'type': event_type, 'content': content}, ensure_ascii=False)}\n\n"

            # 流式完成后，保存对话记录
            if full_response:
                # 添加用户消息
                interactive_manager.add_message(
                    chat_id=chat.id,
                    role="user",
                    content=request.message,
                )

                # 添加 AI 回复
                interactive_manager.add_message(
                    chat_id=chat.id,
                    role="assistant",
                    content=full_response,
                    suggestion_snapshot=updated_suggestion or chat.current_suggestion,
                )

                # 同步更新 review_results 中的建议
                if updated_suggestion:
                    for mod in result.modifications:
                        if mod.id == item_id:
                            mod.suggested_text = updated_suggestion
                            break
                    storage_manager.save_result(result)

        except Exception as e:
            logger.error(f"流式对话失败: {e}")
            yield f"data: {json_module.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )


@app.post("/api/interactive/{task_id}/items/{item_id}/complete")
async def complete_item(
    task_id: str,
    item_id: str,
    request: CompleteItemRequest,
    user_id: str = Depends(get_current_user),
):
    """标记条目为已完成"""
    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 获取对话记录
    interactive_manager = get_interactive_manager()
    chat = interactive_manager.get_chat_by_item(task_id, item_id)

    if not chat:
        raise HTTPException(status_code=404, detail="对话记录不存在")

    # 完成对话
    final_suggestion = request.final_suggestion or chat.current_suggestion
    success = interactive_manager.complete_chat(chat.id, final_suggestion)

    if not success:
        raise HTTPException(status_code=500, detail="完成条目失败")

    # 同步更新 review_results
    result = storage_manager.get_result(task_id)
    if result:
        for mod in result.modifications:
            if mod.id == item_id:
                mod.suggested_text = final_suggestion
                mod.user_confirmed = True
                break
        storage_manager.save_result(result)

    return {
        "item_id": item_id,
        "status": "completed",
        "final_suggestion": final_suggestion,
    }


# ==================== 文档内容 API ====================


class DocumentParagraph(BaseModel):
    """文档段落"""
    index: int
    text: str
    start_char: int
    end_char: int


class DocumentTextResponse(BaseModel):
    """文档全文响应"""
    task_id: str
    document_name: str
    text: str
    paragraphs: List[DocumentParagraph]


@app.get("/api/tasks/{task_id}/document/text", response_model=DocumentTextResponse)
async def get_document_text(
    task_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    获取文档的纯文本内容

    返回文档全文及段落信息，用于交互审阅页面左侧的文档展示。
    """
    # 验证任务
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务归属
    if USE_SUPABASE:
        task_user_id = task_manager.get_task_user_id(task_id)
        if task_user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问此任务")

    if not task.document_filename:
        raise HTTPException(status_code=404, detail="未找到文档")

    try:
        # 获取文档路径
        if USE_SUPABASE:
            doc_path = task_manager.get_document_path(task_id, user_id)
        else:
            doc_path = storage_manager.get_document_path(task_id)

        if not doc_path or not doc_path.exists():
            raise HTTPException(status_code=404, detail="文档文件不存在")

        # 使用已有的文档加载功能解析文档
        doc_text = await load_document_async(doc_path)

        if not doc_text:
            raise HTTPException(status_code=500, detail="无法解析文档内容")

        # 将文档拆分为段落
        paragraphs = []
        current_pos = 0

        # 按换行符分割，保留非空段落
        raw_paragraphs = doc_text.split('\n')

        for idx, para_text in enumerate(raw_paragraphs):
            # 跳过空段落
            stripped = para_text.strip()
            if not stripped:
                current_pos += len(para_text) + 1  # +1 for newline
                continue

            start_pos = current_pos
            end_pos = current_pos + len(para_text)

            paragraphs.append(DocumentParagraph(
                index=len(paragraphs),
                text=stripped,
                start_char=start_pos,
                end_char=end_pos,
            ))

            current_pos = end_pos + 1  # +1 for newline

        return DocumentTextResponse(
            task_id=task_id,
            document_name=task.document_filename,
            text=doc_text,
            paragraphs=paragraphs,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档内容失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取文档内容失败: {str(e)}")


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "llm_model": settings.llm.model,
    }


# ==================== 静态文件服务 ====================

# 挂载前端静态文件（生产环境）
frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
