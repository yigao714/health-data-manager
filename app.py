"""
健康数据分析系统 — Web 服务器
=================================

一体化 Web 界面：截图上传 + OCR识别 + 个人档案 + 仪表盘 + 数据管理

启动: python app.py
访问: http://localhost:8080
"""

import os
import sys
import io
import json
import shutil
import zipfile
import hashlib
import socket
from pathlib import Path
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, render_template_string

# 项目路径
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from health_data_schema import HealthDataStore, DailyHealthData, PersonProfile
from extract_health_data import QwenVLExtractor, check_cross_day_consistency

# 修复 Windows GBK 终端无法输出 emoji 的问题
if sys.stdout and hasattr(sys.stdout, 'buffer') and not getattr(sys.stdout, '_utf8_wrapped', False):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdout._utf8_wrapped = True
if sys.stderr and hasattr(sys.stderr, 'buffer') and not getattr(sys.stderr, '_utf8_wrapped', False):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    sys.stderr._utf8_wrapped = True

app = Flask(__name__, static_folder=str(PROJECT_DIR))
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB 上传限制（兼容华为健康备份压缩包）

PEOPLE_DIR = PROJECT_DIR / "people"
DASHBOARD_TEMPLATE = PROJECT_DIR / "dashboard_template.html"
ECHARTS_JS = PROJECT_DIR / "echarts.min.js"
PUBLISH_CONFIG = PROJECT_DIR / "publish_config.json"

PEOPLE_DIR.mkdir(exist_ok=True)

import re as _re


# ── 多人路径工具 ──


def _safe_person_id(person_id: str) -> str:
    """校验人员标识，拒绝路径穿越/非法字符"""
    pid = (person_id or "").strip()
    if not pid or pid in (".", "..") or any(c in pid for c in '/\\:*?"<>|') or ".." in pid:
        raise ValueError(f"非法的人员标识: {person_id!r}")
    return pid


def _safe_filename(filename: str) -> str:
    """剥离目录成分，拒绝空/穿越文件名（保留中文等合法字符）"""
    name = os.path.basename((filename or "").replace("\\", "/"))
    if not name or name in (".", ".."):
        raise ValueError(f"非法的文件名: {filename!r}")
    return name


def get_person_dir(person_id: str) -> Path:
    """获取人员数据目录"""
    return PEOPLE_DIR / _safe_person_id(person_id)


def get_person_json(person_id: str) -> Path:
    return get_person_dir(person_id) / "health_data.json"


def get_person_dashboard(person_id: str) -> Path:
    return get_person_dir(person_id) / "dashboard.html"


def get_person_data_dir(person_id: str) -> Path:
    d = get_person_dir(person_id) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_people() -> list:
    """列出所有人员 ID（排除 _archive）"""
    if not PEOPLE_DIR.exists():
        return []
    return sorted([
        d.name for d in PEOPLE_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    ])


def create_person(person_id: str) -> bool:
    """创建新人员目录和空数据文件"""
    pdir = get_person_dir(person_id)
    if pdir.exists():
        return False
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "data").mkdir(exist_ok=True)
    store = HealthDataStore(person_name=person_id)
    store.save(str(get_person_json(person_id)))
    regenerate_dashboard(store, person_id)
    return True


def archive_person(person_id: str) -> bool:
    """归档删除人员（移到 _archive/ 下）"""
    pdir = get_person_dir(person_id)
    if not pdir.exists():
        return False
    archive_dir = PEOPLE_DIR / "_archive"
    archive_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = archive_dir / f"{person_id}_{ts}"
    shutil.move(str(pdir), str(dest))
    return True


def load_store(person_id: str) -> HealthDataStore:
    """加载指定人员的数据存储"""
    jp = get_person_json(person_id)
    if jp.exists():
        return HealthDataStore.load(str(jp))
    return HealthDataStore(person_name=person_id)


def save_store(store: HealthDataStore, person_id: str):
    """保存指定人员的数据存储"""
    get_person_dir(person_id).mkdir(parents=True, exist_ok=True)
    store.save(str(get_person_json(person_id)))


def regenerate_dashboard(store: HealthDataStore, person_id: str):
    """重新生成指定人员的仪表盘（内联 ECharts，确保离线/手机端可用）"""
    try:
        tmpl = DASHBOARD_TEMPLATE
        if not tmpl.exists():
            # 兼容：如果模板不存在，尝试用旧 dashboard.html
            old = PROJECT_DIR / "dashboard.html"
            if old.exists():
                tmpl = old
            else:
                print(f"仪表盘模板不存在: {tmpl}")
                return False

        with open(tmpl, "r", encoding="utf-8") as f:
            html = f.read()

        data_json = json.dumps(store.model_dump(
            include={"person_name", "profile", "data_source", "last_updated", "records"}
        ), ensure_ascii=False)

        pattern = r'/\*__DATA_PLACEHOLDER__\*/.*?/\*__DATA_END__\*/'
        replacement = f'/*__DATA_PLACEHOLDER__*/{data_json}/*__DATA_END__*/'
        new_html = _re.sub(pattern, replacement, html, flags=_re.DOTALL)

        # ── 内联 ECharts：将外部 <script src="echarts.min.js"> 替换为内联脚本 ──
        # 确保生成的 HTML 是完全自包含的单文件，在手机端（iOS Safari / 华为浏览器）
        # 直接打开即可正常渲染，无需依赖同目录下的 echarts.min.js 文件
        if ECHARTS_JS.exists():
            with open(ECHARTS_JS, "r", encoding="utf-8") as f:
                echarts_code = f.read()
            new_html = new_html.replace(
                '<script src="echarts.min.js"></script>',
                f'<script>{echarts_code}</script>'
            )

        out_path = get_person_dashboard(person_id)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(new_html)

        return True
    except Exception as e:
        print(f"仪表盘更新失败: {e}")
        return False


def _get_person_param():
    """从请求参数中获取 person_id，缺失则返回 None"""
    pid = request.args.get("person", "").strip()
    if not pid:
        # 也尝试从 JSON body 中获取
        if request.is_json:
            pid = (request.get_json(silent=True) or {}).get("person", "").strip()
    return pid if pid else None


# ── 数据迁移（旧单人格式 → 新多人格式）──

def _migrate_if_needed():
    """首次启动时检测并迁移旧格式数据"""
    old_json = PROJECT_DIR / "health_data.json"
    old_data_dir = PROJECT_DIR / "data"

    # 条件：根目录有 health_data.json 且 people/ 目录为空
    if not old_json.exists():
        return
    if list_people():
        return  # 已有人员，不需要迁移

    print("📦 检测到旧格式数据，开始迁移...")

    # 读取 person_name
    try:
        store = HealthDataStore.load(str(old_json))
        person_id = store.person_name.strip() or "默认"
    except Exception:
        person_id = "默认"

    # 创建人员目录
    pdir = get_person_dir(person_id)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "data").mkdir(exist_ok=True)

    # 移动 JSON
    shutil.move(str(old_json), str(get_person_json(person_id)))
    print(f"  ✅ health_data.json → people/{person_id}/health_data.json")

    # 移动截图
    if old_data_dir.exists():
        for f in old_data_dir.iterdir():
            if f.is_file():
                shutil.move(str(f), str(pdir / "data" / f.name))
        # 删除空目录
        try:
            old_data_dir.rmdir()
        except OSError:
            pass
        print(f"  ✅ data/ → people/{person_id}/data/")

    # 重新生成仪表盘
    store = load_store(person_id)
    regenerate_dashboard(store, person_id)
    print(f"  ✅ 仪表盘已重新生成")
    print(f"📦 迁移完成: 人员 [{person_id}]")


# 启动时执行迁移
_migrate_if_needed()


# ── 云端发布工具函数 ──

def load_publish_config():
    """加载云端发布配置"""
    if PUBLISH_CONFIG.exists():
        try:
            with open(PUBLISH_CONFIG, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"netlify_token": "", "sites": {}, "published_urls": {}}


