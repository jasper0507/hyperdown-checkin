#!/usr/bin/env python3
"""Hyperdown daily auto check-in.

Usage:
  cp config.example.toml config.toml   # fill email/password
  python3 checkin.py                  # login + check-in
  python3 checkin.py --login-only
  python3 checkin.py --me-only
  python3 checkin.py --probe-secure   # try KDF/wire variants (debug)

Exit codes:
  0 success or already checked in
  1 config error
  2 auth error
  3 check-in / secure API error
  4 network error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore

from client import APIError, HyperdownClient, TokenPair
from secure_api import KDF_VARIANT, SIGN_VARIANT, WIRE_VARIANT

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.toml"
TOKENS_PATH = ROOT / "tokens.json"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "checkin.log"

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_AUTH = 2
EXIT_CHECKIN = 3
EXIT_NETWORK = 4


def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_config(path: Path) -> dict[str, Any]:
    """Load config from TOML and/or environment variables.

    Cloud-friendly: if HYPERDOWN_EMAIL + HYPERDOWN_PASSWORD are set,
    config.toml is optional.
    """
    cfg: dict[str, Any] = {
        "api_base_url": "https://hyperdown.net",
        "user_agent": "Mozilla/5.0 Hyperdown/3.0",
        "email": "",
        "password": "",
        "proxy": "",
    }
    if path.is_file():
        if tomllib is None:
            raise RuntimeError(
                f"存在 {path} 但当前 Python 无 tomllib/tomli。"
                "请执行: pip install tomli   或升级到 Python 3.11+，"
                "或删除 config.toml 仅使用环境变量 HYPERDOWN_EMAIL/PASSWORD。"
            )
        with path.open("rb") as f:
            file_cfg = tomllib.load(f)
        if isinstance(file_cfg, dict):
            cfg.update(file_cfg)
    elif not (
        os.environ.get("HYPERDOWN_EMAIL") and os.environ.get("HYPERDOWN_PASSWORD")
    ):
        raise FileNotFoundError(
            f"缺少配置文件 {path}，且未设置 HYPERDOWN_EMAIL/HYPERDOWN_PASSWORD。\n"
            "云服务器可用：复制 deploy/env.example 为 /etc/hyperdown-checkin.env 并填写，\n"
            "或本地：cp config.example.toml config.toml"
        )

    # Env overrides (prefer for secrets on cloud)
    if os.environ.get("HYPERDOWN_EMAIL"):
        cfg["email"] = os.environ["HYPERDOWN_EMAIL"]
    if os.environ.get("HYPERDOWN_PASSWORD"):
        cfg["password"] = os.environ["HYPERDOWN_PASSWORD"]
    if os.environ.get("HYPERDOWN_API_BASE"):
        cfg["api_base_url"] = os.environ["HYPERDOWN_API_BASE"]
    if os.environ.get("HYPERDOWN_PROXY"):
        cfg["proxy"] = os.environ["HYPERDOWN_PROXY"]
    if os.environ.get("HYPERDOWN_USER_AGENT"):
        cfg["user_agent"] = os.environ["HYPERDOWN_USER_AGENT"]
    return cfg


def load_tokens(path: Path) -> TokenPair:
    if not path.is_file():
        return TokenPair()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TokenPair.from_dict(data)
    except (OSError, json.JSONDecodeError):
        return TokenPair()


def save_tokens(path: Path, tokens: TokenPair) -> None:
    path.write_text(
        json.dumps(tokens.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def format_bytes(n: int | float | None) -> str:
    if n is None:
        return "?"
    n = float(n)
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.2f} {units[i]}"


def ensure_auth(client: HyperdownClient, email: str, password: str) -> dict[str, Any]:
    """Return current user dict, refreshing/logging in as needed."""
    if client.tokens.access_token:
        try:
            return client.me()
        except APIError as e:
            if e.code not in ("unauthorized", "invalid_token", "token_expired"):
                # try refresh anyway for auth-ish errors
                pass
            log(f"access token 无效 ({e.code})，尝试 refresh…")
    if client.tokens.refresh_token:
        try:
            client.refresh()
            save_tokens(TOKENS_PATH, client.tokens)
            return client.me()
        except APIError as e:
            log(f"refresh 失败 ({e.code}): {e.message}，改为密码登录…")
    if not email or not password:
        raise APIError("config_error", "需要 email/password 或有效 tokens.json")
    log("正在登录…")
    client.login(email, password)
    save_tokens(TOKENS_PATH, client.tokens)
    return client.me()


def do_checkin(client: HyperdownClient, user: dict[str, Any]) -> int:
    if user.get("is_check_in"):
        log(
            f"今日已签到。流量余额 {format_bytes(user.get('traffic_bytes'))}，"
            f"累计签到流量 {format_bytes(user.get('total_traffic_check_in_bytes'))}"
        )
        return EXIT_OK

    log(
        f"开始签到（KDF={KDF_VARIANT}, WIRE={WIRE_VARIANT}, SIGN={SIGN_VARIANT}）…"
    )
    try:
        result = client.check_in()
    except APIError as e:
        if e.code == "network_error":
            log(f"网络错误: {e.message}")
            return EXIT_NETWORK
        log(f"签到失败: [{e.code}] {e.message}")
        if e.code in (
            "secure_request_invalid",
            "secure_request_required",
            "secure_request_expired",
            "secure_request_replayed",
        ):
            log(
                "安全封包未通过服务端校验。登录/查询可用；签到加密仍待对齐。"
                "请用官方客户端抓一次签到请求，或运行: python3 checkin.py --probe-secure"
            )
        return EXIT_CHECKIN

    reward = result.get("traffic_bytes") or result.get("reward_bytes") or 0
    user2 = result.get("user") if isinstance(result.get("user"), dict) else {}
    bal = user2.get("traffic_bytes", user.get("traffic_bytes"))
    log(f"签到成功！本次奖励 {format_bytes(reward)}，余额 {format_bytes(bal)}")
    if user2:
        log(
            f"is_check_in={user2.get('is_check_in')} "
            f"last_check_in_at={user2.get('last_check_in_at')}"
        )
    return EXIT_OK


def probe_secure() -> int:
    """Try a small matrix of seal variants against /me/checkins (no auth)."""
    import os as _os
    from secure_api import derive_key  # noqa: F401

    variants = [
        ("salt_digest_info_method_path", "nonce_hex_ct_b64"),
        ("salt_digest_info_prefix_method_path", "nonce_hex_ct_b64"),
        ("salt_digest_info_prefix_only", "nonce_hex_ct_b64"),
        ("salt_prefix_info_digest", "nonce_hex_ct_b64"),
        ("salt_prefix_info_material", "nonce_hex_ct_b64"),
        ("salt_prefix_info_method_path", "nonce_hex_ct_b64"),
        ("salt_digest_info_empty", "nonce_hex_ct_b64"),
        ("salt_prefix_info_empty", "nonce_hex_ct_b64"),
        ("salt_digest_info_method_path", "nonce_hex_ct_hex"),
        ("salt_digest_info_method_path", "nonce_b64_ct_b64"),
        ("salt_digest_info_method_path", "nonce_hex_ct_b64_with_nonce"),
        ("salt_prefix_info_digest", "nonce_hex_ct_hex"),
        ("salt_prefix_info_digest", "nonce_b64_ct_b64"),
    ]
    client = HyperdownClient()
    for kdf, wire in variants:
        _os.environ["HYPERDOWN_KDF_VARIANT"] = kdf
        _os.environ["HYPERDOWN_WIRE_VARIANT"] = wire
        # Reload module constants
        import importlib
        import secure_api as sa

        importlib.reload(sa)
        try:
            client.request("POST", "/me/checkins", body={}, auth=False, secure=True)
            log(f"UNEXPECTED SUCCESS kdf={kdf} wire={wire}")
            return EXIT_OK
        except APIError as e:
            log(f"kdf={kdf} wire={wire} -> {e.code}: {e.message[:60]}")
            if e.code not in (
                "secure_request_invalid",
                "secure_request_required",
                "unauthorized",
            ):
                log(f"interesting error: {e}")
    log("probe 结束（均未通过业务校验；结构正确时应多为 secure_request_invalid 或 unauthorized）")
    return EXIT_CHECKIN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hyperdown 每日自动签到")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--login-only", action="store_true", help="仅登录并保存 token")
    parser.add_argument("--me-only", action="store_true", help="仅查询用户信息")
    parser.add_argument(
        "--probe-secure",
        action="store_true",
        help="探测安全封包 KDF/线格式变体（调试用）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使 is_check_in=true 也尝试签到",
    )
    args = parser.parse_args(argv)

    if args.probe_secure:
        return probe_secure()

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return EXIT_CONFIG
    except Exception as e:
        print(f"读取配置失败: {e}", file=sys.stderr)
        return EXIT_CONFIG

    email = str(cfg.get("email") or "").strip()
    password = str(cfg.get("password") or "")
    base = str(cfg.get("api_base_url") or "https://hyperdown.net")
    ua = str(cfg.get("user_agent") or "Mozilla/5.0 Hyperdown/3.0")
    proxy = str(cfg.get("proxy") or "")

    client = HyperdownClient(
        base_url=base,
        user_agent=ua,
        proxy=proxy,
        tokens=load_tokens(TOKENS_PATH),
    )

    try:
        user = ensure_auth(client, email, password)
    except APIError as e:
        if e.code == "network_error":
            log(f"网络错误: {e.message}")
            return EXIT_NETWORK
        log(f"鉴权失败: [{e.code}] {e.message}")
        return EXIT_AUTH
    except Exception as e:
        log(f"鉴权异常: {e}")
        return EXIT_AUTH

    nick = user.get("nickname") or user.get("email") or user.get("id") or "?"
    log(
        f"已登录: {nick} | 流量 {format_bytes(user.get('traffic_bytes'))} | "
        f"今日已签到={user.get('is_check_in')}"
    )
    save_tokens(TOKENS_PATH, client.tokens)

    if args.login_only or args.me_only:
        return EXIT_OK

    if args.force:
        user = {**user, "is_check_in": False}

    try:
        return do_checkin(client, user)
    except APIError as e:
        if e.code == "network_error":
            log(f"网络错误: {e.message}")
            return EXIT_NETWORK
        log(f"签到错误: [{e.code}] {e.message}")
        return EXIT_CHECKIN


if __name__ == "__main__":
    sys.exit(main())
