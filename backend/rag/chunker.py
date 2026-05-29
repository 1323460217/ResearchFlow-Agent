import logging
import re
from dataclasses import dataclass, field
from typing import List

from backend.core.config import settings

logger = logging.getLogger(__name__)



@dataclass
class Chunk:
    content: str
    chunk_index: int
    token_count: int = 0
    metadata: dict = field(default_factory=dict)


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文 ~1.5 字符/token，英文 ~4 字符/token。"""
    chinese_chars = len(re.findall(r"[一-鿿]", text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def fixed_size_chunk(text: str) -> List[Chunk]:
    """固定大小切片：chunk_size=512 tokens, overlap=64 tokens。

    以段落为最小单元，避免在段落中间切断。
    """
    chunk_size = settings.CHUNK_SIZE
    chunk_overlap = settings.CHUNK_OVERLAP

    paragraphs = text.split("\n\n")
    chunks: List[Chunk] = []
    current_texts: List[str] = []
    current_tokens = 0
    index = 0

    for para in paragraphs:
        para_stripped = para.strip()
        if not para_stripped:
            continue

        para_tokens = _estimate_tokens(para_stripped)

        if current_tokens + para_tokens > chunk_size and current_texts:
            content = "\n\n".join(current_texts)
            chunks.append(Chunk(
                content=content,
                chunk_index=index,
                token_count=_estimate_tokens(content),
            ))
            index += 1

            # overlap: 保留最后几个段落
            overlap_tokens = 0
            overlap_texts: List[str] = []
            for p in reversed(current_texts):
                t = _estimate_tokens(p)
                if overlap_tokens + t > chunk_overlap:
                    break
                overlap_texts.insert(0, p)
                overlap_tokens += t
            current_texts = overlap_texts
            current_tokens = overlap_tokens

        current_texts.append(para_stripped)
        current_tokens += para_tokens

    # 最后一个 chunk
    if current_texts:
        content = "\n\n".join(current_texts)
        chunks.append(Chunk(
            content=content,
            chunk_index=index,
            token_count=_estimate_tokens(content),
        ))

    return chunks


def semantic_chunk(text: str) -> List[Chunk]:
    """语义切片：按 Markdown 标题（#、##、###）和段落边界切分。

    标题作为 chunk 的起点，其下内容归入同一 chunk，直到下一个同级别标题。
    """
    heading_pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

    sections = heading_pattern.split(text)
    if not sections or not heading_pattern.search(text):
        return fixed_size_chunk(text)

    chunks: List[Chunk] = []
    index = 0

    leading = sections[0].strip()
    sections = sections[1:]

    current_heading = ""
    current_body_parts: List[str] = []

    if leading:
        current_body_parts.append(leading)

    for i in range(0, len(sections), 3):
        level = sections[i] if i < len(sections) else ""
        heading_text = sections[i + 1] if i + 1 < len(sections) else ""
        body = sections[i + 2] if i + 2 < len(sections) else ""

        combined = f"{level} {heading_text}\n\n{body}".strip()

        tokens = _estimate_tokens(combined)
        if tokens > settings.CHUNK_SIZE * 2:
            sub_chunks = fixed_size_chunk(combined)
            for sc in sub_chunks:
                sc.chunk_index = index
                index += 1
                chunks.append(sc)
        else:
            chunks.append(Chunk(
                content=combined,
                chunk_index=index,
                token_count=tokens,
                metadata={"heading": heading_text.strip(), "level": len(level)},
            ))
            index += 1

    return chunks


def table_chunk(text: str) -> List[Chunk]:
    """表格切片：检测 Markdown 表格和 CSV 格式行，将表格作为独立 chunk。

    非表格内容回退到 fixed_size_chunk 处理。
    """
    table_pattern = re.compile(
        r"(\|.+\|[\r\n]+\|[-:| ]+\|[\r\n]+(?:\|.+\|[\r\n]*)*)",
        re.MULTILINE,
    )

    tables = list(table_pattern.finditer(text))
    if not tables:
        return fixed_size_chunk(text)

    chunks: List[Chunk] = []
    index = 0
    last_end = 0

    for match in tables:
        before = text[last_end:match.start()].strip()
        if before:
            for fc in fixed_size_chunk(before):
                fc.chunk_index = index
                index += 1
                chunks.append(fc)

        table_text = match.group(1).strip()
        chunks.append(Chunk(
            content=table_text,
            chunk_index=index,
            token_count=_estimate_tokens(table_text),
            metadata={"chunk_type": "table"},
        ))
        index += 1
        last_end = match.end()

    # 尾部剩余文本
    after = text[last_end:].strip()
    if after:
        for fc in fixed_size_chunk(after):
            fc.chunk_index = index
            index += 1
            chunks.append(fc)

    return chunks


def chunk_document(text: str, strategy: str = "fixed") -> List[Chunk]:
    """统一入口：按指定策略切片文档。

    Args:
        text: 文档全文
        strategy: "fixed" | "semantic" | "table" | "auto"

    Returns:
        Chunk 列表，chunk_index 已连续编号
    """
    strategies = {
        "fixed": fixed_size_chunk,
        "semantic": semantic_chunk,
        "table": table_chunk,
    }

    if strategy == "auto":
        has_headings = bool(re.search(r"^#{1,4}\s+", text, re.MULTILINE))
        has_tables = bool(re.search(r"\|.+\|[\r\n]+\|[-:| ]+\|", text))
        if has_tables:
            strategy = "table"
        elif has_headings:
            strategy = "semantic"
        else:
            strategy = "fixed"

    chunk_fn = strategies.get(strategy, fixed_size_chunk)

    if not text.strip():
        return []

    chunks = chunk_fn(text)
    logger.debug("Chunked document: strategy=%s, chunks=%d", strategy, len(chunks))
    return chunks