def save_publish_config(config):
    """保存云端发布配置"""
    with open(PUBLISH_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _netlify_api(method, path, token, data=None, raw_body=None):
    """调用 Netlify REST API（使用 stdlib，无需额外依赖）"""
    import urllib.request
    import urllib.error

    url = f"https://api.netlify.com/api/v1{path}"
    headers = {"Authorization": f"Bearer {token}"}

    if raw_body is not None:
        body = raw_body
        headers["Content-Type"] = "application/octet-stream"
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        body = None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise Exception(f"Netlify API {e.code}: {err[:300]}")


def get_lan_ip():
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ══════════════════════════════════════════════════════════════
# 主页面 — 管理界面
# ══════════════════════════════════════════════════════════════

MAIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>健康数据管理中心</title>
    <style>
        *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
        :root {
            --bg: #0a0e1a; --bg2: #111827; --card: rgba(17,24,39,0.7);
            --border: rgba(99,102,241,0.15); --border-h: rgba(99,102,241,0.35);
            --text: #f1f5f9; --text2: #94a3b8; --muted: #64748b;
            --blue: #6366f1; --cyan: #22d3ee; --green: #34d399;
            --orange: #fb923c; --red: #f87171; --purple: #a78bfa;
            --radius: 16px;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
            background: var(--bg); color: var(--text); min-height: 100vh; line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

        /* Person selector */
        .person-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
        .person-select { background: var(--bg2); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 8px 16px; font-size: 14px; cursor: pointer; min-width: 120px; }
        .person-select:focus { outline: none; border-color: var(--cyan); }
        .btn-new-person { background: rgba(34,211,238,0.12); color: var(--cyan); border: 1px solid rgba(34,211,238,0.3); border-radius: 10px; padding: 8px 16px; font-size: 13px; cursor: pointer; transition: all 0.2s; }
        .btn-new-person:hover { background: rgba(34,211,238,0.2); }
        .btn-del-person { background: rgba(248,113,113,0.1); color: var(--red); border: 1px solid rgba(248,113,113,0.2); border-radius: 10px; padding: 8px 12px; font-size: 13px; cursor: pointer; transition: all 0.2s; }
        .btn-del-person:hover { background: rgba(248,113,113,0.2); }
        .btn-rename-person { background: rgba(167,139,250,0.12); color: var(--purple); border: 1px solid rgba(167,139,250,0.3); border-radius: 10px; padding: 8px 16px; font-size: 13px; cursor: pointer; transition: all 0.2s; }
        .btn-rename-person:hover { background: rgba(167,139,250,0.2); }
        .person-label { color: var(--text2); font-size: 13px; }
        .dl-btn-group { display: flex; gap: 8px; margin-bottom: 12px; }
        .dl-btn { background: rgba(99,102,241,0.1); color: var(--blue); border: 1px solid rgba(99,102,241,0.2); border-radius: 10px; padding: 10px 20px; font-size: 13px; cursor: pointer; transition: all 0.2s; text-decoration: none; }
        .dl-btn:hover { background: rgba(99,102,241,0.2); }

        /* Nav tabs */
        .nav { display: flex; gap: 4px; margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
        .nav-tab {
            padding: 10px 24px; border-radius: 10px 10px 0 0; cursor: pointer;
            color: var(--text2); font-size: 14px; font-weight: 500;
            background: transparent; border: none; transition: all 0.2s;
        }
        .nav-tab:hover { color: var(--text); background: rgba(99,102,241,0.08); }
        .nav-tab.active { color: var(--cyan); background: rgba(99,102,241,0.12); border-bottom: 2px solid var(--cyan); }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        /* Cards */
        .card {
            background: var(--card); backdrop-filter: blur(20px);
            border: 1px solid var(--border); border-radius: var(--radius);
            padding: 24px; margin-bottom: 20px;
        }
        .card-title { font-size: 18px; font-weight: 600; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }

        /* Upload zone */
        .upload-zone {
            border: 2px dashed var(--border); border-radius: var(--radius);
            padding: 48px; text-align: center; cursor: pointer;
            transition: all 0.3s; position: relative;
        }
        .upload-zone:hover, .upload-zone.dragover {
            border-color: var(--cyan); background: rgba(34,211,238,0.05);
        }
        .upload-zone input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
        .upload-icon { font-size: 48px; margin-bottom: 12px; }
        .upload-text { color: var(--text2); font-size: 14px; }
        .upload-hint { color: var(--muted); font-size: 12px; margin-top: 8px; }

        /* Result card */
        .result-card {
            background: rgba(99,102,241,0.06); border: 1px solid var(--border);
            border-radius: 12px; padding: 16px; margin-top: 16px;
        }
        .result-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
        .result-field { padding: 8px 12px; border-radius: 8px; background: rgba(99,102,241,0.04); }
        .result-field .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
        .result-field .value { font-size: 16px; font-weight: 600; color: var(--text); margin-top: 2px; }
        .result-field.error .value { color: var(--red); }
        .result-field.ok .value { color: var(--green); }

        /* Buttons */
        .btn {
            padding: 10px 24px; border-radius: 10px; border: none; cursor: pointer;
            font-size: 14px; font-weight: 600; transition: all 0.2s; display: inline-flex; align-items: center; gap: 6px;
        }
        .btn-primary { background: linear-gradient(135deg, var(--blue), var(--purple)); color: #fff; }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(99,102,241,0.3); }
        .btn-success { background: linear-gradient(135deg, var(--green), var(--cyan)); color: #0a0e1a; }
        .btn-danger { background: rgba(248,113,113,0.15); color: var(--red); border: 1px solid rgba(248,113,113,0.3); }
        .btn-danger:hover { background: rgba(248,113,113,0.25); }
        .btn-outline { background: transparent; color: var(--text2); border: 1px solid var(--border); }
        .btn-outline:hover { border-color: var(--cyan); color: var(--cyan); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }
        .btn-group { display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap; }

        /* Form */
        .form-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; }
        .form-group { display: flex; flex-direction: column; gap: 6px; }
        .form-label { font-size: 13px; color: var(--text2); font-weight: 500; }
        .form-input, .form-select {
            padding: 10px 14px; border-radius: 10px; border: 1px solid var(--border);
            background: rgba(99,102,241,0.04); color: var(--text); font-size: 14px;
            outline: none; transition: border-color 0.2s;
        }
        .form-input:focus, .form-select:focus { border-color: var(--cyan); }
        .form-input::placeholder { color: var(--muted); }
        .form-hint { font-size: 11px; color: var(--muted); }

        .tag-input { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 10px; min-height: 42px;
            border: 1px solid var(--border); border-radius: 10px; background: rgba(99,102,241,0.04); }
        .tag { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px;
            border-radius: 6px; background: rgba(99,102,241,0.15); color: var(--cyan); font-size: 12px; }
        .tag .remove { cursor: pointer; opacity: 0.6; }
        .tag .remove:hover { opacity: 1; }
        .tag-field { border: none; background: transparent; color: var(--text); font-size: 13px;
            outline: none; flex: 1; min-width: 100px; }

        /* Toast */
        .toast {
            position: fixed; top: 20px; right: 20px; padding: 14px 24px;
            border-radius: 12px; color: #fff; font-size: 14px; z-index: 1000;
            animation: slideIn 0.3s ease-out;
        }
        .toast.success { background: rgba(52,211,153,0.9); }
        .toast.error { background: rgba(248,113,113,0.9); }
        .toast.info { background: rgba(99,102,241,0.9); }
        @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

        /* Loading spinner */
        .spinner { display: inline-block; width: 20px; height: 20px; border: 3px solid rgba(255,255,255,0.3);
            border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* Status badge */
        .status { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px;
            border-radius: 6px; font-size: 12px; font-weight: 600; }
        .status.ok { background: rgba(52,211,153,0.12); color: var(--green); }
        .status.warn { background: rgba(251,146,60,0.12); color: var(--orange); }
        .status.error { background: rgba(248,113,113,0.12); color: var(--red); }

        /* Data table */
        .data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .data-table th { background: rgba(99,102,241,0.1); color: var(--purple); font-weight: 600;
            padding: 10px 12px; text-align: center; white-space: nowrap; border-bottom: 1px solid var(--border); }
        .data-table td { padding: 8px 12px; text-align: center; border-bottom: 1px solid rgba(99,102,241,0.06);
            color: var(--text2); }
        .data-table tr:hover td { background: rgba(99,102,241,0.06); color: var(--text); }
        .data-table .action-btn { padding: 4px 10px; border-radius: 6px; border: none; cursor: pointer;
            font-size: 11px; background: rgba(248,113,113,0.1); color: var(--red); }
        .data-table .action-btn:hover { background: rgba(248,113,113,0.2); }

        /* Header */
        .page-header { text-align: center; padding: 32px 0 16px; }
        .page-header h1 { font-size: 28px; font-weight: 700;
            background: linear-gradient(135deg, var(--cyan), var(--blue));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .page-header .sub { color: var(--text2); font-size: 14px; margin-top: 4px; }

        /* iframe for dashboard */
        .dashboard-frame { width: 100%; height: 80vh; border: 1px solid var(--border); border-radius: var(--radius); }

        /* Verification detail */
        .verify-detail { margin-top: 12px; padding: 12px; border-radius: 8px; background: rgba(99,102,241,0.04); }
        .verify-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 12px; color: var(--text2); }

        /* Cloud publish */
        .publish-url-box {
            display: none; margin-top: 12px; padding: 16px;
            background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.2);
            border-radius: 12px;
        }
        .publish-url-box.show { display: block; }
        .publish-url-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
        .publish-url-input {
            flex: 1; padding: 10px 14px; border-radius: 10px;
            border: 1px solid var(--border); background: var(--bg2);
            color: var(--cyan); font-size: 14px; outline: none;
        }
        .copy-btn {
            padding: 10px 16px; border-radius: 10px; border: none;
            background: var(--green); color: #0a0e1a; font-size: 13px;
            font-weight: 600; cursor: pointer; white-space: nowrap; transition: all 0.2s;
        }
        .copy-btn:hover { transform: translateY(-1px); }
        .token-input-box {
            display: none; margin-top: 12px; padding: 16px;
            background: rgba(99,102,241,0.06); border: 1px solid var(--border);
            border-radius: 12px;
        }
        .token-input-box.show { display: block; }
        .lan-info-box {
            display: none; margin-top: 12px; padding: 16px;
            background: rgba(34,211,238,0.08); border: 1px solid rgba(34,211,238,0.2);
            border-radius: 12px;
        }
        .lan-info-box.show { display: block; }

        /* Huawei ZIP import */
        .huawei-import-card { background: linear-gradient(135deg, rgba(251,146,60,0.06), rgba(167,139,250,0.06)); border: 1px solid rgba(251,146,60,0.2); }
        .huawei-import-card .card-title { color: var(--orange); }
        .import-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
        .import-row .form-group { flex: 1; min-width: 200px; }
        .import-progress { margin-top: 16px; display: none; }
        .import-progress.show { display: block; }
        .progress-bar-wrap { width: 100%; height: 8px; border-radius: 4px; background: rgba(99,102,241,0.1); overflow: hidden; margin-top: 8px; }
        .progress-bar-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--orange), var(--cyan)); width: 0%; transition: width 0.4s ease; }
        .import-log { margin-top: 12px; max-height: 240px; overflow-y: auto; padding: 12px; border-radius: 10px; background: rgba(10,14,26,0.6); font-family: 'Consolas','Courier New',monospace; font-size: 12px; line-height: 1.7; color: var(--text2); }
        .import-log .log-ok { color: var(--green); }
        .import-log .log-skip { color: var(--orange); }
        .import-log .log-err { color: var(--red); }
        .import-summary { margin-top: 12px; padding: 14px; border-radius: 10px; }
        .import-summary.ok { background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.2); }
        .import-summary.partial { background: rgba(251,146,60,0.1); border: 1px solid rgba(251,146,60,0.2); }
    </style>
</head>
<body>

