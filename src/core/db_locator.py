# -*- coding: utf-8 -*-
"""
微信 4.x 数据库智能寻址模块

【实现逻辑】：
不单纯依赖 Windows 注册表或用户的「文档」目录，解决微信修改文件存储位置后找不到数据库的痛点：
1. 优先校验手动配置的路径（若有效直接返回）；
2. 通过 psutil 反射当前运行中的微信主进程（WeChat.exe/Weixin.exe）正在打开的文件句柄，
   通过正则直接提取微信数据目录基准路径（最精准、最可靠）；
3. 枚举当前系统中所有物理磁盘、网络挂载盘（A~Z），自动扫描常见微信数据根目录名（如 xwechat_files 等）；
4. 深度兼容 4 种常见数据目录布局（纯根目录、带账号层级、直接指定账号目录、直接指定 db_storage）。
"""

import os
import re
import string
import sys
from typing import List, Optional

# Windows 终端中文编码兼容处理
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 微信 4.x 数据目录的常见名字
DB_ROOT_NAMES = ("xwechat_files", "WeChat Files", "xwechat_files_data")


def looks_like_db_root(p: str) -> bool:
    """
    检查路径 p 是否符合微信 4.x 数据库目录特征。

    兼容以下四种常见布局：
    1. E:\\xwechat_files\\<账号>\\db_storage  （标准多账号根目录）
    2. E:\\xwechat_files\\db_storage         （账号目录层级被拍平）
    3. 直填账号目录：p\\db_storage
    4. 直填 db_storage 目录本身
    """
    if not p or not os.path.isdir(p):
        return False

    # 情况 3：直接指定了账号目录（其下有 db_storage）
    if os.path.isdir(os.path.join(p, "db_storage")):
        return True

    # 情况 4：直接指定了 db_storage 目录本身
    if os.path.basename(os.path.normpath(p)).lower() == "db_storage":
        return True

    # 情况 1 & 2：指定的是外层根目录，向下寻找账号目录或 db_storage
    bases = [p]
    for name in DB_ROOT_NAMES:
        bases.append(os.path.join(p, name))

    for base in bases:
        if not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for name in entries:
            target = os.path.join(base, name, "db_storage")
            if os.path.isdir(target):
                return True

    return False


def iter_drive_roots() -> List[str]:
    """
    动态获取系统中所有真实存在的磁盘根路径。
    不仅枚举 A~Z，还通过 psutil 补充网络映射盘、移动设备和 UNC 挂载点。
    """
    roots = []
    # 1. 扫描 A~Z 物理盘符
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.isdir(root):
            roots.append(root)

    # 2. 补充 psutil 检测到的其他挂载点
    try:
        import psutil
        for part in psutil.disk_partitions(all=False):
            mp = str(part.mountpoint or "")
            if mp and mp not in roots and os.path.isdir(mp):
                roots.append(mp)
    except Exception:
        pass

    return roots


def normalize_db_dir(p: str) -> str:
    """
    规整数据根目录：
    如果用户传入或反射定位到了上一层目录（例如包含 xwechat_files 等），
    自动探测下钻到真实存放各账号文件夹的数据根目录。
    """
    if not p or not os.path.isdir(p):
        return p

    # 1. 如果其下直接有账号目录包含 db_storage，说明本身就是有效数据根目录
    try:
        for name in os.listdir(p):
            if os.path.isdir(os.path.join(p, name, "db_storage")):
                return p
    except OSError:
        pass

    # 2. 如果其下有 xwechat_files 等子目录，且子目录下有账号目录包含 db_storage，自动下钻
    for name in DB_ROOT_NAMES:
        sub = os.path.join(p, name)
        if os.path.isdir(sub):
            try:
                for sub_name in os.listdir(sub):
                    if os.path.isdir(os.path.join(sub, sub_name, "db_storage")):
                        return sub
            except OSError:
                pass

    return p


