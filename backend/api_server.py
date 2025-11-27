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
    ReviewTask,
)
from src.contract_review.result_formatter import ResultFormatter, generate_summary_report
from src.contract_review.review_engine import ReviewEngine
from src.contract_review.standard_parser import parse_standard_file
from src.contract_review.storage import StorageManager
from src.contract_review.tasks import TaskManager

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