<div class="container">
    <div class="page-header">
        <h1>🏥 健康数据管理中心</h1>
        <div class="sub">华为家庭空间 · 数据分析与健康追踪</div>
    </div>

    <div class="person-bar">
        <span class="person-label">当前人员:</span>
        <select class="person-select" id="person-select" onchange="switchPerson(this.value)"></select>
        <button class="btn-new-person" onclick="createNewPerson()">＋ 新建人员</button>
        <button class="btn-del-person" onclick="deleteCurrentPerson()">🗑 归档删除</button>
        <button class="btn-rename-person" onclick="renameCurrentPerson()">✏️ 重命名</button>
        <button class="btn-new-person" onclick="doBackup()">📦 备份全部数据</button>
        <button class="btn-new-person" onclick="document.getElementById('restore-input').click()">♻️ 恢复数据</button>
        <input type="file" id="restore-input" accept=".zip" style="display:none" onchange="doRestore(this)">
    </div>

    <div class="nav">
        <button class="nav-tab active" onclick="switchTab('upload', this)">📸 截图识别</button>
        <button class="nav-tab" onclick="switchTab('profile', this)">👤 个人档案</button>
        <button class="nav-tab" onclick="switchTab('data', this)">📋 数据管理</button>
        <button class="nav-tab" onclick="switchTab('dashboard', this)">📊 分析仪表盘</button>
    </div>

    <!-- ═══ TAB 1: UPLOAD ═══ -->
    <div id="tab-upload" class="tab-content active">
        <div class="card">
            <div class="card-title">📸 截图上传与识别</div>
            <div class="upload-zone" id="upload-zone">
                <input type="file" id="file-input" accept="image/*" multiple />
                <div class="upload-icon">📤</div>
                <div class="upload-text">拖拽截图到此处，或点击选择文件</div>
                <div class="upload-hint">支持 JPG、PNG 格式 · 华为家庭空间健康截图</div>
            </div>
        </div>
        <div id="extraction-results"></div>

        <!-- 华为备份压缩包导入 -->
        <div class="card huawei-import-card" style="margin-top: 24px;">
            <div class="card-title">📦 华为运动健康备份导入</div>
            <p style="color:var(--text2); font-size:13px; line-height:1.7; margin-bottom:16px;">
                上传从华为「个人数据与隐私」导出的加密 <code>.zip</code> 备份文件，系统将自动解密、提取并合并步数、心率、血氧、睡眠等健康指标数据。
            </p>
            <div class="import-row">
                <div class="form-group">
                    <label class="form-label">选择备份 ZIP 文件</label>
                    <input class="form-input" type="file" id="huawei-zip-input" accept=".zip">
                </div>
                <div class="form-group">
                    <label class="form-label">解压密码</label>
                    <input class="form-input" type="password" id="huawei-zip-pwd" placeholder="华为邮件中的解压密码">
                </div>
                <button class="btn btn-primary" id="btn-import-hw" onclick="importHuaweiZip()" style="height:42px;">
                    🚀 开始导入
                </button>
            </div>
            <div class="import-progress" id="hw-import-progress">
                <div style="display:flex; justify-content:space-between; font-size:12px; color:var(--text2);">
                    <span id="hw-progress-text">准备中…</span>
                    <span id="hw-progress-pct">0%</span>
                </div>
                <div class="progress-bar-wrap">
                    <div class="progress-bar-fill" id="hw-progress-bar"></div>
                </div>
                <div class="import-log" id="hw-import-log"></div>
                <div class="import-summary" id="hw-import-summary" style="display:none;"></div>
            </div>
        </div>
    </div>

    <!-- ═══ TAB 2: PROFILE ═══ -->
    <div id="tab-profile" class="tab-content">
        <div class="card">
            <div class="card-title">👤 个人健康档案</div>
            <div class="form-grid" id="profile-form">
                <div class="form-group">
                    <label class="form-label">称呼/姓名</label>
                    <input class="form-input" id="pf-name" placeholder="如：爸爸">
                </div>
                <div class="form-group">
                    <label class="form-label">年龄</label>
                    <input class="form-input" id="pf-age" type="number" placeholder="如：65">
                    <div class="form-hint">影响心率评估(最大心率=220-年龄)、睡眠需求</div>
                </div>
                <div class="form-group">
                    <label class="form-label">性别</label>
                    <select class="form-select" id="pf-sex">
                        <option value="">未填写</option>
                        <option value="male">男</option>
                        <option value="female">女</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">身高 (cm)</label>
                    <input class="form-input" id="pf-height" type="number" step="0.1" placeholder="如：170">
                </div>
                <div class="form-group">
                    <label class="form-label">体重 (kg)</label>
                    <input class="form-input" id="pf-weight" type="number" step="0.1" placeholder="如：70">
                    <div class="form-hint" id="bmi-display"></div>
                </div>
                <div class="form-group">
                    <label class="form-label">吸烟</label>
                    <select class="form-select" id="pf-smoking">
                        <option value="">未填写</option>
                        <option value="false">不吸烟</option>
                        <option value="true">吸烟</option>
                    </select>
                </div>
            </div>
            <div style="margin-top:20px;">
                <div class="form-group">
                    <label class="form-label">基础疾病 (按回车添加)</label>
                    <div class="tag-input" id="conditions-tags">
                        <input class="tag-field" id="condition-input" placeholder="如：高血压、糖尿病、COPD...">
                    </div>
                    <div class="form-hint">常见选项：高血压、糖尿病、冠心病、COPD、哮喘、睡眠呼吸暂停</div>
                </div>
            </div>
            <div style="margin-top:16px;">
                <div class="form-group">
                    <label class="form-label">当前用药 (按回车添加)</label>
                    <div class="tag-input" id="medications-tags">
                        <input class="tag-field" id="medication-input" placeholder="如：美托洛尔、氨氯地平...">
                    </div>
                    <div class="form-hint">如服用β受体阻滞剂(美托洛尔/比索洛尔等)，系统会自动调整心率评估标准</div>
                </div>
            </div>
            <div class="btn-group">
                <button class="btn btn-primary" onclick="saveProfile()">💾 保存档案</button>
            </div>
        </div>
    </div>

    <!-- ═══ TAB 3: DATA ═══ -->
    <div id="tab-data" class="tab-content">
        <div class="card">
            <div class="card-title">📋 数据管理</div>
            <div style="overflow-x:auto;" id="data-table-container"></div>
        </div>
    </div>

    <!-- ═══ TAB 4: DASHBOARD ═══ -->
    <div id="tab-dashboard" class="tab-content">
        <div class="dl-btn-group">
            <a class="dl-btn" id="dl-html" href="#" onclick="downloadReport('html'); return false;">📥 下载 HTML 报告</a>
            <a class="dl-btn" id="dl-docx" href="#" onclick="downloadReport('docx'); return false;">📄 下载 Word 报告</a>
            <button class="dl-btn" onclick="publishToCloud()" id="btn-publish" style="border:1px solid rgba(52,211,153,0.3);color:var(--green);background:rgba(52,211,153,0.1);">📤 发布到云端</button>
            <button class="dl-btn" onclick="toggleLanInfo()" style="border:1px solid rgba(34,211,238,0.3);color:var(--cyan);background:rgba(34,211,238,0.1);">🔗 局域网访问</button>
        </div>

        <div class="publish-url-box" id="publish-url-box">
            <div style="font-size:14px;font-weight:600;color:var(--green);">✅ 已发布到云端</div>
            <div style="font-size:12px;color:var(--text2);margin-top:4px;">将此链接发送到微信，所有手机（iPhone/华为/安卓）均可打开完整动态仪表盘</div>
            <div class="publish-url-row">
                <input class="publish-url-input" id="publish-url" readonly>
                <button class="copy-btn" onclick="copyUrl('publish-url')">📋 复制链接</button>
            </div>
        </div>

        <div class="token-input-box" id="token-input-box">
            <div style="font-size:14px;font-weight:600;color:var(--blue);">🔑 首次使用需配置 Netlify Token</div>
            <div style="font-size:12px;color:var(--text2);margin-top:6px;line-height:1.8;">
                1. 访问 <a href="https://app.netlify.com/user/applications#personal-access-tokens" target="_blank" style="color:var(--cyan);">Netlify 个人令牌页面</a>（需先注册免费账号）<br>
                2. 点击 “New access token”，填写名称（如 health-report），点击 Generate<br>
                3. 复制生成的 Token，粘贴到下方
            </div>
            <div class="publish-url-row" style="margin-top:12px;">
                <input class="publish-url-input" id="netlify-token-input" placeholder="粘贴 Netlify Access Token..." style="color:var(--text);">
                <button class="copy-btn" onclick="saveNetlifyToken()" style="background:var(--blue);color:#fff;">💾 保存</button>
            </div>
        </div>

        <div class="lan-info-box" id="lan-info-box">
            <div style="font-size:14px;font-weight:600;color:var(--cyan);">🔗 局域网访问（同一 WiFi）</div>
            <div style="font-size:12px;color:var(--text2);margin-top:4px;">在同一 WiFi 下，用手机浏览器访问此地址，或发到微信点击打开</div>
            <div class="publish-url-row">
                <input class="publish-url-input" id="lan-url" readonly style="color:var(--cyan);">
                <button class="copy-btn" onclick="copyUrl('lan-url')" style="background:var(--cyan);">📋 复制</button>
            </div>
        </div>

        <div class="card" style="padding:8px;margin-top:12px;">
            <iframe class="dashboard-frame" id="dashboard-iframe" src=""></iframe>
        </div>
    </div>
</div>

<script>
// ══════════ STATE ══════════
let conditions = [];
let medications = [];
let pendingExtractions = {};
let extractionCounter = 0;
let currentPerson = '';

// ══════════ PERSON MANAGEMENT ══════════
async function loadPeopleList() {
    try {
        const resp = await fetch('/api/people');
        const people = await resp.json();
        const sel = document.getElementById('person-select');
        sel.innerHTML = '';
        if (!people.length) {
            sel.innerHTML = '<option value="">（暂无人员）</option>';
            currentPerson = '';
            return;
        }
        people.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name + ' (' + p.records + '条记录)';
            sel.appendChild(opt);
        });
        if (!currentPerson || !people.find(p => p.id === currentPerson)) {
            currentPerson = people[0].id;
        }
        sel.value = currentPerson;
    } catch(e) { console.error('loadPeopleList failed:', e); }
}

function switchPerson(pid) {
    currentPerson = pid;
    loadProfile();
    // 如果当前在数据管理或仪表盘标签，刷新
    const activeTab = document.querySelector('.tab-content.active');
    if (activeTab && activeTab.id === 'tab-data') loadDataTable();
    if (activeTab && activeTab.id === 'tab-dashboard') loadDashboard();
    showToast('已切换到: ' + pid, 'success');
}

async function createNewPerson() {
    const name = prompt('请输入新人员名称（如：爸爸、妈妈）:');
    if (!name || !name.trim()) return;
    try {
        const resp = await fetch('/api/people', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim() }),
        });
        const result = await resp.json();
        if (result.success) {
            currentPerson = result.id;
            await loadPeopleList();
            switchPerson(currentPerson);
            showToast('已创建人员: ' + name.trim(), 'success');
        } else {
            showToast(result.error || '创建失败', 'error');
        }
    } catch(e) { showToast('网络错误: ' + e.message, 'error'); }
}

async function deleteCurrentPerson() {
    if (!currentPerson) return;
    if (!confirm('确定要归档删除 [' + currentPerson + '] 吗？数据将保留在 people/_archive/ 目录中，可随时恢复。')) return;
    try {
        const resp = await fetch('/api/people/' + encodeURIComponent(currentPerson), { method: 'DELETE' });
        const result = await resp.json();
        if (result.success) {
            showToast(currentPerson + ' 已归档', 'success');
            currentPerson = '';
            await loadPeopleList();
            if (currentPerson) switchPerson(currentPerson);
        } else {
            showToast(result.error || '删除失败', 'error');
        }
    } catch(e) { showToast('网络错误: ' + e.message, 'error'); }
}

async function renameCurrentPerson() {
    if (!currentPerson) { showToast('请先选择人员', 'error'); return; }
    const newName = prompt('请输入 [' + currentPerson + '] 的新名字:', currentPerson);
    if (!newName || !newName.trim() || newName.trim() === currentPerson) return;
    try {
        const resp = await fetch('/api/people/' + encodeURIComponent(currentPerson) + '/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName.trim() }),
        });
        const result = await resp.json();
        if (result.success) {
            const oldName = currentPerson;
            currentPerson = result.id;
            await loadPeopleList();
            switchPerson(currentPerson);
            showToast('已将 ' + oldName + ' 重命名为: ' + currentPerson, 'success');
        } else {
            showToast(result.error || '重命名失败', 'error');
        }
    } catch(e) { showToast('网络错误: ' + e.message, 'error'); }
}

