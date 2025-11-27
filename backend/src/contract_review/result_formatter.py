"""
结果格式化器

将审阅结果格式化为不同的输出格式：
- JSON：中间结果，便于存储和编辑
- Excel：单 Sheet 合并格式，便于查看和导出
- CSV：文本表格格式
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from .models import ReviewResult


class ResultFormatter:
    """结果格式化器"""

    # Excel 导出的列定义
    EXCEL_COLUMNS = [
        ("序号", "index"),
        ("风险等级", "risk_level"),
        ("风险类型", "risk_type"),
        ("风险描述", "description"),
        ("判定理由", "reason"),
        ("原文摘录", "original_text"),
        ("当前文本", "current_text"),
        ("建议文本", "suggested_text"),
        ("修改优先级", "priority"),
        ("行动建议", "actions"),
        ("用户确认", "user_confirmed"),
    ]

    # 风险等级映射
    RISK_LEVEL_MAP = {
        "high": "高",
        "medium": "中",
        "low": "低",
    }

    # 修改优先级映射
    PRIORITY_MAP = {
        "must": "必须",
        "should": "应该",
        "may": "可以",
    }

    def to_json(self, result: ReviewResult, indent: int = 2) -> str:
        """
        将审阅结果转换为 JSON 字符串

        Args:
            result: 审阅结果
            indent: 缩进空格数

        Returns:
            JSON 字符串
        """
        return result.model_dump_json(indent=indent)

    def to_dict(self, result: ReviewResult) -> Dict[str, Any]:
        """将审阅结果转换为字典"""
        return result.model_dump(mode="json")

    def to_dataframe(self, result: ReviewResult) -> pd.DataFrame:
        """
        将审阅结果转换为 pandas DataFrame（单 Sheet 合并格式）

        每行对应一个风险点及其相关的修改建议和行动建议
        """
        rows = []

        # 建立风险点 ID 到修改建议的映射
        modifications_map = {m.risk_id: m for m in result.modifications}

        # 建立风险点 ID 到行动建议的映射
        actions_map: Dict[str, List[str]] = {}
        for action in result.actions:
            for risk_id in action.related_risk_ids:
                if risk_id not in actions_map:
                    actions_map[risk_id] = []
                actions_map[risk_id].append(
                    f"[{action.action_type}] {action.description}"
                )

        for i, risk in enumerate(result.risks, start=1):
            modification = modifications_map.get(risk.id)
            related_actions = actions_map.get(risk.id, [])

            row = {
                "index": i,
                "risk_level": self.RISK_LEVEL_MAP.get(risk.risk_level, risk.risk_level),
                "risk_type": risk.risk_type,
                "description": risk.description,
                "reason": risk.reason,
                "original_text": risk.location.original_text if risk.location else "",
                "current_text": modification.original_text if modification else "",
                "suggested_text": modification.suggested_text if modification else "",
                "priority": self.PRIORITY_MAP.get(
                    modification.priority, modification.priority
                ) if modification else "",
                "actions": "\n".join(related_actions),
                "user_confirmed": "是" if (modification and modification.user_confirmed) else "否",
            }
            rows.append(row)

        # 处理没有关联到风险点的行动建议
        standalone_actions = []
        associated_risk_ids = set()
        for action in result.actions:
            associated_risk_ids.update(action.related_risk_ids)

        for action in result.actions:
            # 检查是否有独立的行动建议（关联到不存在的风险点 ID）
            for risk_id in action.related_risk_ids:
                if risk_id not in [r.id for r in result.risks]:
                    standalone_actions.append(action)
                    break

        # 添加独立的行动建议行
        for i, action in enumerate(standalone_actions, start=len(rows) + 1):
            row = {
                "index": i,
                "risk_level": "",
                "risk_type": "",
                "description": "",
                "reason": "",
                "original_text": "",
                "current_text": "",
                "suggested_text": "",
                "priority": "",
                "actions": f"[{action.action_type}] {action.description}",
                "user_confirmed": "是" if action.user_confirmed else "否",
            }
            rows.append(row)

        # 创建 DataFrame
        df = pd.DataFrame(rows)

        # 按照定义的列顺序重新排列
        column_order = [col[1] for col in self.EXCEL_COLUMNS]
        df = df[column_order]

        # 重命名列为中文
        column_names = {col[1]: col[0] for col in self.EXCEL_COLUMNS}
        df = df.rename(columns=column_names)

        return df

    def to_excel(self, result: ReviewResult) -> bytes:
        """
        将审阅结果转换为 Excel 文件

        Args:
            result: 审阅结果

        Returns:
            Excel 文件的字节内容
        """
        df = self.to_dataframe(result)

        # 创建 Excel 写入器
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="审阅结果", index=False)

            # 获取工作表进行格式调整
            worksheet = writer.sheets["审阅结果"]

            # 调整列宽
            column_widths = {
                "A": 6,   # 序号
                "B": 10,  # 风险等级
                "C": 12,  # 风险类型
                "D": 30,  # 风险描述
                "E": 30,  # 判定理由
                "F": 35,  # 原文摘录
                "G": 35,  # 当前文本
                "H": 35,  # 建议文本
                "I": 12,  # 修改优先级
                "J": 35,  # 行动建议
                "K": 10,  # 用户确认
            }

            for col, width in column_widths.items():
                worksheet.column_dimensions[col].width = width

        output.seek(0)
        return output.read()

    def to_csv(self, result: ReviewResult, encoding: str = "utf-8-sig") -> bytes:
        """
        将审阅结果转换为 CSV 文件

        Args:
            result: 审阅结果
            encoding: 字符编码（默认 utf-8-sig 以支持 Excel 打开）

        Returns:
            CSV 文件的字节内容
        """
        df = self.to_dataframe(result)
        return df.to_csv(index=False, encoding=encoding).encode(encoding)

    def save_json(self, result: ReviewResult, file_path: Path) -> None:
        """保存 JSON 文件"""
        file_path.write_text(self.to_json(result), encoding="utf-8")

    def save_excel(self, result: ReviewResult, file_path: Path) -> None:
        """保存 Excel 文件"""
        file_path.write_bytes(self.to_excel(result))

    def save_csv(self, result: ReviewResult, file_path: Path) -> None:
        """保存 CSV 文件"""
        file_path.write_bytes(self.to_csv(result))


# 创建摘要报告
def generate_summary_report(result: ReviewResult) -> str:
    """
    生成审阅结果的文本摘要报告

    Args:
        result: 审阅结果

    Returns:
        Markdown 格式的摘要报告
    """
    summary = result.summary

    report = f"""# 法务审阅报告

