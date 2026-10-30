# -*- coding: utf-8 -*-
"""
seekdb 弹药库服务 —— Dify《梗王对线》的后端

作用：为 Dify 工作流提供「离谱辩论弹药检索」与「跨轮次记忆」能力。
      seekdb 在本作品里承担两个真实职责（对应赛题「技术结合有效」要求）：
        1. 弹药库 debate_ammo：45 条辩论话术/梗，按辩题语义检索 → 供 LLM 组织发言
        2. 记忆库 debate_memory：辩论中产生的金句与战绩，写入后可在后续轮次被检索复用

启动：
    pip install -r requirements.txt
    python seekdb_service.py                 # 启动服务，默认 http://127.0.0.1:8000
    python seekdb_service.py --selftest      # 不启动服务，只做一次本地检索自测
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    import pyseekdb
except ImportError:
    sys.exit("缺少依赖，请先执行： pip install -r requirements.txt")

# ---------------------------------------------------------------- 常量与路径
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "data", "ammunition.json")
DB_PATH = os.environ.get("SEEKDB_PATH", os.path.join(HERE, "seekdb_data"))

AMMO_COLLECTION = "debate_ammo"
MEMORY_COLLECTION = "debate_memory"


# ---------------------------------------------------------------- seekdb 封装
class AmmoStore:
    """seekdb 读写封装。

    关键坑（实测）：pyseekdb 嵌入式模式下，add/upsert 写入的数据不会立即进入向量索引，
    必须调用 collection.refresh_index() 之后 query 才能查到。否则返回空列表。
    这一条是整个项目能跑起来的前提。
    """

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.client = pyseekdb.Client(path=path)
        self.ammo = self._collection(AMMO_COLLECTION)
        self.memory = self._collection(MEMORY_COLLECTION)
        self._ensure_ammo_loaded()

    # ---------------- 基础操作
    def _collection(self, name: str):
        try:
            return self.client.create_collection(name=name)
        except Exception:
            return self.client.get_collection(name=name)

    @staticmethod
    def _reindex(col) -> None:
        """写入后刷新索引，使新数据可被立即检索"""
        try:
            col.refresh_index()
        except Exception as e:  # 不同版本可能不提供该接口，失败时降级处理
            print(f"[warn] refresh_index 调用失败（{e}），若检索为空请重启服务")

    @staticmethod
    def _count(col) -> int:
        try:
            return col.count()
        except Exception:
            return 0

    # ---------------- 弹药库
    def _ensure_ammo_loaded(self) -> None:
        """首次启动时把 data/ammunition.json 灌进 seekdb；已有数据则跳过"""
        if self._count(self.ammo) > 0:
            print(f"[init] 弹药库已存在 {self._count(self.ammo)} 条，跳过初始化")
            return
        if not os.path.exists(DATA_FILE):
            print(f"[warn] 找不到数据文件 {DATA_FILE}，弹药库为空")
            return
        with open(DATA_FILE, encoding="utf-8") as f:
            items = json.load(f)
        self.ammo.upsert(
            ids=[it["id"] for it in items],
            documents=[it["text"] for it in items],
            metadatas=[{"move": it.get("move", "未分类")} for it in items],
        )
        self._reindex(self.ammo)
        print(f"[init] 已从 ammunition.json 载入 {len(items)} 条弹药")

    def load_ammo_from_file(self) -> int:
        """强制重新装载弹药（数据文件更新后调用）"""
        with open(DATA_FILE, encoding="utf-8") as f:
            items = json.load(f)
        self.ammo.upsert(
            ids=[it["id"] for it in items],
            documents=[it["text"] for it in items],
            metadatas=[{"move": it.get("move", "未分类")} for it in items],
        )
        self._reindex(self.ammo)
        return len(items)

    def search_ammo(
        self, query: str, top_k: int = 3, move: str | None = None, exclude: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """语义检索弹药。move 可按招式类别过滤；exclude 用于避免重复引用"""
        where = {"move": move} if move else None
        n = top_k + len(exclude or [])
        res = self.ammo.query(query_texts=[query], n_results=max(n, 1), where=where)

        hits: list[dict[str, Any]] = []
        try:
            ids = res["ids"][0]
            docs = res["documents"][0]
            metas = res["metadatas"][0]
            dists = res["distances"][0]
        except (KeyError, IndexError):
            return hits

        skip = set(exclude or [])
        for _id, doc, meta, dist in zip(ids, docs, metas, dists):
            if _id in skip:
                continue
            hits.append(
                {
                    "id": _id,
                    "text": doc,
                    "move": (meta or {}).get("move", "未分类"),
                    "distance": round(float(dist), 4),
                    "similarity": round(1.0 / (1.0 + float(dist)), 4),  # 距离越小越相似
                }
            )
            if len(hits) >= top_k:
                break
        return hits

    # ---------------- 记忆库
    def remember(self, text: str, side: str = "unknown", topic: str = "", tag: str = "quote") -> str:
        """写入一条记忆（金句/战绩），写入后刷新索引使其可被后续检索"""
        import uuid

        _id = uuid.uuid4().hex[:12]
        self.memory.upsert(
            ids=[_id],
            documents=[text],
            metadatas=[{"side": side, "topic": topic, "tag": tag}],
        )
        self._reindex(self.memory)
        return _id

    def recall(self, query: str, top_k: int = 3, side: str | None = None) -> list[dict[str, Any]]:
        where = {"side": side} if side else None
        res = self.memory.query(query_texts=[query], n_results=top_k, where=where)
        hits: list[dict[str, Any]] = []
        try:
            ids = res["ids"][0]
            docs = res["documents"][0]
            metas = res["metadatas"][0]
            dists = res["distances"][0]
        except (KeyError, IndexError):
            return hits
        for _id, doc, meta, dist in zip(ids, docs, metas, dists):
            hits.append(
                {
                    "id": _id,
                    "text": doc,
                    "side": (meta or {}).get("side", "unknown"),
                    "tag": (meta or {}).get("tag", ""),
                    "distance": round(float(dist), 4),
                    "similarity": round(1.0 / (1.0 + float(dist)), 4),
                }
            )
        return hits

    def stats(self) -> dict[str, int]:
        return {"ammo_count": self._count(self.ammo), "memory_count": self._count(self.memory)}


# ---------------------------------------------------------------- 请求模型
class AmmoRequest(BaseModel):
    query: str = Field(..., description="辩题或当前论点")
    top_k: int = 3
    move: str | None = None
    exclude: list[str] = Field(default_factory=list)


class MemoryRequest(BaseModel):
    text: str
    side: str = "unknown"
    topic: str = ""
    tag: str = "quote"


class RecallRequest(BaseModel):
    query: str
    top_k: int = 3
    side: str | None = None


# ---------------------------------------------------------------- 服务
@asynccontextmanager
async def lifespan(_: FastAPI):
    """服务启动时初始化 seekdb（载入弹药库）"""
    get_store()
    print("[ready] seekdb 弹药库服务已就绪")
    yield


app = FastAPI(title="seekdb 辩论弹药库", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store: AmmoStore | None = None


def get_store() -> AmmoStore:
    global store
    if store is None:
        store = AmmoStore()
    return store


@app.get("/health")
def health() -> dict[str, Any]:
    s = get_store()
    return {"status": "ok", "seekdb_path": DB_PATH, **s.stats()}


@app.post("/ammo")
def ammo(req: AmmoRequest) -> dict[str, Any]:
    """检索辩论弹药 —— Dify 的 HTTP Request 节点主要调用这个"""
    s = get_store()
    hits = s.search_ammo(req.query, top_k=req.top_k, move=req.move, exclude=req.exclude)
    print(f"[ammo] query={req.query!r} top_k={req.top_k} -> {[h['id'] for h in hits]}")
    return {"ok": True, "query": req.query, "count": len(hits), "hits": hits}


@app.post("/memory")
def memory(req: MemoryRequest) -> dict[str, Any]:
    s = get_store()
    _id = s.remember(req.text, side=req.side, topic=req.topic, tag=req.tag)
    print(f"[memory] 写入 {_id} side={req.side} tag={req.tag}")
    return {"ok": True, "id": _id}


@app.post("/recall")
def recall(req: RecallRequest) -> dict[str, Any]:
    s = get_store()
    hits = s.recall(req.query, top_k=req.top_k, side=req.side)
    print(f"[recall] query={req.query!r} -> {[h['id'] for h in hits]}")
    return {"ok": True, "count": len(hits), "hits": hits}


@app.post("/reload")
def reload_ammo() -> dict[str, Any]:
    """数据文件更新后重新装载弹药库"""
    s = get_store()
    n = s.load_ammo_from_file()
    return {"ok": True, "loaded": n, **s.stats()}


# ---------------------------------------------------------------- 本地自测
def selftest() -> None:
    """不启动 Web 服务，直接验证 seekdb 检索是否真的在工作"""
    print("=" * 60)
    print("seekdb 弹药库自测")
    print("=" * 60)
    s = AmmoStore()
    print("库状态:", s.stats())

    for q in ["人工智能会不会取代老师", "要不要每天早起锻炼", "上班摸鱼是不是合理的"]:
        hits = s.search_ammo(q, top_k=2)
        print(f"\n辩题：{q}")
        for h in hits:
            print(f"  [{h['move']}] 相似度 {h['similarity']} | {h['text'][:38]}...")

    print("\n--- 测试记忆写入与复用 ---")
    mid = s.remember("对方说「规则就是规则」，我方回应：规则是人定的，人也能改。", side="con", topic="测试辩题")
    print("写入 id:", mid)
    back = s.recall("规则能不能改", top_k=1)
    for h in back:
        print(f"  检索到：{h['text']}")
    print("\n库状态:", s.stats())
    print("自测完成 ✅")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true", help="只做本地检索自测，不启动服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args, _ = parser.parse_known_args()

    if args.selftest:
        selftest()
    else:
        uvicorn.run(app, host=args.host, port=args.port)