function downloadReport(format) {
    if (!currentPerson) { showToast('请先选择人员', 'error'); return; }
    window.open('/api/report/' + format + '?person=' + encodeURIComponent(currentPerson), '_blank');
}

// ══════════ TAB SWITCHING ══════════
function switchTab(name, btn) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    btn.classList.add('active');
    if (name === 'dashboard') loadDashboard();
    if (name === 'data') loadDataTable();
    if (name === 'profile') loadProfile();
}

// ══════════ TOAST ══════════
function showToast(msg, type='info') {
    const t = document.createElement('div');
    t.className = 'toast ' + type;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

// ══════════ UPLOAD ══════════
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');

['dragenter','dragover'].forEach(e => {
    uploadZone.addEventListener(e, ev => { ev.preventDefault(); uploadZone.classList.add('dragover'); });
});
['dragleave','drop'].forEach(e => {
    uploadZone.addEventListener(e, ev => { ev.preventDefault(); uploadZone.classList.remove('dragover'); });
});
uploadZone.addEventListener('drop', ev => {
    const files = ev.dataTransfer.files;
    if (files.length) handleFiles(files);
});
fileInput.addEventListener('change', ev => {
    if (ev.target.files.length) handleFiles(ev.target.files);
});

async function handleFiles(files) {
    const resultsDiv = document.getElementById('extraction-results');
    for (const file of files) {
        const card = document.createElement('div');
        card.className = 'card';
        const objectUrl = URL.createObjectURL(file);
        card.innerHTML = `
            <div class="card-title" style="margin-bottom:12px;">📷 ${file.name}</div>
            <div style="display:flex; gap:16px; align-items:flex-start;">
                <img src="${objectUrl}" style="max-height: 100px; max-width: 100px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); cursor: pointer;" onclick="window.open('${objectUrl}', '_blank')" title="点击查看大图">
                <div style="flex: 1;">
                    <div style="display:flex;align-items:center;gap:8px;color:var(--text2);">
                        <span class="spinner"></span> AI 正在识别中...（提取 + 复核验证）
                    </div>
                </div>
            </div>`;
        resultsDiv.prepend(card);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const resp = await fetch('/api/extract?person=' + encodeURIComponent(currentPerson), { method: 'POST', body: formData });
            const data = await resp.json();
            if (data.already_processed) {
                card.innerHTML = `
                    <div class="card-title" style="margin-bottom:12px;">📷 ${file.name} <span class="status" style="background:rgba(52,211,153,0.15);color:#34d399;">✓ 已跳过（已上传过）</span></div>
                    <div style="display:flex; gap:16px; align-items:flex-start;">
                        <img src="${objectUrl}" style="max-height: 100px; max-width: 100px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); cursor: pointer;" onclick="window.open('${objectUrl}', '_blank')" title="点击查看大图">
                        <div style="flex: 1;">
                            <p style="color:var(--text2);font-size:13px;line-height:1.6;margin:0;">${data.message || '该图片已在系统中，已自动过滤，无需重复上传。'}</p>
                        </div>
                    </div>`;
            } else if (data.error) {
                card.innerHTML = `
                    <div class="card-title" style="margin-bottom:12px;">📷 ${file.name} <span class="status error">❌ 失败</span></div>
                    <div style="display:flex; gap:16px; align-items:flex-start;">
                        <img src="${objectUrl}" style="max-height: 100px; max-width: 100px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); cursor: pointer;" onclick="window.open('${objectUrl}', '_blank')" title="点击查看大图">
                        <div style="flex: 1;">
                            <p style="color:var(--red);font-size:13px;line-height:1.6;margin:0;">${data.error}</p>
                        </div>
                    </div>`;
            } else {
                const needsReview = renderExtractionResult(card, file.name, data, objectUrl);
                if (!needsReview) {
                    // 无异常，自动入库
                    const eid = card.querySelector('[data-eid]')?.dataset.eid;
                    if (eid) await doConfirm(eid);
                }
            }
        } catch (e) {
            card.innerHTML = `
                <div class="card-title" style="margin-bottom:12px;">📷 ${file.name} <span class="status error">❌ 网络错误</span></div>
                <div style="display:flex; gap:16px; align-items:flex-start;">
                    <img src="${objectUrl}" style="max-height: 100px; max-width: 100px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); cursor: pointer;" onclick="window.open('${objectUrl}', '_blank')" title="点击查看大图">
                    <div style="flex: 1;">
                        <p style="color:var(--red);font-size:13px;line-height:1.6;margin:0;">${e.message}</p>
                    </div>
                </div>`;
        }
    }
    fileInput.value = '';
}

function renderExtractionResult(card, filename, data, objectUrl) {
    const d = data.extraction;
    const v = data.verification;
    const w = data.warnings || [];
    const cw = data.consistency_warnings || [];

    // 存入全局待确认列表
    const eid = 'ext_' + (++extractionCounter);
    pendingExtractions[eid] = { filename, data: d };

    const fields = [
        ['日期', d.date, 'date'], ['步数', d.steps, 'steps'],
        ['距离', d.distance_km + ' km', 'distance_km'], ['锻炼', d.exercise_minutes + ' min', 'exercise_minutes'],
        ['心率范围', d.heart_rate_min + '-' + d.heart_rate_max, 'heart_rate_min'],
        ['静息心率', d.resting_heart_rate + ' bpm', 'resting_heart_rate'],
        ['血氧范围', d.spo2_min + '%-' + d.spo2_max + '%', 'spo2_min'],
        ['睡眠', d.sleep_hours + 'h', 'sleep_hours'],
        ['入睡', d.sleep_start, 'sleep_start'], ['醒来', d.sleep_end, 'sleep_end'],
        ['睡眠分数', d.sleep_score, 'sleep_score'],
    ];

    // 智能判断：corrections值和提取值相同 → 只是格式确认，非真正错误
    let hasRealError = false;
    if (v && v.verified === false) {
        const corr = v.corrections || {};
        for (const [key, corrVal] of Object.entries(corr)) {
            const origVal = d[key];
            if (corrVal !== undefined && origVal !== undefined) {
                const diff = (typeof origVal === 'number') ? Math.abs(Number(corrVal) - origVal) : (String(corrVal) !== String(origVal) ? 1 : 0);
                if (diff > 0.06) { hasRealError = true; break; }
            }
        }
    }

    // 也检查一致性警告中的突变警告
    const hasConsistencyIssue = cw.length > 0;

    // 需要人工审核的条件：有真实错误 或 有一致性突变警告
    const needsReview = hasRealError || hasConsistencyIssue;

    let fieldsHTML = fields.map(([label, value, key]) => {
        const fieldOk = !hasRealError || !v || !v.field_results || v.field_results[key] !== false;
        return '<div class="result-field ' + (fieldOk ? 'ok' : 'error') + '">' +
            '<div class="label">' + label + '</div>' +
            '<div class="value">' + (value != null ? value : '-') + (fieldOk ? '' : ' !!') + '</div>' +
            '</div>';
    }).join('');

    let warningsHTML = '';
    if (w.length || cw.length) {
        warningsHTML = '<div style="margin-top:10px;">' +
            [...w, ...cw].map(x => '<div style="color:var(--orange);font-size:12px;">' + x + '</div>').join('') +
            '</div>';
    }

    let verifyBadge = '';
    if (hasRealError) {
        verifyBadge = '<span class="status error">!! AI发现数据错误，请核对</span>';
    } else if (!needsReview) {
        verifyBadge = '<span class="status" style="background:rgba(52,211,153,0.15);color:#34d399;">✓ 自动入库中...</span>';
    }

    const noteText = (v && v.notes && hasRealError) ? '<div style="margin-top:6px;font-size:12px;color:var(--red);">' + v.notes + '</div>' : '';

    // 根据是否需要审核决定按钮显示
    let buttonsHTML;
    if (needsReview) {
        buttonsHTML = '<div class="btn-group">' +
            '<button class="btn btn-success" id="' + eid + '" data-eid="' + eid + '">Confirm 确认入库</button>' +
            '<button class="btn btn-outline" data-action="discard">Discard 丢弃</button>' +
        '</div>';
    } else {
        buttonsHTML = '<div class="btn-group">' +
            '<button class="btn btn-success" id="' + eid + '" data-eid="' + eid + '" style="display:none;">auto</button>' +
        '</div>';
    }

    let imageHTML = '';
    if (objectUrl) {
        imageHTML = `<img src="${objectUrl}" style="max-height: 100px; max-width: 100px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border); cursor: pointer;" onclick="window.open('${objectUrl}', '_blank')" title="点击查看大图">`;
    }

    card.innerHTML = `
        <div class="card-title" style="margin-bottom:12px;">📷 ${filename} ${verifyBadge ? verifyBadge : ''}</div>
        <div style="display:flex; gap:16px; align-items:flex-start;">
            ${imageHTML}
            <div style="flex: 1; min-width: 0;">
                <div class="result-card" style="margin: 0 0 12px 0;">
                    <div class="result-grid">${fieldsHTML}</div>
                    ${warningsHTML} ${noteText}
                </div>
                ${buttonsHTML}
            </div>
        </div>`;

    if (needsReview) {
        card.querySelector('[data-eid]').addEventListener('click', function() { doConfirm(this.dataset.eid); });
        card.querySelector('[data-action="discard"]').addEventListener('click', function() { this.closest('.card').remove(); });
    }

    return needsReview;
}

async function doConfirm(eid) {
    const entry = pendingExtractions[eid];
    if (!entry) { showToast('数据丢失，请重新上传', 'error'); return; }

    const btn = document.getElementById(eid);
    if (btn) { btn.disabled = true; btn.textContent = '保存中...'; }

    try {
        const resp = await fetch('/api/confirm?person=' + encodeURIComponent(currentPerson), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: entry.filename, data: entry.data }),
        });
        const result = await resp.json();
        if (result.success) {
            showToast(entry.data.date + ' 数据已入库', 'success');
            if (btn) { btn.textContent = 'Done 已入库'; btn.style.opacity = '0.6'; }
            delete pendingExtractions[eid];
        } else {
            showToast('保存失败: ' + result.error, 'error');
            if (btn) { btn.disabled = false; btn.textContent = 'Confirm 确认入库'; }
        }
    } catch(e) {
        showToast('网络错误: ' + e.message, 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Confirm 确认入库'; }
    }
}



