"""
Redline 文档生成器

将已确认的修改建议应用到 Word 文档，生成带修订追踪标记的文档。
使用 OpenXML 格式直接操作 Word 文档的 XML 结构。
"""

from __future__ import annotations

import copy
import logging
import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from lxml import etree

from .models import ModificationSuggestion, ActionRecommendation, RiskPoint

logger = logging.getLogger(__name__)

# OpenXML 命名空间
NAMESPACES = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'mc': 'http://schemas.openxmlformats.org/markup-compatibility/2006',
}

# 注册命名空间前缀
for prefix, uri in NAMESPACES.items():
    etree.register_namespace(prefix, uri)


@dataclass
class TextRun:
    """文本 run 元素信息"""
    element: etree._Element  # <w:r> 元素
    text_element: etree._Element  # <w:t> 元素
    text: str  # 文本内容
    start_pos: int  # 在完整文本中的起始位置
    end_pos: int  # 在完整文本中的结束位置


@dataclass
class TextMatch:
    """文本匹配结果"""
    runs: List[TextRun]  # 涉及的 run 元素列表
    start_offset: int  # 在第一个 run 中的起始偏移
    end_offset: int  # 在最后一个 run 中的结束偏移
    matched_text: str  # 实际匹配到的文本


@dataclass
class RedlineResult:
    """Redline 处理结果"""
    success: bool
    document_bytes: Optional[bytes] = None
    applied_count: int = 0
    skipped_count: int = 0
    skipped_reasons: List[str] = None
    # 批注相关
    comments_added: int = 0
    comments_skipped: int = 0

    def __post_init__(self):
        if self.skipped_reasons is None:
            self.skipped_reasons = []


