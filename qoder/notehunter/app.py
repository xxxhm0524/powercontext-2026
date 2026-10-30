"""
app.py - Flask 主程序

职责：
1. 提供 Web 界面（首页）
2. 提供搜索 API 接口
3. 提供文档导入 API 接口
"""

import os
import shutil

from flask import Flask, render_template, request, jsonify

from search import search
from ingest import ingest_folder

# 创建 Flask 应用
app = Flask(__name__)

# 项目根目录（app.py 所在位置）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 默认的数据文件夹（存放待导入的 .md / .txt / .pdf）
DEFAULT_DATA_DIR = os.path.join(BASE_DIR, "data")

# seekdb 数据库文件目录（嵌入式模式，数据存在本地）
SEEKDB_DIR = os.path.join(BASE_DIR, "seekdb.db")


# ========== 页面路由 ==========

@app.route("/")
def index():
    """渲染首页（搜索界面）"""
    return render_template("index.html")


# ========== API 接口 ==========

@app.route("/api/search", methods=["GET"])
def api_search():
    """
    搜索接口
    请求参数（URL query string）：
        q        : 搜索关键词（必填）
        filename : 限定文件名（可选，用于混合检索）
        n        : 返回结果数量（可选，默认 5）
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "请输入搜索内容"}), 400

    filename = request.args.get("filename", "").strip()
    n_results = request.args.get("n", "5")
    try:
        n_results = int(n_results)
    except ValueError:
        n_results = 5

    try:
        results = search(query_text=query, n_results=n_results, filename=filename)
        return jsonify({"query": query, "filename": filename, "results": results})
    except Exception as e:
        return jsonify({"error": f"检索出错: {str(e)}"}), 500


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """
    文档导入接口
    请求体（JSON）：
        folder: 要导入的文件夹路径（可选，默认用 data/）
    """
    data = request.get_json(silent=True) or {}
    folder = data.get("folder", DEFAULT_DATA_DIR).strip()

    if not os.path.isdir(folder):
        return jsonify({"error": f"文件夹不存在: {folder}"}), 400

    try:
        stats = ingest_folder(folder)
        return jsonify({
            "message": "导入完成",
            "files": stats["files"],
            "chunks": stats["chunks"],
        })
    except Exception as e:
        return jsonify({"error": f"导入出错: {str(e)}"}), 500


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """
    重置数据库接口：删除 seekdb.db 目录，清空所有已导入的数据。
    用于避免重复导入导致数据重复。
    """
    try:
        if os.path.exists(SEEKDB_DIR):
            if os.path.isdir(SEEKDB_DIR):
                shutil.rmtree(SEEKDB_DIR)
            else:
                os.remove(SEEKDB_DIR)
        return jsonify({"message": "数据库已重置完成，可以重新导入文档"})
    except Exception as e:
        return jsonify({"error": f"重置出错: {str(e)}"}), 500


# ========== 启动入口 ==========

if __name__ == "__main__":
    print("=" * 50)
    print("  笔记猎人 NoteHunter 已启动")
    print("  请在浏览器打开: http://127.0.0.1:5000")
    print("=" * 50)
    # debug=True 表示代码修改后会自动重启，方便开发
    app.run(debug=True, host="127.0.0.1", port=5000)