// ══════════ PROFILE ══════════
async function loadProfile() {
    try {
        if (!currentPerson) return;
        const resp = await fetch('/api/profile?person=' + encodeURIComponent(currentPerson));
        const data = await resp.json();
        document.getElementById('pf-name').value = data.person_name || '';
        document.getElementById('pf-age').value = data.profile?.age || '';
        document.getElementById('pf-sex').value = data.profile?.sex || '';
        document.getElementById('pf-height').value = data.profile?.height_cm || '';
        document.getElementById('pf-weight').value = data.profile?.weight_kg || '';
        document.getElementById('pf-smoking').value = data.profile?.smoking === true ? 'true' : data.profile?.smoking === false ? 'false' : '';
        conditions = data.profile?.conditions || [];
        medications = data.profile?.medications || [];
        renderTags('conditions-tags', conditions, 'condition-input');
        renderTags('medications-tags', medications, 'medication-input');
        updateBMI();
    } catch(e) { console.error(e); }
}

async function saveProfile() {
    const profile = {
        person_name: document.getElementById('pf-name').value,
        profile: {
            age: parseInt(document.getElementById('pf-age').value) || null,
            sex: document.getElementById('pf-sex').value || null,
            height_cm: parseFloat(document.getElementById('pf-height').value) || null,
            weight_kg: parseFloat(document.getElementById('pf-weight').value) || null,
            smoking: document.getElementById('pf-smoking').value === 'true' ? true :
                     document.getElementById('pf-smoking').value === 'false' ? false : null,
            conditions: conditions,
            medications: medications,
        }
    };
    try {
        if (!currentPerson) { showToast('请先选择或新建人员', 'error'); return; }
        const resp = await fetch('/api/profile?person=' + encodeURIComponent(currentPerson), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(profile),
        });
        const data = await resp.json();
        if (data.success) showToast('✅ 个人档案已保存', 'success');
        else showToast('保存失败', 'error');
    } catch(e) { showToast('网络错误', 'error'); }
}

// Tag input helper
function renderTags(containerId, tags, inputId) {
    const container = document.getElementById(containerId);
    container.innerHTML = tags.map((t, i) =>
        `<span class="tag">${t} <span class="remove" onclick="removeTag('${containerId}', ${i}, '${inputId}')">&times;</span></span>`
    ).join('') + `<input class="tag-field" id="${inputId}" placeholder="按回车添加..."
        onkeydown="if(event.key==='Enter'){event.preventDefault();addTag('${containerId}','${inputId}');}">`;
}
function addTag(containerId, inputId) {
    const input = document.getElementById(inputId);
    const val = input.value.trim();
    if (!val) return;
    const tags = containerId.includes('condition') ? conditions : medications;
    if (!tags.includes(val)) { tags.push(val); }
    renderTags(containerId, tags, inputId);
}
function removeTag(containerId, index, inputId) {
    const tags = containerId.includes('condition') ? conditions : medications;
    tags.splice(index, 1);
    renderTags(containerId, tags, inputId);
}

// BMI auto-calc
document.getElementById('pf-height')?.addEventListener('input', updateBMI);
document.getElementById('pf-weight')?.addEventListener('input', updateBMI);
function updateBMI() {
    const h = parseFloat(document.getElementById('pf-height').value);
    const w = parseFloat(document.getElementById('pf-weight').value);
    const el = document.getElementById('bmi-display');
    if (h && w) {
        const bmi = (w / Math.pow(h/100, 2)).toFixed(1);
        const cat = bmi < 18.5 ? '偏瘦' : bmi < 24 ? '正常' : bmi < 28 ? '超重' : '肥胖';
        el.textContent = `BMI: ${bmi} (${cat})`;
        el.style.color = bmi >= 24 ? 'var(--orange)' : 'var(--green)';
    } else { el.textContent = ''; }
}

// ══════════ DATA TABLE ══════════
async function loadDataTable() {
    try {
        if (!currentPerson) return;
        const resp = await fetch('/api/records?person=' + encodeURIComponent(currentPerson));
        const records = await resp.json();
        if (!records.length) {
            document.getElementById('data-table-container').innerHTML = '<p style="color:var(--muted)">暂无数据</p>';
            return;
        }
        let html = `<table class="data-table"><thead><tr>
            <th>日期</th><th>步数</th><th>距离</th><th>心率</th><th>静息HR</th>
            <th>血氧</th><th>睡眠</th><th>入睡</th><th>醒来</th><th>分数</th><th>操作</th>
        </tr></thead><tbody>`;
        records.forEach(r => {
            html += `<tr>
                <td style="font-weight:600;color:var(--blue)">${r.date}</td>
                <td>${r.steps?.toLocaleString() ?? '-'}</td>
                <td>${r.distance_km ?? '-'} km</td>
                <td>${r.heart_rate_min}-${r.heart_rate_max}</td>
                <td>${r.resting_heart_rate ?? '-'}</td>
                <td>${r.spo2_min}%-${r.spo2_max}%</td>
                <td>${r.sleep_hours?.toFixed(1) ?? '-'}h</td>
                <td>${r.sleep_start ?? '-'}</td>
                <td>${r.sleep_end ?? '-'}</td>
                <td>${r.sleep_score ?? '-'}</td>
                <td><button class="action-btn" onclick="deleteRecord('${r.date}')">删除</button></td>
            </tr>`;
        });
        html += '</tbody></table>';
        document.getElementById('data-table-container').innerHTML = html;
    } catch(e) { console.error(e); }
}

async function deleteRecord(date) {
    if (!confirm(`确定删除 ${date} 的数据？`)) return;
    try {
        const resp = await fetch('/api/records/' + date + '?person=' + encodeURIComponent(currentPerson), { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) { showToast('已删除 ' + date, 'success'); loadDataTable(); }
        else showToast('删除失败', 'error');
    } catch(e) { showToast('网络错误', 'error'); }
}

// ══════════ DASHBOARD ══════════
function loadDashboard() {
    const iframe = document.getElementById('dashboard-iframe');
    if (!currentPerson) return;
    iframe.src = '/dashboard.html?person=' + encodeURIComponent(currentPerson) + '&t=' + Date.now();
    loadPublishState();
}

// ══════════ CLOUD PUBLISH ══════════
async function publishToCloud() {
    if (!currentPerson) { showToast('请先选择人员', 'error'); return; }

    // 检查 token 配置
    try {
        const cfgResp = await fetch('/api/publish/config');
        const cfg = await cfgResp.json();
        if (!cfg.has_token) {
            document.getElementById('token-input-box').classList.add('show');
            showToast('请先配置 Netlify Token', 'info');
            return;
        }
    } catch(e) { showToast('检查配置失败: ' + e.message, 'error'); return; }

    const btn = document.getElementById('btn-publish');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ 发布中...';

    try {
        const resp = await fetch('/api/publish?person=' + encodeURIComponent(currentPerson), { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            document.getElementById('publish-url').value = data.url;
            document.getElementById('publish-url-box').classList.add('show');
            document.getElementById('token-input-box').classList.remove('show');
            showToast('✅ 发布成功！复制链接发到微信即可', 'success');
        } else if (data.need_token) {
            document.getElementById('token-input-box').classList.add('show');
            showToast('请先配置 Netlify Token', 'info');
        } else {
            showToast('发布失败: ' + data.error, 'error');
        }
    } catch(e) {
        showToast('网络错误: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = origText;
    }
}

async function saveNetlifyToken() {
    const token = document.getElementById('netlify-token-input').value.trim();
    if (!token) { showToast('请输入 Token', 'error'); return; }
    try {
        const resp = await fetch('/api/publish/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token }),
        });
        const data = await resp.json();
        if (data.success) {
            showToast('✅ Token 已保存', 'success');
            document.getElementById('token-input-box').classList.remove('show');
            publishToCloud();
        } else {
            showToast('保存失败: ' + data.error, 'error');
        }
    } catch(e) { showToast('网络错误: ' + e.message, 'error'); }
}

function copyUrl(inputId) {
    const input = document.getElementById(inputId);
    input.select();
    input.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(input.value).then(() => {
        showToast('✅ 链接已复制', 'success');
    }).catch(() => {
        document.execCommand('copy');
        showToast('✅ 链接已复制', 'success');
    });
}

async function toggleLanInfo() {
    const box = document.getElementById('lan-info-box');
    if (box.classList.contains('show')) {
        box.classList.remove('show');
        return;
    }
    try {
        const resp = await fetch('/api/lan-info?person=' + encodeURIComponent(currentPerson));
        const data = await resp.json();
        document.getElementById('lan-url').value = data.url;
        box.classList.add('show');
    } catch(e) { showToast('获取失败: ' + e.message, 'error'); }
}

async function loadPublishState() {
    try {
        const resp = await fetch('/api/publish/config');
        const cfg = await resp.json();
        const url = (cfg.published_urls || {})[currentPerson];
        if (url) {
            document.getElementById('publish-url').value = url;
            document.getElementById('publish-url-box').classList.add('show');
        } else {
            document.getElementById('publish-url-box').classList.remove('show');
        }
    } catch(e) {}
}

// ══════════ BACKUP & RESTORE ══════════
async function doBackup() {
    showToast('正在打包备份...', 'info');
    window.open('/api/backup', '_blank');
}

async function doRestore(input) {
    const file = input.files[0];
    if (!file) return;
    if (!confirm('确定要从备份恢复数据吗？同名人员的数据将被覆盖。')) {
        input.value = '';
        return;
    }
    showToast('正在恢复数据...', 'info');
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch('/api/restore', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.success) {
            showToast('✅ 已恢复 ' + data.count + ' 个人员的数据', 'success');
            await loadPeopleList();
            if (currentPerson) switchPerson(currentPerson);
        } else {
            showToast('恢复失败: ' + data.error, 'error');
        }
    } catch(e) { showToast('网络错误: ' + e.message, 'error'); }
    input.value = '';
}

// ══════════ HUAWEI ZIP IMPORT ══════════
async function importHuaweiZip() {
    const fileInput = document.getElementById('huawei-zip-input');
    const pwdInput  = document.getElementById('huawei-zip-pwd');
    const file = fileInput.files[0];
    if (!file) { showToast('请先选择 ZIP 备份文件', 'error'); return; }
    if (!pwdInput.value) { showToast('请输入解压密码', 'error'); return; }
    if (!currentPerson) { showToast('请先选择一个人员', 'error'); return; }

    const btn = document.getElementById('btn-import-hw');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> 导入中…';

    const progressDiv = document.getElementById('hw-import-progress');
    const logDiv = document.getElementById('hw-import-log');
    const summaryDiv = document.getElementById('hw-import-summary');
    const barEl = document.getElementById('hw-progress-bar');
    const pctEl = document.getElementById('hw-progress-pct');
    const txtEl = document.getElementById('hw-progress-text');

    progressDiv.classList.add('show');
    logDiv.innerHTML = '';
    summaryDiv.style.display = 'none';
    barEl.style.width = '0%';
    txtEl.textContent = '正在上传文件…';
    pctEl.textContent = '0%';

    function addLog(text, cls) {
        const span = document.createElement('div');
        span.className = cls || '';
        span.textContent = text;
        logDiv.appendChild(span);
        logDiv.scrollTop = logDiv.scrollHeight;
    }

    addLog('▶ 开始上传 ' + file.name + ' (' + (file.size / 1048576).toFixed(1) + 'MB)…');
    barEl.style.width = '10%'; pctEl.textContent = '10%';

    const formData = new FormData();
    formData.append('file', file);
    formData.append('password', pwdInput.value);

    try {
        txtEl.textContent = '正在解密并解析…';
        barEl.style.width = '30%'; pctEl.textContent = '30%';

        const resp = await fetch('/api/import-huawei-zip?person=' + encodeURIComponent(currentPerson), {
            method: 'POST', body: formData
        });
        const data = await resp.json();
        barEl.style.width = '90%'; pctEl.textContent = '90%';

        if (data.error) {
            addLog('✖ 错误: ' + data.error, 'log-err');
            showToast('导入失败: ' + data.error, 'error');
            btn.disabled = false;
            btn.innerHTML = '🚀 开始导入';
            return;
        }

        // Display detailed logs
        if (data.parsed_files) {
            data.parsed_files.forEach(f => addLog('  📄 已解析: ' + f, 'log-ok'));
        }
        if (data.skipped_files) {
            data.skipped_files.forEach(f => addLog('  ⏭ 已跳过: ' + f, 'log-skip'));
        }
        if (data.merge_log) {
            data.merge_log.forEach(m => {
                const cls = m.startsWith('新增') ? 'log-ok' : m.startsWith('合并') ? 'log-skip' : '';
                addLog('  ' + m, cls);
            });
        }

        barEl.style.width = '100%'; pctEl.textContent = '100%';
        txtEl.textContent = '导入完成！';

        // Show summary
        const s = data.summary || {};
        const isOk = (s.errors || 0) === 0;
        summaryDiv.style.display = 'block';
        summaryDiv.className = 'import-summary ' + (isOk ? 'ok' : 'partial');
        summaryDiv.innerHTML = `
            <div style="font-weight:600;font-size:14px;margin-bottom:6px;color:${isOk ? 'var(--green)' : 'var(--orange)'}">
                ${isOk ? '✅ 导入成功' : '⚠️ 部分导入成功'}
            </div>
            <div style="font-size:13px;color:var(--text2);line-height:1.8;">
                📊 新增 <b style="color:var(--green)">${s.new_records || 0}</b> 天数据，
                合并更新 <b style="color:var(--cyan)">${s.merged_records || 0}</b> 天数据，
                日期范围: <b>${s.date_range || '—'}</b><br>
                📂 共解析 <b>${s.total_files_parsed || 0}</b> 个文件，
                跳过 <b>${s.total_files_skipped || 0}</b> 个文件
                ${(s.errors || 0) > 0 ? '<br>⚠️ <b style="color:var(--red)">' + s.errors + '</b> 个文件出错' : ''}
            </div>`;

        showToast('✅ 华为备份导入成功: 新增 ' + (s.new_records || 0) + ' 天, 合并 ' + (s.merged_records || 0) + ' 天', 'success');

        // Reload data
        loadDataTable();

    } catch(e) {
        addLog('✖ 网络错误: ' + e.message, 'log-err');
        showToast('导入失败: ' + e.message, 'error');
    }

    btn.disabled = false;
    btn.innerHTML = '🚀 开始导入';
}

// ══════════ INIT ══════════
(async function init() {
    await loadPeopleList();
    if (currentPerson) loadProfile();
})();
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    resp = app.make_response(render_template_string(MAIN_PAGE_HTML))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/dashboard.html")
def serve_dashboard():
    """提供指定人员的仪表盘"""
    person_id = request.args.get("person", "").strip()
    if person_id:
        try:
            dp = get_person_dashboard(person_id)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if dp.exists():
            return send_from_directory(str(dp.parent), dp.name)
    # 兼容：返回模板
    return send_from_directory(str(PROJECT_DIR), "dashboard_template.html")


@app.route("/echarts.min.js")
def serve_echarts():
    return send_from_directory(str(PROJECT_DIR), "echarts.min.js")


# ── 人员管理 API ──

@app.route("/api/people", methods=["GET"])
def api_list_people():
    """获取所有人员列表"""
    people = []
    for pid in list_people():
        jp = get_person_json(pid)
        info = {"id": pid, "name": pid, "records": 0}
        if jp.exists():
            try:
                store = HealthDataStore.load(str(jp))
                info["name"] = store.person_name or pid
                info["records"] = len(store.records)
            except Exception:
                pass
        people.append(info)
    return jsonify(people)


@app.route("/api/people", methods=["POST"])
def api_create_person():
    """新建人员"""
    data = request.get_json()
    if not data or not data.get("name", "").strip():
        return jsonify({"error": "请输入人员名称"}), 400
    name = data["name"].strip()
    try:
        if create_person(name):
            return jsonify({"success": True, "id": name})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"error": f"人员 [{name}] 已存在"}), 409


