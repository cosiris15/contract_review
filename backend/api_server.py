"""
FastAPI 服务入口

提供法务文本审阅系统的 RESTful API。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
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
from src.contract_review.prompts import (
    build_usage_instruction_messages,
    build_standard_recommendation_messages,
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
)

# 初始化管理器
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


# ==================== 请求/响应模型 ====================

class CreateTaskRequest(BaseModel):
    name: str
    our_party: str
    material_type: MaterialType = "contract"


class TaskResponse(BaseModel):
    id: str
    name: str
    our_party: str
    material_type: str
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
    standards: List[CreateStandardRequest]
    replace: bool = False  # 是否替换现有库


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


# ==================== 任务管理 API ====================

@app.post("/api/tasks", response_model=TaskResponse)
async def create_task(request: CreateTaskRequest):
    """创建审阅任务"""
    task = task_manager.create_task(
        name=request.name,
        our_party=request.our_party,
        material_type=request.material_type,
    )
    logger.info(f"创建任务: {task.id} - {task.name}")
    return TaskResponse.from_task(task)


@app.get("/api/tasks", response_model=List[TaskResponse])
async def list_tasks(limit: int = Query(default=100, ge=1, le=500)):
    """获取任务列表"""
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
async def delete_task(task_id: str):
    """删除任务"""
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
async def upload_document(task_id: str, file: UploadFile = File(...)):
    """上传待审阅文档"""
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
    task_manager.save_document(task_id, file.filename, content)

    logger.info(f"任务 {task_id} 上传文档: {file.filename}")
    return {"message": "上传成功", "filename": file.filename}


@app.post("/api/tasks/{task_id}/standard")
async def upload_standard(task_id: str, file: UploadFile = File(...)):
    """上传审核标准"""
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
    task_manager.save_standard(task_id, file.filename, content)

    logger.info(f"任务 {task_id} 上传审核标准: {file.filename}")
    return {"message": "上传成功", "filename": file.filename}


@app.post("/api/tasks/{task_id}/standard/template")
async def use_template(task_id: str, template_name: str = Query(...)):
    """使用默认模板作为审核标准"""
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
    task_manager.save_standard(task_id, template_path.name, content)

    # 更新任务
    task.standard_template = template_name
    task_manager.update_task(task)

    return {"message": "模板应用成功", "template": template_name}


# ==================== 审阅执行 API ====================

async def run_review(task_id: str):
    """后台执行审阅任务"""
    task = task_manager.get_task(task_id)
    if not task:
        return

    try:
        # 更新状态
        task.update_status("reviewing", "正在准备审阅...")
        task_manager.update_task(task)

        # 获取文档
        doc_path = task_manager.get_document_path(task_id)
        if not doc_path:
            raise ValueError("未上传文档")

        # 获取审核标准
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

        # 执行审阅
        engine = ReviewEngine(settings)
        result = await engine.review_document(
            document=document,
            standards=standard_set.standards,
            our_party=task.our_party,
            material_type=task.material_type,
            task_id=task_id,
            progress_callback=progress_callback,
        )

        # 保存结果
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
async def start_review(task_id: str, background_tasks: BackgroundTasks):
    """开始审阅"""
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

    # 启动后台任务
    background_tasks.add_task(run_review, task_id)

    task.update_status("reviewing", "审阅任务已启动")
    task.update_progress("analyzing", 0, "正在启动...")
    task_manager.update_task(task)

    return {"message": "审阅任务已启动"}


# ==================== 结果管理 API ====================

@app.get("/api/tasks/{task_id}/result")
async def get_result(task_id: str):
    """获取审阅结果"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

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
    storage_manager.update_result(task_dir, result)

    return {"message": "更新成功"}


@app.patch("/api/tasks/{task_id}/result/actions/{action_id}")
async def update_action(task_id: str, action_id: str, user_confirmed: bool):
    """更新行动建议状态"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_dir = settings.review.tasks_dir / task_id
    result = storage_manager.load_result(task_dir)

    if not result:
        raise HTTPException(status_code=404, detail="暂无审阅结果")

    # 查找并更新行动建议
    found = False
    for action in result.actions:
        if action.id == action_id:
            action.user_confirmed = user_confirmed
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="行动建议不存在")

    # 保存更新
    storage_manager.update_result(task_dir, result)

    return {"message": "更新成功"}


# ==================== 导出 API ====================

@app.get("/api/tasks/{task_id}/export/json")
async def export_json(task_id: str):
    """导出 JSON"""
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
async def export_redline(task_id: str, request: ExportRedlineRequest = None):
    """
    导出带修订标记的 Word 文档

    将用户确认的修改建议以 Track Changes 形式应用到原始文档。
    可选择将行动建议作为批注添加到对应风险点位置。
    只支持 .docx 格式的原始文档。
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查原始文档
    doc_path = task_manager.get_document_path(task_id)
    if not doc_path:
        raise HTTPException(status_code=400, detail="未找到原始文档")

    if doc_path.suffix.lower() != '.docx':
        raise HTTPException(
            status_code=400,
            detail=f"Redline 导出只支持 .docx 格式，当前文档格式为 {doc_path.suffix}"
        )

    # 获取审阅结果
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
    redline_result = generate_redline_document(
        docx_path=doc_path,
        modifications=modifications,
        author="AI审阅助手",
        filter_confirmed=filter_confirmed,
        actions=result.actions if include_comments else None,
        risks=result.risks if include_comments else None,
        include_comments=include_comments,
    )

    if not redline_result.success:
        error_msg = "; ".join(redline_result.skipped_reasons[:3])
        raise HTTPException(
            status_code=400,
            detail=f"生成 Redline 文档失败: {error_msg}"
        )

    # 生成文件名
    original_name = doc_path.stem
    filename = f"{original_name}_redline.docx"

    logger.info(
        f"任务 {task_id} 导出 Redline: 应用 {redline_result.applied_count} 条修改，"
        f"添加 {redline_result.comments_added} 条批注，"
        f"跳过 {redline_result.skipped_count + redline_result.comments_skipped} 条"
    )

    return Response(
        content=redline_result.document_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Redline-Applied": str(redline_result.applied_count),
            "X-Redline-Skipped": str(redline_result.skipped_count),
            "X-Comments-Added": str(redline_result.comments_added),
            "X-Comments-Skipped": str(redline_result.comments_skipped),
        },
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

    # 检查有多少行动建议可以作为批注（有关联风险点且风险点有原文）
    commentable_actions = 0
    if result.actions and result.risks:
        risk_map = {r.id: r for r in result.risks}
        for action in result.actions:
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
    """将预览的标准保存到标准库"""
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

    imported_count, warnings = standard_library_manager.import_from_parsed_standards(
        standards,
        replace=request.replace,
    )

    logger.info(f"保存到标准库: {imported_count} 条")

    return {
        "message": f"成功保存 {imported_count} 条标准到标准库",
        "imported_count": imported_count,
        "warnings": warnings,
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