class RedlineGenerator:
    """
    Redline 文档生成器

    将修改建议以修订追踪形式应用到 Word 文档。
    """

    def __init__(self, docx_path: Path):
        """
        初始化生成器

        Args:
            docx_path: 原始 Word 文档路径
        """
        self.docx_path = docx_path
        self.zip_buffer: Optional[BytesIO] = None
        self.document_xml: Optional[etree._Element] = None
        self.settings_xml: Optional[etree._Element] = None
        self.comments_xml: Optional[etree._Element] = None
        self.content_types_xml: Optional[etree._Element] = None
        self.rels_xml: Optional[etree._Element] = None
        self._file_contents: Dict[str, bytes] = {}
        self._next_comment_id: int = 0
        self._comments_added: bool = False

        self._load_document()

    def _load_document(self) -> None:
        """加载并解析 Word 文档"""
        with zipfile.ZipFile(self.docx_path, 'r') as zf:
            # 读取所有文件内容
            for name in zf.namelist():
                self._file_contents[name] = zf.read(name)

            # 解析主文档
            if 'word/document.xml' in self._file_contents:
                self.document_xml = etree.fromstring(
                    self._file_contents['word/document.xml']
                )
            else:
                raise ValueError("无效的 Word 文档：缺少 document.xml")

            # 解析设置文件
            if 'word/settings.xml' in self._file_contents:
                self.settings_xml = etree.fromstring(
                    self._file_contents['word/settings.xml']
                )

            # 解析已有的批注文件（如果存在）
            if 'word/comments.xml' in self._file_contents:
                self.comments_xml = etree.fromstring(
                    self._file_contents['word/comments.xml']
                )
                # 找出现有最大的 comment id
                for comment in self.comments_xml.findall('.//w:comment', NAMESPACES):
                    cid = comment.get(f"{{{NAMESPACES['w']}}}id")
                    if cid and cid.isdigit():
                        self._next_comment_id = max(self._next_comment_id, int(cid) + 1)

            # 解析 Content_Types
            if '[Content_Types].xml' in self._file_contents:
                self.content_types_xml = etree.fromstring(
                    self._file_contents['[Content_Types].xml']
                )

            # 解析文档关系文件
            if 'word/_rels/document.xml.rels' in self._file_contents:
                self.rels_xml = etree.fromstring(
                    self._file_contents['word/_rels/document.xml.rels']
                )

    def apply_modifications(
        self,
        modifications: List[ModificationSuggestion],
        author: str = "AI审阅助手",
        filter_confirmed: bool = True,
    ) -> RedlineResult:
        """
        应用修改建议，生成带修订标记的文档

        Args:
            modifications: 修改建议列表
            author: 修订作者名称
            filter_confirmed: 是否只处理已确认的修改

        Returns:
            RedlineResult 包含处理结果和文档字节
        """
        # 筛选要处理的修改
        if filter_confirmed:
            to_apply = [m for m in modifications if m.user_confirmed]
        else:
            to_apply = modifications

        if not to_apply:
            return RedlineResult(
                success=False,
                applied_count=0,
                skipped_count=len(modifications),
                skipped_reasons=["没有已确认的修改建议"]
            )

        applied_count = 0
        skipped_reasons = []

        # 获取当前时间戳
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        # 处理每条修改
        for mod in to_apply:
            original = mod.original_text.strip()
            # 优先使用用户修改的文本
            new_text = (mod.user_modified_text or mod.suggested_text).strip()

            if not original:
                skipped_reasons.append(f"修改 {mod.id}: 原文为空")
                continue

            if original == new_text:
                skipped_reasons.append(f"修改 {mod.id}: 原文与新文本相同")
                continue

            # 在文档中查找并替换
            match = self._find_text_in_document(original)

            if match:
                try:
                    self._apply_revision(match, new_text, author, timestamp)
                    applied_count += 1
                    logger.info(f"成功应用修改 {mod.id}: '{original[:30]}...'")
                except Exception as e:
                    logger.error(f"应用修改 {mod.id} 失败: {e}")
                    skipped_reasons.append(f"修改 {mod.id}: 应用失败 - {str(e)}")
            else:
                logger.warning(f"未找到原文: '{original[:50]}...'")
                skipped_reasons.append(f"修改 {mod.id}: 未在文档中找到原文")

        # 启用修订追踪
        self._enable_track_revisions()

        # 生成输出文档
        output_bytes = self._save_document()

        return RedlineResult(
            success=applied_count > 0,
            document_bytes=output_bytes,
            applied_count=applied_count,
            skipped_count=len(to_apply) - applied_count,
            skipped_reasons=skipped_reasons,
        )

    def _find_text_in_document(self, target: str) -> Optional[TextMatch]:
        """
        在文档中查找目标文本

        Args:
            target: 要查找的文本

        Returns:
            TextMatch 如果找到，否则 None
        """
        # 规范化目标文本
        normalized_target = self._normalize_text(target)

        # 遍历所有段落
        body = self.document_xml.find('.//w:body', NAMESPACES)
        if body is None:
            return None

        # 查找所有段落和表格单元格中的文本
        for paragraph in body.iter(f"{{{NAMESPACES['w']}}}p"):
            match = self._find_in_paragraph(paragraph, normalized_target)
            if match:
                return match

        return None

    def _find_in_paragraph(
        self, paragraph: etree._Element, target: str
    ) -> Optional[TextMatch]:
        """
        在段落中查找目标文本

        Args:
            paragraph: 段落元素 <w:p>
            target: 规范化后的目标文本

        Returns:
            TextMatch 如果找到，否则 None
        """
        # 收集段落中的所有文本 run
        runs: List[TextRun] = []
        full_text = ""

        for run in paragraph.findall('.//w:r', NAMESPACES):
            # 跳过已经是修订内容的 run
            parent = run.getparent()
            if parent is not None:
                parent_tag = etree.QName(parent.tag).localname
                if parent_tag in ('ins', 'del'):
                    continue

            # 获取文本元素
            for t_elem in run.findall('w:t', NAMESPACES):
                text = t_elem.text or ""
                if text:
                    start_pos = len(full_text)
                    full_text += text
                    runs.append(TextRun(
                        element=run,
                        text_element=t_elem,
                        text=text,
                        start_pos=start_pos,
                        end_pos=len(full_text),
                    ))

        if not runs:
            return None

        # 规范化完整文本并查找
        normalized_full = self._normalize_text(full_text)

        # 尝试精确匹配
        idx = normalized_full.find(target)
        if idx == -1:
            # 尝试模糊匹配（忽略多余空格）
            idx = self._fuzzy_find(normalized_full, target)

        if idx == -1:
            return None

        # 找到匹配，确定涉及的 runs
        target_len = len(target)
        match_end = idx + target_len

        # 建立规范化文本到原始文本的位置映射
        # 由于规范化可能改变长度，需要反向映射
        orig_start, orig_end = self._map_normalized_to_original(
            full_text, normalized_full, idx, match_end
        )

        # 找出涉及的 runs
        matched_runs = []
        for run in runs:
            if run.end_pos > orig_start and run.start_pos < orig_end:
                matched_runs.append(run)

        if not matched_runs:
            return None

        # 计算偏移量
        start_offset = orig_start - matched_runs[0].start_pos
        end_offset = orig_end - matched_runs[-1].start_pos

        return TextMatch(
            runs=matched_runs,
            start_offset=max(0, start_offset),
            end_offset=min(len(matched_runs[-1].text), end_offset),
            matched_text=full_text[orig_start:orig_end],
        )

    def _normalize_text(self, text: str) -> str:
        """
        规范化文本以便比较

        - 合并多个空白字符为单个空格
        - 去除首尾空白
        - 统一换行符
        """
        # 替换各种空白字符
        text = re.sub(r'[\s\u00a0\u3000]+', ' ', text)
        return text.strip()

    def _fuzzy_find(self, haystack: str, needle: str) -> int:
        """
        模糊查找，处理空格差异

        Returns:
            找到的位置索引，未找到返回 -1
        """
        # 移除所有空格后比较
        haystack_no_space = re.sub(r'\s+', '', haystack)
        needle_no_space = re.sub(r'\s+', '', needle)

        idx_no_space = haystack_no_space.find(needle_no_space)
        if idx_no_space == -1:
            return -1

        # 将无空格位置映射回原始位置
        char_count = 0
        for i, c in enumerate(haystack):
            if not c.isspace():
                if char_count == idx_no_space:
                    return i
                char_count += 1

        return -1

    def _map_normalized_to_original(
        self, original: str, normalized: str, norm_start: int, norm_end: int
    ) -> Tuple[int, int]:
        """
        将规范化文本中的位置映射回原始文本

        简化实现：假设规范化主要是合并空格
        """
        # 简单情况：长度相同
        if len(original) == len(normalized):
            return norm_start, norm_end

        # 构建映射表
        orig_to_norm = []
        norm_pos = 0
        in_space_run = False

        for i, c in enumerate(original):
            if c.isspace():
                if not in_space_run and norm_pos < len(normalized):
                    orig_to_norm.append(norm_pos)
                    norm_pos += 1
                    in_space_run = True
                else:
                    orig_to_norm.append(norm_pos - 1 if norm_pos > 0 else 0)
            else:
                in_space_run = False
                orig_to_norm.append(norm_pos)
                norm_pos += 1

        # 反向查找原始位置
        orig_start = 0
        orig_end = len(original)

        for i, norm_i in enumerate(orig_to_norm):
            if norm_i >= norm_start and orig_start == 0:
                orig_start = i
            if norm_i >= norm_end:
                orig_end = i
                break

        return orig_start, orig_end

    def _apply_revision(
        self,
        match: TextMatch,
        new_text: str,
        author: str,
        timestamp: str,
    ) -> None:
        """
        应用修订标记到匹配的文本

        Args:
            match: 文本匹配结果
            new_text: 新文本
            author: 作者
            timestamp: 时间戳
        """
        w = NAMESPACES['w']

        if len(match.runs) == 1:
            # 简单情况：文本在单个 run 中
            self._apply_single_run_revision(
                match.runs[0], match.start_offset, match.end_offset,
                new_text, author, timestamp
            )
        else:
            # 复杂情况：文本跨多个 run
            self._apply_multi_run_revision(
                match, new_text, author, timestamp
            )

    def _apply_single_run_revision(
        self,
        run: TextRun,
        start_offset: int,
        end_offset: int,
        new_text: str,
        author: str,
        timestamp: str,
    ) -> None:
        """
        在单个 run 中应用修订
        """
        w = NAMESPACES['w']
        original_text = run.text

        # 分割文本：前缀 + 被替换部分 + 后缀
        prefix = original_text[:start_offset]
        replaced = original_text[start_offset:end_offset]
        suffix = original_text[end_offset:]

        # 获取 run 的格式属性
        rPr = run.element.find('w:rPr', NAMESPACES)
        rPr_copy = copy.deepcopy(rPr) if rPr is not None else None

        # 获取父元素和位置
        parent = run.element.getparent()
        run_index = list(parent).index(run.element)

        # 移除原始 run
        parent.remove(run.element)

        insert_index = run_index

        # 1. 添加前缀（如果有）
        if prefix:
            prefix_run = self._create_text_run(prefix, rPr_copy)
            parent.insert(insert_index, prefix_run)
            insert_index += 1

        # 2. 添加删除标记
        del_elem = etree.Element(f"{{{w}}}del")
        del_elem.set(f"{{{w}}}author", author)
        del_elem.set(f"{{{w}}}date", timestamp)
        del_run = self._create_text_run(replaced, rPr_copy, is_delete=True)
        del_elem.append(del_run)
        parent.insert(insert_index, del_elem)
        insert_index += 1

        # 3. 添加插入标记
        ins_elem = etree.Element(f"{{{w}}}ins")
        ins_elem.set(f"{{{w}}}author", author)
        ins_elem.set(f"{{{w}}}date", timestamp)
        ins_run = self._create_text_run(new_text, rPr_copy)
        ins_elem.append(ins_run)
        parent.insert(insert_index, ins_elem)
        insert_index += 1

        # 4. 添加后缀（如果有）
        if suffix:
            suffix_run = self._create_text_run(suffix, rPr_copy)
            parent.insert(insert_index, suffix_run)

    def _apply_multi_run_revision(
        self,
        match: TextMatch,
        new_text: str,
        author: str,
        timestamp: str,
    ) -> None:
        """
        跨多个 run 应用修订
        """
        w = NAMESPACES['w']
        runs = match.runs

        # 获取第一个 run 的父元素
        first_run = runs[0]
        parent = first_run.element.getparent()
        first_index = list(parent).index(first_run.element)

        # 收集所有被替换文本的格式（使用第一个 run 的格式）
        rPr = first_run.element.find('w:rPr', NAMESPACES)
        rPr_copy = copy.deepcopy(rPr) if rPr is not None else None

        # 处理第一个 run 的前缀
        first_text = first_run.text
        prefix = first_text[:match.start_offset]
        first_replaced = first_text[match.start_offset:]

        # 处理最后一个 run 的后缀
        last_run = runs[-1]
        last_text = last_run.text
        last_replaced = last_text[:match.end_offset]
        suffix = last_text[match.end_offset:]

        # 收集所有被替换的文本
        all_replaced_parts = [first_replaced]
        for run in runs[1:-1]:
            all_replaced_parts.append(run.text)
        if len(runs) > 1:
            all_replaced_parts.append(last_replaced)
        full_replaced = "".join(all_replaced_parts)

        # 移除所有涉及的 run
        for run in runs:
            if run.element.getparent() is not None:
                parent.remove(run.element)

        insert_index = first_index

        # 1. 添加前缀
        if prefix:
            prefix_run = self._create_text_run(prefix, rPr_copy)
            parent.insert(insert_index, prefix_run)
            insert_index += 1

        # 2. 添加删除标记
        del_elem = etree.Element(f"{{{w}}}del")
        del_elem.set(f"{{{w}}}author", author)
        del_elem.set(f"{{{w}}}date", timestamp)
        del_run = self._create_text_run(full_replaced, rPr_copy, is_delete=True)
        del_elem.append(del_run)
        parent.insert(insert_index, del_elem)
        insert_index += 1

        # 3. 添加插入标记
        ins_elem = etree.Element(f"{{{w}}}ins")
        ins_elem.set(f"{{{w}}}author", author)
        ins_elem.set(f"{{{w}}}date", timestamp)
        ins_run = self._create_text_run(new_text, rPr_copy)
        ins_elem.append(ins_run)
        parent.insert(insert_index, ins_elem)
        insert_index += 1

        # 4. 添加后缀
        if suffix:
            suffix_run = self._create_text_run(suffix, rPr_copy)
            parent.insert(insert_index, suffix_run)

    def _create_text_run(
        self,
        text: str,
        rPr: Optional[etree._Element] = None,
        is_delete: bool = False,
    ) -> etree._Element:
        """
        创建文本 run 元素

        Args:
            text: 文本内容
            rPr: 格式属性（可选）
            is_delete: 是否为删除文本（使用 delText）
        """
        w = NAMESPACES['w']

        run = etree.Element(f"{{{w}}}r")

        # 添加格式属性
        if rPr is not None:
            run.append(copy.deepcopy(rPr))

        # 添加文本元素
        if is_delete:
            t = etree.SubElement(run, f"{{{w}}}delText")
        else:
            t = etree.SubElement(run, f"{{{w}}}t")

        t.text = text

        # 保留空格
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

        return run

    def _enable_track_revisions(self) -> None:
        """
        在 settings.xml 中启用修订追踪
        """
        if self.settings_xml is None:
            # 创建基本的 settings.xml
            w = NAMESPACES['w']
            self.settings_xml = etree.Element(f"{{{w}}}settings")

        w = NAMESPACES['w']

        # 检查是否已存在 trackRevisions
        existing = self.settings_xml.find(f".//{{{w}}}trackRevisions", NAMESPACES)
        if existing is None:
            # 添加 trackRevisions 元素
            track_elem = etree.Element(f"{{{w}}}trackRevisions")
            self.settings_xml.insert(0, track_elem)

    # ==================== 批注功能 ====================

    def apply_comments(
        self,
        actions: List[ActionRecommendation],
        risks: List[RiskPoint],
        author: str = "AI审阅助手",
        initials: str = "AI",
    ) -> Tuple[int, int, List[str]]:
        """
        将行动建议作为批注添加到文档

        Args:
            actions: 行动建议列表
            risks: 风险点列表（用于定位）
            author: 批注作者
            initials: 作者缩写

        Returns:
            (添加数量, 跳过数量, 跳过原因列表)
        """
        if not actions:
            return 0, 0, []

        # 构建风险点 ID 到风险点的映射
        risk_map: Dict[str, RiskPoint] = {r.id: r for r in risks}

        added_count = 0
        skipped_count = 0
        skipped_reasons = []

        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        for action in actions:
            # 找到关联的风险点
            target_text = None
            for risk_id in action.related_risk_ids:
                risk = risk_map.get(risk_id)
                if risk and risk.location and risk.location.original_text:
                    target_text = risk.location.original_text.strip()
                    break

            if not target_text:
                skipped_count += 1
                skipped_reasons.append(
                    f"行动建议 {action.id}: 未找到关联的风险点原文"
                )
                continue

            # 在文档中查找目标文本
            match = self._find_text_in_document(target_text)

            if not match:
                skipped_count += 1
                skipped_reasons.append(
                    f"行动建议 {action.id}: 未在文档中找到原文 '{target_text[:30]}...'"
                )
                continue

            # 构建批注内容
            urgency_text = {
                "immediate": "【立即处理】",
                "soon": "【尽快处理】",
                "normal": "【一般】"
            }.get(action.urgency, "")

            comment_text = f"{urgency_text}{action.action_type}：{action.description}"
            if action.responsible_party:
                comment_text += f"\n负责方：{action.responsible_party}"
            if action.deadline_suggestion:
                comment_text += f"\n建议时限：{action.deadline_suggestion}"

            try:
                self._add_comment_to_match(
                    match=match,
                    comment_text=comment_text,
                    author=author,
                    initials=initials,
                    timestamp=timestamp,
                )
                added_count += 1
                logger.info(f"成功添加批注 {action.id}: '{target_text[:30]}...'")
            except Exception as e:
                skipped_count += 1
                skipped_reasons.append(f"行动建议 {action.id}: 添加批注失败 - {str(e)}")
                logger.error(f"添加批注失败: {e}")

        return added_count, skipped_count, skipped_reasons

    def _add_comment_to_match(
        self,
        match: TextMatch,
        comment_text: str,
        author: str,
        initials: str,
        timestamp: str,
    ) -> None:
        """
        在匹配的文本位置添加批注

        Args:
            match: 文本匹配结果
            comment_text: 批注内容
            author: 作者
            initials: 作者缩写
            timestamp: 时间戳
        """
        w = NAMESPACES['w']
        comment_id = str(self._next_comment_id)
        self._next_comment_id += 1

        # 1. 在 comments.xml 中添加批注内容
        self._ensure_comments_xml()
        self._add_comment_content(comment_id, comment_text, author, initials, timestamp)

        # 2. 在文档中添加批注锚点
        first_run = match.runs[0]
        last_run = match.runs[-1]
        parent = first_run.element.getparent()

        # 找到第一个 run 的位置
        first_index = list(parent).index(first_run.element)

        # 插入 commentRangeStart
        range_start = etree.Element(f"{{{w}}}commentRangeStart")
        range_start.set(f"{{{w}}}id", comment_id)
        parent.insert(first_index, range_start)

        # 找到最后一个 run 的位置（注意：插入了 rangeStart 后索引变化）
        last_index = list(parent).index(last_run.element)

        # 在最后一个 run 后插入 commentRangeEnd
        range_end = etree.Element(f"{{{w}}}commentRangeEnd")
        range_end.set(f"{{{w}}}id", comment_id)
        parent.insert(last_index + 1, range_end)

        # 插入 commentReference（包含在一个 run 中）
        ref_run = etree.Element(f"{{{w}}}r")
        ref = etree.SubElement(ref_run, f"{{{w}}}commentReference")
        ref.set(f"{{{w}}}id", comment_id)
        parent.insert(last_index + 2, ref_run)

        self._comments_added = True

    def _ensure_comments_xml(self) -> None:
        """确保 comments.xml 存在"""
        if self.comments_xml is not None:
            return

        w = NAMESPACES['w']

        # 创建新的 comments.xml
        self.comments_xml = etree.Element(
            f"{{{w}}}comments",
            nsmap={'w': NAMESPACES['w']}
        )

        # 更新 Content_Types.xml
        self._add_comments_content_type()

        # 更新关系文件
        self._add_comments_relationship()

    def _add_comment_content(
        self,
        comment_id: str,
        text: str,
        author: str,
        initials: str,
        timestamp: str,
    ) -> None:
        """
        在 comments.xml 中添加批注内容

        Args:
            comment_id: 批注 ID
            text: 批注文本
            author: 作者
            initials: 作者缩写
            timestamp: 时间戳
        """
        w = NAMESPACES['w']

        comment = etree.SubElement(self.comments_xml, f"{{{w}}}comment")
        comment.set(f"{{{w}}}id", comment_id)
        comment.set(f"{{{w}}}author", author)
        comment.set(f"{{{w}}}initials", initials)
        comment.set(f"{{{w}}}date", timestamp)

        # 批注内容可以包含多个段落
        for line in text.split('\n'):
            p = etree.SubElement(comment, f"{{{w}}}p")
            r = etree.SubElement(p, f"{{{w}}}r")
            t = etree.SubElement(r, f"{{{w}}}t")
            t.text = line
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    def _add_comments_content_type(self) -> None:
        """在 Content_Types.xml 中添加批注内容类型"""
        if self.content_types_xml is None:
            return

        # 检查是否已存在
        ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
        for override in self.content_types_xml.findall(f".//{{{ct_ns}}}Override"):
            if override.get("PartName") == "/word/comments.xml":
                return  # 已存在

        # 添加新的 Override
        override = etree.SubElement(
            self.content_types_xml,
            f"{{{ct_ns}}}Override"
        )
        override.set("PartName", "/word/comments.xml")
        override.set(
            "ContentType",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
        )

    def _add_comments_relationship(self) -> None:
        """在文档关系文件中添加批注关系"""
        if self.rels_xml is None:
            # 创建新的关系文件
            rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
            self.rels_xml = etree.Element(
                f"{{{rel_ns}}}Relationships",
                nsmap={None: rel_ns}
            )

        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"

        # 检查是否已存在
        comments_rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
        for rel in self.rels_xml.findall(f".//{{{rel_ns}}}Relationship"):
            if rel.get("Type") == comments_rel_type:
                return  # 已存在

        # 生成新的关系 ID
        existing_ids = set()
        for rel in self.rels_xml.findall(f".//{{{rel_ns}}}Relationship"):
            rid = rel.get("Id", "")
            if rid.startswith("rId"):
                try:
                    existing_ids.add(int(rid[3:]))
                except ValueError:
                    pass

        new_id = max(existing_ids, default=0) + 1
        rel_id = f"rId{new_id}"

        # 添加关系
        rel = etree.SubElement(self.rels_xml, f"{{{rel_ns}}}Relationship")
        rel.set("Id", rel_id)
        rel.set("Type", comments_rel_type)
        rel.set("Target", "comments.xml")

    def _save_document(self) -> bytes:
        """
        保存修改后的文档

        Returns:
            文档的字节内容
        """
        output = BytesIO()

        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, content in self._file_contents.items():
                if name == 'word/document.xml':
                    # 使用修改后的文档
                    content = etree.tostring(
                        self.document_xml,
                        xml_declaration=True,
                        encoding='UTF-8',
                        standalone=True,
                    )
                elif name == 'word/settings.xml' and self.settings_xml is not None:
                    # 使用修改后的设置
                    content = etree.tostring(
                        self.settings_xml,
                        xml_declaration=True,
                        encoding='UTF-8',
                        standalone=True,
                    )
                elif name == '[Content_Types].xml' and self.content_types_xml is not None:
                    # 使用修改后的内容类型
                    content = etree.tostring(
                        self.content_types_xml,
                        xml_declaration=True,
                        encoding='UTF-8',
                        standalone=True,
                    )
                elif name == 'word/_rels/document.xml.rels' and self.rels_xml is not None:
                    # 使用修改后的关系文件
                    content = etree.tostring(
                        self.rels_xml,
                        xml_declaration=True,
                        encoding='UTF-8',
                        standalone=True,
                    )

                zf.writestr(name, content)

            # 如果添加了批注，写入 comments.xml
            if self._comments_added and self.comments_xml is not None:
                comments_content = etree.tostring(
                    self.comments_xml,
                    xml_declaration=True,
                    encoding='UTF-8',
                    standalone=True,
                )
                zf.writestr('word/comments.xml', comments_content)

        output.seek(0)
        return output.read()