@app.route("/api/people/<path:person_id>", methods=["DELETE"])
def api_delete_person(person_id):
    """归档删除人员"""
    try:
        if archive_person(person_id):
            return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"error": f"人员 [{person_id}] 不存在"}), 404


@app.route("/api/people/<path:person_id>/rename", methods=["POST"])
def api_rename_person(person_id):
    """重命名人员及其所有关联文件和发布配置"""
    data = request.get_json()
    if not data or not data.get("new_name", "").strip():
        return jsonify({"error": "请输入新的名称"}), 400

    new_name = data["new_name"].strip()
    if not new_name:
        return jsonify({"error": "姓名不能为空"}), 400

    if new_name == person_id:
        return jsonify({"success": True, "id": person_id})

    # 校验是否重名
    new_dir = get_person_dir(new_name)
    if new_dir.exists():
        return jsonify({"error": f"人员 [{new_name}] 已存在"}), 409

    old_dir = get_person_dir(person_id)
    if not old_dir.exists():
        return jsonify({"error": f"人员 [{person_id}] 不存在"}), 404

    try:
        # 1. 物理重命名目录
        import os
        os.rename(str(old_dir), str(new_dir))

        # 2. 读取并修改 JSON 里的 person_name
        store = load_store(new_name)
        store.person_name = new_name
        save_store(store, new_name)

        # 3. 重新生成仪表盘
        regenerate_dashboard(store, new_name)

        # 4. 更新云端发布配置文件中的 Key
        config = load_publish_config()
        sites = config.get("sites", {})
        published_urls = config.get("published_urls", {})

        updated_config = False
        if person_id in sites:
            sites[new_name] = sites.pop(person_id)
            updated_config = True
        if person_id in published_urls:
            published_urls[new_name] = published_urls.pop(person_id)
            updated_config = True

        if updated_config:
            config["sites"] = sites
            config["published_urls"] = published_urls
            save_publish_config(config)

        return jsonify({"success": True, "id": new_name})
    except Exception as e:
        return jsonify({"error": f"重命名失败: {str(e)}"}), 500


# ── 数据 API（需要 ?person= 参数）──