def resolve_db_dir(config_db_dir: Optional[str] = None, verbose: bool = True) -> str:
    """
    核心寻址函数：
    智能寻找微信 4.x 的数据库目录。

    寻址优先级：
    1. 手动配置路径 (config_db_dir)
    2. 微信进程打开的文件反查 (psutil open_files)
    3. 系统所有磁盘根目录扫描 (iter_drive_roots)
    """
    # 1. 优先校验手动配置路径
    if config_db_dir and looks_like_db_root(config_db_dir):
        resolved = normalize_db_dir(config_db_dir)
        if verbose:
            print(f"[寻址命中] 使用手动配置的数据库目录: {resolved}")
        return resolved

    # 2. 检查正在运行的微信进程打开的文件句柄（最高效且最准确）
    try:
        import psutil
        for proc in psutil.process_iter(["name", "pid"]):
            name = str(proc.info.get("name") or "").lower()
            if not any(k in name for k in ("weixin", "wechat")):
                continue

            try:
                open_files = proc.open_files()
            except Exception:
                continue

            for item in open_files:
                fpath = item.path or ""
                # 如果句柄路径中包含 db_storage，直接从目录层级结构精准定位
                # 例如 .../xwechat_files/wxid_xxx/db_storage/...
                fpath_lower = fpath.lower()
                if "db_storage" in fpath_lower:
                    idx = fpath_lower.rfind("db_storage")
                    acct_dir = fpath[:idx].rstrip("/\\")
                    root_cand = os.path.dirname(acct_dir)
                    if looks_like_db_root(root_cand):
                        root_cand = normalize_db_dir(root_cand)
                        if verbose:
                            print(f"[寻址命中] 通过微信进程(PID={proc.info.get('pid')})句柄反射发现: {root_cand}")
                        return root_cand

                # 兜底正则匹配路径中的 xwechat_files 等关键词
                m = re.search(
                    r"([\\/])(" + "|".join(DB_ROOT_NAMES) + r")([\\/]|$)",
                    fpath,
                    re.IGNORECASE,
                )
                if not m:
                    continue

                root_candidate = fpath[: m.start() + 1] + m.group(2)
                if looks_like_db_root(root_candidate):
                    root_candidate = normalize_db_dir(root_candidate)
                    if verbose:
                        print(f"[寻址命中] 通过微信进程(PID={proc.info.get('pid')})句柄反射发现: {root_candidate}")
                    return root_candidate
    except Exception as e:
        if verbose:
            print(f"[寻址提示] 进程反射探测未完成: {e}")

    # 3. 扫描各磁盘根目录
    for root in iter_drive_roots():
        for name in DB_ROOT_NAMES:
            cand = os.path.join(root, name)
            if looks_like_db_root(cand):
                cand = normalize_db_dir(cand)
                if verbose:
                    print(f"[寻址命中] 磁盘深度扫描发现数据根目录: {cand}")
                return cand

    if verbose:
        print("[寻址警告] 未能自动定位到微信 4.x 数据目录，请确认微信是否已登录并生成了 db_storage。")
    return ""


def find_all_accounts(db_dir: Optional[str] = None) -> List[dict]:
    """
    枚举指定微信数据根目录下所有真实存在的账号目录，
    并通过 psutil 反查与每个账号关联的运行中 Weixin.exe 进程 PID。

    返回列表元素格式：
    {
        "account": "wxid_5o4m2m35b31w22_f8c6",
        "account_dir": "D:\\hc\\xwechat_files\\wxid_5o4m2m35b31w22_f8c6",
        "pid": 16064,
        "is_running": True
    }
    """
    target_dir = db_dir or resolve_db_dir(verbose=False)
    if not target_dir or not os.path.isdir(target_dir):
        return []

    target_dir = normalize_db_dir(target_dir)
    target_dir_norm = os.path.normcase(os.path.abspath(target_dir))

    # 1. 扫描当前运行中微信进程打开的文件句柄，建立 账号名 -> PID 映射
    pids_by_acct = {}
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name"]):
            name = str(proc.info.get("name") or "").lower()
            if any(k in name for k in ("weixin", "wechat")):
                pid = proc.info.get("pid")
                try:
                    for f in proc.open_files():
                        fpath = os.path.normcase(os.path.abspath(f.path or ""))
                        if target_dir_norm in fpath and "db_storage" in fpath:
                            rel = os.path.relpath(fpath, target_dir_norm)
                            parts = rel.split(os.sep)
                            if len(parts) >= 1:
                                acct_folder = parts[0]
                                pids_by_acct[acct_folder] = pid
                                break
                except Exception:
                    pass
    except Exception:
        pass

    # 2. 列举包含 db_storage 的有效账号目录
    results = []
    try:
        for name in os.listdir(target_dir):
            storage_path = os.path.join(target_dir, name, "db_storage")
            if os.path.isdir(storage_path):
                pid = pids_by_acct.get(name)
                results.append({
                    "account": name,
                    "account_dir": os.path.join(target_dir, name),
                    "pid": pid,
                    "is_running": (pid is not None)
                })
    except Exception:
        pass

    # 如果根目录本身就是拍平的单个账号目录（直接包含 db_storage）
    if not results and os.path.isdir(os.path.join(target_dir, "db_storage")):
        acct_name = os.path.basename(os.path.normpath(target_dir))
        results.append({
            "account": acct_name,
            "account_dir": target_dir,
            "pid": None,
            "is_running": True
        })

    return results


if __name__ == "__main__":
    print("=" * 60)
    print("测试微信 4.x 数据库智能寻址功能")
    print("=" * 60)
    db_path = resolve_db_dir(verbose=True)
    if db_path:
        print(f"\n[成功] 最终获取的数据库目录为:\n  -> {db_path}")
    else:
        print("\n[失败] 未能找到数据库目录。请确认微信 4.x 是否已登录。")