def generate_redline_document(
    docx_path: Path,
    modifications: List[ModificationSuggestion],
    author: str = "AI审阅助手",
    filter_confirmed: bool = True,
    actions: Optional[List[ActionRecommendation]] = None,
    risks: Optional[List[RiskPoint]] = None,
    include_comments: bool = False,
) -> RedlineResult:
    """
    便捷函数：生成带修订标记的 Word 文档

    Args:
        docx_path: 原始 Word 文档路径
        modifications: 修改建议列表
        author: 修订作者名称
        filter_confirmed: 是否只处理已确认的修改
        actions: 行动建议列表（用于生成批注）
        risks: 风险点列表（用于定位批注位置）
        include_comments: 是否将行动建议作为批注添加

    Returns:
        RedlineResult 包含处理结果和文档字节
    """
    try:
        generator = RedlineGenerator(docx_path)

        # 应用修改建议（修订标记）
        result = generator.apply_modifications(
            modifications=modifications,
            author=author,
            filter_confirmed=filter_confirmed,
        )

        # 如果需要添加批注
        if include_comments and actions and risks:
            comments_added, comments_skipped, comment_reasons = generator.apply_comments(
                actions=actions,
                risks=risks,
                author=author,
            )
            result.comments_added = comments_added
            result.comments_skipped = comments_skipped
            result.skipped_reasons.extend(comment_reasons)

            # 重新生成文档（包含批注）
            if comments_added > 0 or result.applied_count > 0:
                result.document_bytes = generator._save_document()
                result.success = True

        return result

    except Exception as e:
        logger.error(f"生成 Redline 文档失败: {e}")
        return RedlineResult(
            success=False,
            skipped_reasons=[f"文档处理失败: {str(e)}"],
        )