@app.route("/api/extract", methods=["POST"])
def api_extract():
    """上传截图并进行OCR提取 + AI验证"""
    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    if "file" not in request.files:
        return jsonify({"error": "未收到文件"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "文件名为空"}), 400

    # 保存到该人员的位置目录
    try:
        data_dir = get_person_data_dir(person_id)
        safe_name = _safe_filename(file.filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # 查重功能：如果文件名已在已处理列表中，且文件确实存在，则跳过提取以节省 Token 和时间
    store = load_store(person_id)
    if safe_name in store.processed_files and (data_dir / safe_name).exists():
        return jsonify({
            "already_processed": True,
            "filename": safe_name,
            "message": "该图片已成功上传并录入过，已自动跳过（查重过滤）"
        })

    save_path = data_dir / safe_name
    file.save(str(save_path))

    try:
        extractor = QwenVLExtractor()
        result, warnings, verification = extractor.extract_and_verify(save_path)

        # 跨日一致性检查
        store = load_store(person_id)
        consistency_warnings = check_cross_day_consistency(
            result.data, store.records
        )

        return jsonify({
            "extraction": result.data.model_dump(),
            "confidence": result.confidence,
            "notes": result.extraction_notes,
            "warnings": warnings,
            "verification": verification,
            "consistency_warnings": consistency_warnings,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    """确认提取结果并入库"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无数据"}), 400

    person_id = request.args.get("person", "").strip() or data.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    try:
        record = DailyHealthData.model_validate(data["data"])
        filename = data.get("filename", "")

        store = load_store(person_id)
        is_new = store.add_record(record, filename)
        save_store(store, person_id)
        regenerate_dashboard(store, person_id)

        return jsonify({
            "success": True,
            "is_new": is_new,
            "total_records": len(store.records),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile", methods=["GET"])
def api_get_profile():
    """获取个人档案"""
    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400
    try:
        store = load_store(person_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "person_name": store.person_name,
        "profile": store.profile.model_dump(),
    })


@app.route("/api/profile", methods=["POST"])
def api_save_profile():
    """保存个人档案"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无数据"}), 400

    person_id = request.args.get("person", "").strip() or data.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    try:
        store = load_store(person_id)
        store.person_name = data.get("person_name", store.person_name)

        if "profile" in data:
            store.profile = PersonProfile.model_validate(data["profile"])

        save_store(store, person_id)
        regenerate_dashboard(store, person_id)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/records", methods=["GET"])
def api_get_records():
    """获取所有记录"""
    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400
    try:
        store = load_store(person_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify([r.model_dump() for r in store.records])


@app.route("/api/records/<date>", methods=["DELETE"])
def api_delete_record(date):
    """删除指定日期的记录"""
    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    try:
        store = load_store(person_id)
        original_len = len(store.records)
        store.records = [r for r in store.records if r.date != date]

        if len(store.records) == original_len:
            return jsonify({"error": f"未找到 {date} 的记录"}), 404

        save_store(store, person_id)
        regenerate_dashboard(store, person_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 报告下载 API ──

@app.route("/api/report/html")
def api_report_html():
    """下载 HTML 报告（内联 ECharts，可离线查看）"""
    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    dp = get_person_dashboard(person_id)
    if not dp.exists():
        return jsonify({"error": "仪表盘不存在，请先上传数据"}), 404

    try:
        with open(dp, "r", encoding="utf-8") as f:
            html = f.read()

        # 将外部 echarts.min.js 引用替换为内联脚本，确保离线可用
        if ECHARTS_JS.exists():
            with open(ECHARTS_JS, "r", encoding="utf-8") as f:
                echarts_code = f.read()
            html = html.replace(
                '<script src="echarts.min.js"></script>',
                f'<script>{echarts_code}</script>'
            )
            html = html.replace(
                '<script src="/echarts.min.js"></script>',
                f'<script>{echarts_code}</script>'
            )

        from flask import Response
        return Response(
            html,
            mimetype="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="{person_id}_health_report.html"'
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/report/docx")
def api_report_docx():
    """下载 Word 报告"""
    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    store = load_store(person_id)
    if not store.records:
        return jsonify({"error": "暂无数据，请先上传截图"}), 404

    try:
        from report_generator import generate_docx_report
        import tempfile

        # 生成到临时文件
        tmp = Path(tempfile.mktemp(suffix=".docx"))
        generate_docx_report(store, str(tmp))

        from flask import send_file
        return send_file(
            str(tmp),
            as_attachment=True,
            download_name=f"{person_id}_health_report.docx",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    except ImportError:
        return jsonify({"error": "缺少 python-docx 库，请运行: pip install python-docx matplotlib"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 云端发布 API ──

@app.route("/api/publish", methods=["POST"])
def api_publish():
    """一键发布仪表盘到 Netlify 云端"""
    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    config = load_publish_config()
    token = config.get("netlify_token", "").strip()
    if not token:
        return jsonify({"error": "未配置 Netlify Token", "need_token": True}), 400

    # 读取仪表盘 HTML
    try:
        dp = get_person_dashboard(person_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not dp.exists():
        return jsonify({"error": "仪表盘不存在，请先上传数据"}), 404

    with open(dp, "r", encoding="utf-8") as f:
        html_content = f.read()

    html_bytes = html_content.encode("utf-8")
    sha1 = hashlib.sha1(html_bytes).hexdigest()

    try:
        sites = config.get("sites", {})
        site_id = sites.get(person_id)

        # 首次发布：创建 Netlify 站点
        if not site_id:
            import random
            import string as _string
            suffix = ''.join(random.choices(_string.ascii_lowercase + _string.digits, k=8))
            site_name = f"health-rpt-{suffix}"
            result = _netlify_api("POST", "/sites", token, {"name": site_name})
            site_id = result["id"]
            sites[person_id] = site_id
            config["sites"] = sites
            save_publish_config(config)

        # 创建部署
        deploy = _netlify_api(
            "POST", f"/sites/{site_id}/deploys", token,
            {"files": {"/index.html": sha1}}
        )

        deploy_id = deploy["id"]
        required = deploy.get("required", [])

        # 上传文件（如果 Netlify 还没有此版本）
        if sha1 in required:
            _netlify_api(
                "PUT", f"/deploys/{deploy_id}/files/index.html",
                token, raw_body=html_bytes
            )

        url = deploy.get("ssl_url") or deploy.get("url", "")

        # 保存已发布的 URL
        config.setdefault("published_urls", {})[person_id] = url
        save_publish_config(config)

        return jsonify({"success": True, "url": url})

    except Exception as e:
        return jsonify({"error": f"发布失败: {str(e)}"}), 500


@app.route("/api/publish/config", methods=["GET", "POST"])
def api_publish_config():
    """获取或设置 Netlify Token"""
    config = load_publish_config()

    if request.method == "GET":
        token = config.get("netlify_token", "")
        return jsonify({
            "has_token": bool(token),
            "published_urls": config.get("published_urls", {}),
        })

    # POST: 保存 token
    data = request.get_json()
    if not data or not data.get("token", "").strip():
        return jsonify({"error": "Token 不能为空"}), 400

    config["netlify_token"] = data["token"].strip()
    save_publish_config(config)
    return jsonify({"success": True})


@app.route("/api/lan-info")
def api_lan_info():
    """获取局域网访问信息"""
    ip = get_lan_ip()
    person_id = request.args.get("person", "").strip()
    port = request.host.split(":")[-1] if ":" in request.host else "8080"
    url = f"http://{ip}:{port}"
    if person_id:
        url += f"/dashboard.html?person={person_id}"
    return jsonify({"ip": ip, "port": port, "url": url})


# ── 备份与恢复 API ──

@app.route("/api/backup")
def api_backup():
    """备份全部人员数据为 zip 下载"""
    from flask import Response

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for pid in list_people():
            person_dir = get_person_dir(pid)
            # 打包 health_data.json
            json_path = person_dir / "health_data.json"
            if json_path.exists():
                zf.write(str(json_path), f"{pid}/health_data.json")
            # 打包 data/ 目录下的截图
            data_dir = person_dir / "data"
            if data_dir.exists():
                for fpath in data_dir.iterdir():
                    if fpath.is_file():
                        zf.write(str(fpath), f"{pid}/data/{fpath.name}")
    buf.seek(0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="health_backup_{ts}.zip"'
        }
    )


@app.route("/api/restore", methods=["POST"])
def api_restore():
    """从上传的 zip 恢复数据（合并覆盖）"""
    if "file" not in request.files:
        return jsonify({"error": "未收到文件"}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "请上传 .zip 文件"}), 400

    try:
        data = file.read()
        buf = io.BytesIO(data)
        affected_people = set()
        skipped = []

        with zipfile.ZipFile(buf, "r") as zf:
            for info in zf.infolist():
                # 跳过目录条目
                if info.is_dir():
                    continue

                name = info.filename.replace("\\", "/")

                # ── zip-slip 防护 ──
                # 拒绝绝对路径
                if name.startswith("/") or ":" in name:
                    continue
                # 拒绝路径穿越
                parts = name.split("/")
                if any(p in (".", "..") for p in parts):
                    continue
                # 只允许 <person_id>/health_data.json 或 <person_id>/data/<file>
                if len(parts) == 2 and parts[1] == "health_data.json":
                    pass
                elif len(parts) == 3 and parts[1] == "data":
                    pass
                else:
                    continue

                person_id = parts[0]
                # 校验 person_id 合法性
                try:
                    _safe_person_id(person_id)
                except ValueError:
                    continue

                content = zf.read(info)

                # health_data.json 内容校验：坏数据不写入，避免污染页面
                if parts[-1] == "health_data.json":
                    try:
                        HealthDataStore.model_validate_json(content.decode("utf-8"))
                    except Exception:
                        skipped.append(name)
                        continue

                # 确定目标路径
                dest = PEOPLE_DIR / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "wb") as dst:
                    dst.write(content)

                affected_people.add(person_id)

        # 为受影响的人员重新生成仪表盘
        for pid in affected_people:
            try:
                store = load_store(pid)
                regenerate_dashboard(store, pid)
            except Exception:
                pass

        return jsonify({
            "success": True,
            "restored_people": sorted(affected_people),
            "count": len(affected_people),
            "skipped": skipped,
        })

    except zipfile.BadZipFile:
        return jsonify({"error": "无效的 zip 文件"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
# HUAWEI ZIP IMPORT
# ══════════════════════════════════════════════════════════════

@app.route("/api/import-huawei-zip", methods=["POST"])
def api_import_huawei_zip():
    """导入华为运动健康加密备份 ZIP 文件

    解密 AES-256 加密的华为备份 → 在内存中解析 JSON 健康数据文件
    → 提取每日步数/心率/血氧/睡眠 → 增量合并到 HealthDataStore
    """
    import pyzipper
    import traceback

    person_id = request.args.get("person", "").strip()
    if not person_id:
        return jsonify({"error": "缺少 person 参数"}), 400

    if "file" not in request.files:
        return jsonify({"error": "未收到文件"}), 400

    password = request.form.get("password", "").strip()
    if not password:
        return jsonify({"error": "请提供解压密码"}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "请上传 .zip 格式的备份文件"}), 400

    # ── 读入内存 ──
    try:
        zip_bytes = io.BytesIO(file.read())
    except Exception as e:
        return jsonify({"error": f"读取文件失败: {e}"}), 400

    # ── 解密解压 ──
    parsed_files = []
    skipped_files = []
    error_files = []
    all_daily_records = {}  # date -> DailyHealthData fields dict

    try:
        with pyzipper.AESZipFile(zip_bytes, 'r') as zf:
            zf.setpassword(password.encode('utf-8'))
            namelist = zf.namelist()

            # 筛选可能包含健康数据的 JSON 文件
            # 华为导出结构: HealthApp/MotionPath/*.json, HealthApp/HeartRate/*.json, etc.
            json_files = [n for n in namelist if n.lower().endswith('.json') and not n.startswith('__MACOSX')]

            if not json_files:
                return jsonify({"error": "ZIP 中未找到 JSON 健康数据文件。请确认这是华为运动健康的备份文件。"}), 400

            for jf_name in json_files:
                try:
                    raw = zf.read(jf_name)
                    text = raw.decode('utf-8', errors='replace')
                    data = json.loads(text)
                except Exception:
                    skipped_files.append(jf_name)
                    continue

                # ── 解析华为健康数据 JSON 结构 ──
                extracted = _parse_huawei_json(jf_name, data)
                if not extracted:
                    skipped_files.append(jf_name)
                    continue

                parsed_files.append(jf_name)
                # 合并到 all_daily_records
                for date_str, fields in extracted.items():
                    if date_str not in all_daily_records:
                        all_daily_records[date_str] = {}
                    # 智能合并：只覆盖非 None 的新字段
                    for k, v in fields.items():
                        if v is not None:
                            all_daily_records[date_str][k] = v

    except RuntimeError as e:
        err_msg = str(e)
        if 'password' in err_msg.lower() or 'Bad password' in err_msg:
            return jsonify({"error": "解压密码错误，请核实华为发送的密码邮件"}), 400
        return jsonify({"error": f"解压失败: {err_msg}"}), 400
    except Exception as e:
        return jsonify({"error": f"解压失败: {e}"}), 500

    if not all_daily_records:
        return jsonify({"error": "成功解压但未能从中提取到有效的健康数据。可能此备份不包含运动健康数据。"}), 400

    # ── 合并入 HealthDataStore ──
    store = load_store(person_id)
    merge_log = []
    new_count = 0
    merged_count = 0

    for date_str in sorted(all_daily_records.keys()):
        fields = all_daily_records[date_str]
        fields['date'] = date_str
        try:
            record = DailyHealthData.model_validate(fields)
        except Exception as e:
            error_files.append(f"{date_str}: {e}")
            continue

        # 检查是否已有同日数据 — 智能合并
        existing_idx = None
        for i, existing in enumerate(store.records):
            if existing.date == date_str:
                existing_idx = i
                break

        if existing_idx is not None:
            # 已有数据：合并（仅填补 None 字段）
            old = store.records[existing_idx]
            old_dict = old.model_dump()
            updated = False
            for k, v in record.model_dump().items():
                if k == 'date':
                    continue
                if v is not None and old_dict.get(k) is None:
                    old_dict[k] = v
                    updated = True
            if updated:
                store.records[existing_idx] = DailyHealthData.model_validate(old_dict)
                merged_count += 1
                merge_log.append(f"合并补全 {date_str}")
            else:
                merge_log.append(f"跳过 {date_str}（已有完整数据）")
        else:
            store.records.append(record)
            new_count += 1
            merge_log.append(f"新增 {date_str}")

    # 排序并保存
    store.records.sort(key=lambda r: r.date)
    store.last_updated = datetime.now().isoformat()
    save_store(store, person_id)
    regenerate_dashboard(store, person_id)

    # 日期范围
    dates = sorted(all_daily_records.keys())
    date_range = f"{dates[0]} ~ {dates[-1]}" if dates else "—"

    return jsonify({
        "success": True,
        "parsed_files": parsed_files,
        "skipped_files": skipped_files,
        "merge_log": merge_log,
        "summary": {
            "new_records": new_count,
            "merged_records": merged_count,
            "total_files_parsed": len(parsed_files),
            "total_files_skipped": len(skipped_files),
            "errors": len(error_files),
            "date_range": date_range,
        }
    })


def _parse_huawei_json(filename: str, data) -> dict:
    """解析华为运动健康导出的 JSON 文件，返回 {date_str: {field: value}} 字典。

    支持的华为数据结构：
    1. 步数/运动: MotionPath / motion_data
    2. 心率: HeartRate / heart_rate_data
    3. 血氧: BloodOxygen / spo2_data
    4. 睡眠: Sleep / sleep_data
    5. 通用列表格式: [{"dateTime":..., "value":...}]
    """
    result = {}  # date_str -> fields dict
    fname_lower = filename.lower()

    try:
        # ── 处理华为健康数据的多种可能的 JSON 结构 ──

        # 情况 A: 顶层直接是列表 [{...}, ...]
        if isinstance(data, list):
            for item in data:
                _extract_item(item, fname_lower, result)
            return result if result else None

        # 情况 B: 顶层是字典，包含 data / records / items / values 等常见键
        if isinstance(data, dict):
            # 尝试从常见的数据键中获取列表
            for key in ('data', 'records', 'items', 'values', 'dataList',
                        'heartRate', 'heartRateData', 'heart_rate',
                        'stepCount', 'step', 'steps',
                        'bloodOxygen', 'spo2', 'spO2',
                        'sleep', 'sleepData', 'sleepInfo',
                        'motionPath', 'sportData', 'exercise'):
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        _extract_item(item, fname_lower, result)
                    if result:
                        return result

            # 尝试将整个 dict 当作单条数据解析
            _extract_item(data, fname_lower, result)
            return result if result else None

    except Exception:
        return None

    return None


def _extract_item(item: dict, fname_lower: str, result: dict):
    """从单个数据项中提取健康指标并按日期聚合到 result"""
    if not isinstance(item, dict):
        return

    # ── 提取日期 ──
    date_str = None
    for dkey in ('dateTime', 'date', 'startTime', 'start_time',
                 'recordDate', 'time', 'timestamp', 'measureTime',
                 'endTime', 'end_time', 'day'):
        raw = item.get(dkey)
        if raw:
            date_str = _parse_date_str(str(raw))
            if date_str:
                break

    if not date_str:
        return

    if date_str not in result:
        result[date_str] = {}
    fields = result[date_str]

    # ── 根据文件名或数据内容推断指标类型 ──

    # 步数相关
    if any(kw in fname_lower for kw in ('step', 'motion', 'walk', 'sport', 'exercise')):
        for vkey in ('value', 'steps', 'stepCount', 'step_count', 'count', 'totalSteps'):
            v = item.get(vkey)
            if v is not None:
                try:
                    val = int(float(str(v)))
                    if 0 <= val <= 200000:
                        fields['steps'] = max(fields.get('steps') or 0, val)
                except (ValueError, TypeError):
                    pass
                break
        # 距离
        for dkey in ('distance', 'totalDistance', 'total_distance'):
            v = item.get(dkey)
            if v is not None:
                try:
                    val = round(float(str(v)) / 1000, 2) if float(str(v)) > 100 else round(float(str(v)), 2)  # m->km or already km
                    if 0 <= val <= 200:
                        fields['distance_km'] = max(fields.get('distance_km') or 0, val)
                except (ValueError, TypeError):
                    pass
                break
        # 锻炼时长
        for ekey in ('duration', 'exerciseTime', 'exercise_time', 'sportTime'):
            v = item.get(ekey)
            if v is not None:
                try:
                    val = int(float(str(v)))
                    # 可能是秒或分钟
                    if val > 1440:  # > 24h in minutes, probably seconds
                        val = val // 60
                    if 0 <= val <= 1440:
                        fields['exercise_minutes'] = (fields.get('exercise_minutes') or 0) + val
                except (ValueError, TypeError):
                    pass
                break

    # 心率相关
    elif any(kw in fname_lower for kw in ('heart', 'hr', 'pulse', 'heartrate')):
        for vkey in ('value', 'heartRate', 'heart_rate', 'hr', 'bpm', 'rate'):
            v = item.get(vkey)
            if v is not None:
                try:
                    val = int(float(str(v)))
                    if 30 <= val <= 250:
                        cur_min = fields.get('heart_rate_min')
                        cur_max = fields.get('heart_rate_max')
                        fields['heart_rate_min'] = min(cur_min, val) if cur_min is not None else val
                        fields['heart_rate_max'] = max(cur_max, val) if cur_max is not None else val
                except (ValueError, TypeError):
                    pass
                break
        # 静息心率
        for rkey in ('restingHeartRate', 'resting_heart_rate', 'restHr', 'rhr'):
            v = item.get(rkey)
            if v is not None:
                try:
                    val = int(float(str(v)))
                    if 30 <= val <= 150:
                        fields['resting_heart_rate'] = val
                except (ValueError, TypeError):
                    pass
                break

    # 血氧相关
    elif any(kw in fname_lower for kw in ('oxygen', 'spo2', 'blood')):
        for vkey in ('value', 'spo2', 'spO2', 'bloodOxygen', 'saturation', 'oxygenSaturation'):
            v = item.get(vkey)
            if v is not None:
                try:
                    val = int(float(str(v)))
                    if 50 <= val <= 100:
                        cur_min = fields.get('spo2_min')
                        cur_max = fields.get('spo2_max')
                        fields['spo2_min'] = min(cur_min, val) if cur_min is not None else val
                        fields['spo2_max'] = max(cur_max, val) if cur_max is not None else val
                except (ValueError, TypeError):
                    pass
                break

    # 睡眠相关
    elif any(kw in fname_lower for kw in ('sleep',)):
        # 总时长
        for tkey in ('totalTime', 'total_time', 'duration', 'sleepTime', 'sleep_time', 'totalSleepTime'):
            v = item.get(tkey)
            if v is not None:
                try:
                    val = float(str(v))
                    # 可能是分钟或小时
                    if val > 24:  # probably minutes
                        val = round(val / 60, 2)
                    if 0 < val <= 24:
                        fields['sleep_hours'] = val
                except (ValueError, TypeError):
                    pass
                break
        # 睡眠分数
        for skey in ('score', 'sleepScore', 'sleep_score', 'quality'):
            v = item.get(skey)
            if v is not None:
                try:
                    val = int(float(str(v)))
                    if 0 <= val <= 100:
                        fields['sleep_score'] = val
                except (ValueError, TypeError):
                    pass
                break
        # 入睡/醒来时间
        for st_key in ('bedTime', 'bed_time', 'fallAsleepTime', 'sleepStartTime'):
            v = item.get(st_key)
            if v:
                hm = _extract_hm(str(v))
                if hm:
                    fields['sleep_start'] = hm
                break
        for et_key in ('wakeTime', 'wake_time', 'wakeUpTime', 'sleepEndTime', 'riseTime'):
            v = item.get(et_key)
            if v:
                hm = _extract_hm(str(v))
                if hm:
                    fields['sleep_end'] = hm
                break

    # 通用兜底：尝试通过字段名自动推断
    else:
        _generic_extract(item, fields)


def _parse_date_str(raw: str) -> str | None:
    """尝试将多种日期格式解析为 YYYY-MM-DD"""
    import re
    raw = raw.strip()

    # Unix 时间戳（毫秒）
    if raw.isdigit() and len(raw) >= 13:
        try:
            dt = datetime.fromtimestamp(int(raw) / 1000)
            return dt.strftime('%Y-%m-%d')
        except Exception:
            pass

    # Unix 时间戳（秒）
    if raw.isdigit() and 9 <= len(raw) <= 12:
        try:
            dt = datetime.fromtimestamp(int(raw))
            return dt.strftime('%Y-%m-%d')
        except Exception:
            pass

    # 常见日期格式
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S%z',
                '%Y/%m/%d', '%Y%m%d', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            dt = datetime.strptime(raw[:len(raw)].split('+')[0].split('Z')[0].strip(), fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue

    # 正则兜底
    m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return None


def _extract_hm(raw: str) -> str | None:
    """从时间字符串中提取 HH:MM"""
    import re
    m = re.search(r'(\d{1,2}):(\d{2})', raw)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
    # Unix timestamp
    if raw.isdigit() and len(raw) >= 10:
        try:
            ts = int(raw) / 1000 if len(raw) >= 13 else int(raw)
            dt = datetime.fromtimestamp(ts)
            return dt.strftime('%H:%M')
        except Exception:
            pass
    return None


def _generic_extract(item: dict, fields: dict):
    """通用兜底提取：根据键名推断指标类型"""
    for k, v in item.items():
        if v is None:
            continue
        kl = k.lower()
        try:
            if any(w in kl for w in ('step', 'steps')):
                val = int(float(str(v)))
                if 0 <= val <= 200000:
                    fields.setdefault('steps', val)
            elif kl in ('heartrate', 'heart_rate', 'hr', 'bpm'):
                val = int(float(str(v)))
                if 30 <= val <= 250:
                    fields.setdefault('heart_rate_min', val)
                    fields.setdefault('heart_rate_max', val)
            elif kl in ('restingheartrate', 'resting_heart_rate', 'rhr'):
                val = int(float(str(v)))
                if 30 <= val <= 150:
                    fields.setdefault('resting_heart_rate', val)
            elif any(w in kl for w in ('spo2', 'oxygen', 'saturation')):
                val = int(float(str(v)))
                if 50 <= val <= 100:
                    fields.setdefault('spo2_min', val)
                    fields.setdefault('spo2_max', val)
            elif any(w in kl for w in ('sleephour', 'sleep_hour', 'sleeptime', 'sleep_time')):
                val = float(str(v))
                if val > 24:
                    val = round(val / 60, 2)
                if 0 < val <= 24:
                    fields.setdefault('sleep_hours', val)
        except (ValueError, TypeError):
            continue


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import webbrowser
    import threading

    # 自动为所有已存在人员重新生成仪表盘以应用模板更改
    for pid in list_people():
        try:
            store = load_store(pid)
            regenerate_dashboard(store, pid)
        except Exception as e:
            print(f"⚠️ 无法为 {pid} 自动重新生成仪表盘: {e}")

    port = 8080
    print(f"🏥 健康数据管理中心（多人版）")
    print(f"   地址: http://localhost:{port}")
    print(f"   人员: {list_people() or ['（暂无，请新建）']}")
    print(f"   按 Ctrl+C 停止")

    # 自动打开浏览器
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    app.run(host="0.0.0.0", port=port, debug=False)

