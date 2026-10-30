"""
search.py - seekdb 检索封装模块

职责：
1. 获取或创建 seekdb 中的 collection
2. 提供统一的检索接口，支持普通检索和带文件名过滤的混合检索
"""

import pyseekdb


# 集合名称，全局统一使用这一个
COLLECTION_NAME = "notes"


def get_client():
    """创建并返回一个 pyseekdb 客户端实例（嵌入式模式，无需连接远程服务）"""
    return pyseekdb.Client()


def get_or_create_collection(client=None):
    """
    获取名为 notes 的 collection；如果还不存在就先创建。
    返回 collection 对象，后续所有 add / query 都通过它操作。
    """
    if client is None:
        client = get_client()

    # 先尝试直接获取；若不存在再创建
    try:
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception:
        collection = client.create_collection(name=COLLECTION_NAME)

    return collection


def search(query_text, n_results=5, filename=None):
    """
    在 seekdb 中执行语义检索。

    参数：
        query_text  : 用户的自然语言查询字符串
        n_results   : 返回结果数量，默认 5 条
        filename    : 可选，限定只在某个文件名下的文档块中检索（混合检索）

    返回：
        一个列表，每个元素是字典：
        {
            "text":     原文片段,
            "filename": 来源文件名,
            "chunk_id": 段落序号,
            "distance": 相似度距离（越小越相似）
        }
    """
    collection = get_or_create_collection()

    # 构造查询参数
    query_params = {
        "query_texts": [query_text],   # query_texts 需要是列表
        "n_results": n_results,
    }

    # 如果用户指定了文件名，就加上 where 过滤条件（标量过滤）
    if filename and filename.strip():
        query_params["where"] = {"filename": filename.strip()}

    # 调用 seekdb 的 query 接口
    res = collection.query(**query_params)

    # ---- 解析返回结果 ----
    # res 的结构大致是：
    # {
    #   "ids": [[id1, id2, ...]],
    #   "documents": [[doc1, doc2, ...]],
    #   "metadatas": [[meta1, meta2, ...]],
    #   "distances": [[dist1, dist2, ...]],
    # }
    # 注意外层是列表套列表，因为 query_texts 可以传多条（我们只传了一条）

    results = []

    ids_list = res.get("ids", [[]])[0]
    docs_list = res.get("documents", [[]])[0]
    metas_list = res.get("metadatas", [[]])[0]
    dists_list = res.get("distances", [[]])[0]

    for i in range(len(ids_list)):
        meta = metas_list[i] if i < len(metas_list) else {}
        results.append({
            "text": docs_list[i] if i < len(docs_list) else "",
            "filename": meta.get("filename", "未知文件"),
            "chunk_id": meta.get("chunk_id", -1),
            "distance": round(dists_list[i], 4) if i < len(dists_list) else None,
        })

    return results
