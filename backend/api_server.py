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
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.contract_review.config import get_settings, load_settings
from src.contract_review.document_loader import load_document
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
from src.contract_review.redline_generator import generate_redline_document
from src.contract_review.standard_parser import parse_standard_file
from src.contract_review.storage import StorageManager
from src.contract_review.tasks import TaskManager
from src.contract_review.supabase_tasks import SupabaseTaskManager
from src.contract_review.supabase_storage import SupabaseStorageManager
from src.contract_review.prompts import (
    build_usage_instruction_messages,
    build_standard_recommendation_messages,
    build_standard_modification_messages,
    build_merge_special_requirements_messages,
    build_collection_recommendation_messages,
)
from src.contract_review.llm_client import LLMClient

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
# 检查是否配置了 Supabase，如果是则使用 Supabase 版本
USE_SUPABASE = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

if USE_SUPABASE:
    logger.info("使用 Supabase 存储后端")
    task_manager = SupabaseTaskManager()
    storage_manager = SupabaseStorageManager()
else:
    logger.info("使用本地文件存储后端")
    task_manager = TaskManager(settings.review.tasks_dir)
    storage_manager = StorageManager(settings.review.tasks_dir)

formatter = ResultFormatter()

# 标准库目录
STANDARD_LIBRARY_DIR = Path(settings.review.tasks_dir).parent / "data" / "standard_library"
standard_library_manager = StandardLibraryManager(STANDARD_LIBRARY_DIR)

# LLM 客户端
llm_client = LLMClient(settings.llm)

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
    allowed = {".md", ".txt", ".docx", ".pdf"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。支持的格式: {', '.join(allowed)}",
        )

    content = await file.read()
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

async def run_review(task_id: str, user_id: str, llm_provider: str = "deepseek"):
    """后台执行审阅任务

    Args:
        task_id: 任务 ID
        user_id: 用户 ID（用于 Supabase 存储路径）
        llm_provider: LLM 提供者，可选 "deepseek" 或 "gemini"
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

        # 加载文档
        document = load_document(doc_path)

        # 解析审核标准
        standard_set = parse_standard_file(std_path)

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
    user_id: str = Depends(get_current_user),
):
    """开始审阅（需要登录）

    Args:
        task_id: 任务 ID
        llm_provider: LLM 提供者，可选 "deepseek"（初级）或 "gemini"（高级）
    """
    print(f"User {user_id} is starting review for task {task_id}...")
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

    # 启动后台任务，传递 user_id 和 llm_provider 参数
    background_tasks.add_task(run_review, task_id, user_id, llm_provider)

    task.update_status("reviewing", "审阅任务已启动")
    task.update_progress("analyzing", 0, "正在启动...")
    task_manager.update_task(task)

    return {"message": "审阅任务已启动"}


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
async def preview_redline(task_id: str):
    """
    预览 Redline 导出信息

    返回可以导出的修改建议数量、行动建议数量和状态。
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查原始文档格式
    doc_path = task_manager.get_document_path(task_id)
    can_export = doc_path and doc_path.suffix.lower() == '.docx'

    # 获取审阅结果
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

@app.post("/api/standards/generate-usage-instruction")
async def generate_usage_instruction(request: GenerateUsageInstructionRequest):
    """为指定标准生成适用说明（使用 LLM）"""
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

    try:
        # 构建 Prompt
        messages = build_standard_recommendation_messages(
            document_text=request.document_text,
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
