"""
华为家庭空间健康数据分析系统 — 主程序入口
==========================================

统一的命令行工具，支持：
  - extract  : 从截图中OCR提取数据
  - dashboard : 生成/更新交互式HTML仪表盘
  - all      : 完整流程（提取 + 生成仪表盘）
  - add      : 添加新截图文件到data目录并提取

用法:
    python run_analysis.py extract          # 提取截图中的数据
    python run_analysis.py dashboard        # 用已有数据生成仪表盘
    python run_analysis.py all              # 完整流程
    python run_analysis.py add <图片路径>    # 添加新截图
"""

import os
import sys
import json
import shutil
import argparse
import re
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
JSON_PATH = PROJECT_DIR / "health_data.json"
DASHBOARD_PATH = PROJECT_DIR / "dashboard.html"
TEMPLATE_PATH = PROJECT_DIR / "dashboard.html"


def cmd_extract(args):
    """从截图目录提取健康数据"""
    from extract_health_data import scan_and_extract
    
    scan_and_extract(
        data_dir=args.data_dir,
        json_path=args.json_path,
        force=args.force,
    )


def cmd_dashboard(args):
    """用已有JSON数据生成/更新HTML仪表盘"""
    json_path = Path(args.json_path)
    
    if not json_path.exists():
        print(f"❌ 数据文件不存在: {json_path}")
        print("   请先运行: python run_analysis.py extract")
        sys.exit(1)

    # 读取数据
    with open(json_path, 'r', encoding='utf-8') as f:
        health_data = json.load(f)

    records = health_data.get('records', [])
    if not records:
        print("❌ 数据为空，无法生成仪表盘")
        sys.exit(1)

    print(f"📊 加载了 {len(records)} 条健康记录")
    print(f"   日期范围: {records[0]['date']} ~ {records[-1]['date']}")

    # 读取 HTML 模板
    if not TEMPLATE_PATH.exists():
        print(f"❌ 仪表盘模板文件不存在: {TEMPLATE_PATH}")
        sys.exit(1)

    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # 替换数据占位符
    data_json = json.dumps(health_data, ensure_ascii=False)
    
    # 替换 /*__DATA_PLACEHOLDER__*/ ... /*__DATA_END__*/ 之间的内容
    pattern = r'/\*__DATA_PLACEHOLDER__\*/.*?/\*__DATA_END__\*/'
    replacement = f'/*__DATA_PLACEHOLDER__*/{data_json}/*__DATA_END__*/'
    
    new_html = re.sub(pattern, replacement, html_content, flags=re.DOTALL)

    # 写入
    output_path = Path(args.output) if args.output else DASHBOARD_PATH
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(new_html)

    print(f"✅ 仪表盘已生成: {output_path}")
    print(f"   在浏览器中打开即可查看交互式图表")

    # 自动打开浏览器（可选）
    if args.open:
        import webbrowser
        webbrowser.open(str(output_path.resolve()))
        print("🌐 已在浏览器中打开")


def cmd_all(args):
    """完整流程：提取 + 生成仪表盘"""
    print("=" * 60)
    print("🔄 步骤 1/2: 从截图中提取数据")
    print("=" * 60)
    cmd_extract(args)

    print()
    print("=" * 60)
    print("🔄 步骤 2/2: 生成交互式仪表盘")
    print("=" * 60)
    cmd_dashboard(args)


def cmd_add(args):
    """添加新截图文件到data目录并提取"""
    src_path = Path(args.image_path)

    if not src_path.exists():
        print(f"❌ 文件不存在: {src_path}")
        sys.exit(1)

    # 复制到 data 目录
    DATA_DIR.mkdir(exist_ok=True)
    dst_path = DATA_DIR / src_path.name

    if dst_path.exists():
        print(f"⚠️ 文件已存在: {dst_path}")
        if not args.force:
            print("   使用 --force 覆盖")
            return
    
    shutil.copy2(src_path, dst_path)
    print(f"📋 已复制截图到: {dst_path}")

    # 提取这张新图片
    from extract_health_data import QwenVLExtractor, HealthDataStore

    json_path = Path(args.json_path)
    if json_path.exists():
        store = HealthDataStore.load(str(json_path))
    else:
        store = HealthDataStore()

    extractor = QwenVLExtractor()

    try:
        result = extractor.extract_from_image(dst_path)
        warnings = extractor.validate_extraction(result.data)
        
        if warnings:
            print("⚠️ 数据校验警告:")
            for w in warnings:
                print(f"   {w}")

        is_new = store.add_record(result.data, dst_path.name)
        store.save(str(json_path))
        
        status = "新增" if is_new else "更新"
        print(f"✅ 提取成功 ({status}): {result.data.date}")
        print(f"   步数: {result.data.steps}, 睡眠: {result.data.sleep_hours}h")

        # 自动更新仪表盘
        if not args.no_dashboard:
            print("\n🔄 自动更新仪表盘...")
            args.output = None
            args.open = False
            cmd_dashboard(args)

    except Exception as e:
        print(f"❌ 提取失败: {str(e)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="华为家庭空间健康数据分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_analysis.py extract            # 批量提取截图数据
  python run_analysis.py dashboard --open   # 生成仪表盘并打开
  python run_analysis.py all                # 完整流程
  python run_analysis.py add photo.jpg      # 添加并提取新截图
        """,
    )

    # 全局参数
    parser.add_argument('--json-path', type=str, default=str(JSON_PATH),
                        help='JSON数据文件路径')
    parser.add_argument('--force', action='store_true',
                        help='强制重新执行')

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # extract
    p_extract = subparsers.add_parser('extract', help='从截图中OCR提取数据')
    p_extract.add_argument('--data-dir', type=str, default=str(DATA_DIR))

    # dashboard
    p_dashboard = subparsers.add_parser('dashboard', help='生成交互式HTML仪表盘')
    p_dashboard.add_argument('--output', type=str, default=None,
                             help='输出HTML文件路径（默认覆盖 dashboard.html）')
    p_dashboard.add_argument('--open', action='store_true',
                             help='生成后自动在浏览器中打开')

    # all
    p_all = subparsers.add_parser('all', help='完整流程：提取 + 生成仪表盘')
    p_all.add_argument('--data-dir', type=str, default=str(DATA_DIR))
    p_all.add_argument('--output', type=str, default=None)
    p_all.add_argument('--open', action='store_true')

    # add
    p_add = subparsers.add_parser('add', help='添加新截图文件并提取')
    p_add.add_argument('image_path', type=str, help='截图文件路径')
    p_add.add_argument('--no-dashboard', action='store_true',
                        help='添加后不自动更新仪表盘')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 设置默认值
    if not hasattr(args, 'data_dir'):
        args.data_dir = str(DATA_DIR)
    if not hasattr(args, 'output'):
        args.output = None
    if not hasattr(args, 'open'):
        args.open = False
    if not hasattr(args, 'no_dashboard'):
        args.no_dashboard = False

    commands = {
        'extract': cmd_extract,
        'dashboard': cmd_dashboard,
        'all': cmd_all,
        'add': cmd_add,
    }

    print(f"🏥 华为家庭空间健康数据分析系统")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    commands[args.command](args)


if __name__ == "__main__":
    main()