## 基本信息
- **文档名称**: {result.document_name}
- **材料类型**: {"合同" if result.material_type == "contract" else "营销材料"}
- **我方身份**: {result.our_party}
- **审阅时间**: {result.reviewed_at.strftime("%Y-%m-%d %H:%M:%S")}
- **审核标准**: {result.review_standards_used}

## 风险统计
| 指标 | 数量 |
|------|------|
| 总风险数 | {summary.total_risks} |
| 高风险 | {summary.high_risks} |
| 中风险 | {summary.medium_risks} |
| 低风险 | {summary.low_risks} |

## 修改建议统计
| 指标 | 数量 |
|------|------|
| 总修改建议 | {summary.total_modifications} |
| 必须修改 | {summary.must_modify} |
| 应该修改 | {summary.should_modify} |
| 可以修改 | {summary.may_modify} |

## 行动建议统计
| 指标 | 数量 |
|------|------|
| 总行动建议 | {summary.total_actions} |
| 立即处理 | {summary.immediate_actions} |

"""

    # 添加高风险点详情
    if summary.high_risks > 0:
        report += "## 高风险点详情\n\n"
        for i, risk in enumerate(result.risks, start=1):
            if risk.risk_level == "high":
                report += f"### {i}. {risk.risk_type}\n"
                report += f"- **描述**: {risk.description}\n"
                report += f"- **理由**: {risk.reason}\n"
                if risk.location and risk.location.original_text:
                    report += f"- **原文**: {risk.location.original_text[:200]}...\n"
                report += "\n"

    return report


# 默认格式化器实例
formatter = ResultFormatter()
