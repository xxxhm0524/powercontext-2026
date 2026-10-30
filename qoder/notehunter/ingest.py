"""
ingest.py - 文档导入与切片模块

职责：
1. 扫描指定文件夹，读取 .md / .txt / .pdf 文件
2. 把每个文件的内容按段落切分成若干块（chunk）
3. 调用 seekdb 的 collection.add() 把切片写入向量数据库
"""

import os
import uuid

from pypdf import PdfReader

from search import get_or_create_collection


# 支持的文档类型
SUPPORTED_EXTENSIONS = {".md", ".txt", ".pdf"}

# 切片最大字符数（如果某一段特别长，就按这个长度强制切分）
MAX_CHUNK_LENGTH = 500


def read_file_content(file_path):
    """
    根据文件扩展名读取文件内容，返回纯文本字符串。
    - .md / .txt：直接读取文本
    - .pdf：用 pypdf 逐页提取文本
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        # PDF 需要用专门的库来解析
        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    else:
        # .md 和 .txt 都是纯文本，直接读取
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()


def split_into_chunks(text, filename):
    """
    把文本按段落切分成多个 chunk。

    切分规则：
    1. 先按空行（双换行）分段
    2. 如果某段超过 MAX_CHUNK_LENGTH 个字符，再按固定长度二次切分

    返回：
        列表，每个元素是 (chunk文本, chunk_id) 元组
        chunk_id 从 0 开始编号
    """
    # 按双换行符分段（兼容 \n\n 和 \r\n\r\n）
    raw_paragraphs = text.replace("\r\n", "\n").split("\n\n")

    chunks = []
    chunk_id = 0

    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            # 跳过空段
            continue

        if len(para) <= MAX_CHUNK_LENGTH:
            # 长度合理，直接作为一个 chunk
            chunks.append((para, chunk_id))
            chunk_id += 1
        else:
            # 超长段落，按 MAX_CHUNK_LENGTH 强制切分
            for start in range(0, len(para), MAX_CHUNK_LENGTH):
                piece = para[start : start + MAX_CHUNK_LENGTH]
                chunks.append((piece, chunk_id))
                chunk_id += 1

    return chunks


def ingest_folder(folder_path):
    """
    扫描 folder_path 下所有支持的文件，切片后写入 seekdb。

    参数：
        folder_path: 要扫描的文件夹路径

    返回：
        统计信息字典 {"files": 文件数, "chunks": 切片总数}
    """
    collection = get_or_create_collection()

    total_files = 0
    total_chunks = 0

    # 遍历文件夹
    for root, dirs, files in os.walk(folder_path):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                # 跳过不支持的文件类型
                continue

            file_path = os.path.join(root, fname)
            print(f"[导入] 正在处理文件: {fname}")

            # 读取文件内容
            try:
                content = read_file_content(file_path)
            except Exception as e:
                print(f"[错误] 无法读取文件 {fname}: {e}")
                continue

            if not content.strip():
                print(f"[跳过] 文件 {fname} 内容为空")
                continue

            # 切分成 chunk
            chunks = split_into_chunks(content, fname)
            print(f"  -> 切分为 {len(chunks)} 个片段")

            # 准备写入 seekdb 的三组数据
            ids = []        # 每个切片的唯一 ID
            documents = []  # 每个切片的文本
            metadatas = []  # 每个切片的元信息（文件名、段落序号）

            for chunk_text, chunk_id in chunks:
                # 用 uuid 生成唯一 ID，避免重复
                uid = str(uuid.uuid4())
                ids.append(uid)
                documents.append(chunk_text)
                metadatas.append({
                    "filename": fname,   # 来源文件名
                    "chunk_id": chunk_id, # 段落序号
                })

            # 批量写入 seekdb
            if ids:
                collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                )

            total_files += 1
            total_chunks += len(ids)

    # 关键：写入后必须刷新索引，否则新数据检索不到
    collection.refresh_index()
    print(f"\n[完成] 共导入 {total_files} 个文件，{total_chunks} 个切片")

    return {"files": total_files, "chunks": total_chunks}


# ---- 直接运行此脚本时，默认导入 data/ 文件夹 ----
if __name__ == "__main__":
    # 默认路径：当前脚本同目录下的 data/
    default_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    if os.path.isdir(default_data_dir):
        ingest_folder(default_data_dir)
    else:
        print(f"[错误] 找不到数据目录: {default_data_dir}")
