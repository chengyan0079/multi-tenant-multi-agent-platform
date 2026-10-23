"""
gen_dev_curl - 读取 .env 的 DEV_* 配置，拼出带身份头的 curl 命令（开发/联调用）。

本项目不做登录：身份由上游网关断言。开发环境下本脚本生成可直接调用的身份头：
 - TRUST_HEADERS=True：用 X-User-Id / X-Tenant-Id 信任头
 - 否则（默认）：用 Bearer JWT（HS256，payload 仅 user_id，由 JWT_SECRET 签名）；
   租户经 X-Tenant-Id 头传入。角色/权限由后端按 DEV_ROLE 或库解析。
脚本输出可复制执行的 curl；加 --run 直接执行。

用法：
  python scripts/gen_dev_curl.py [PATH] [--method POST] [--data '{"k":"v"}'] [--host http://localhost:8000] [--run]
  PATH 默认 /api/v1/config/requests（该端点挂了 get_current_user，可验证认证）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> dict:
    env: dict = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _b64url(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def make_jwt(user_id: str, secret: str, alg: str = "HS256", exp_hours: int = 24) -> str:
    """stdlib 版 HS256 JWT（与 jose 兼容），避免额外依赖。"""
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"user_id": user_id, "exp": int(time.time()) + exp_hours * 3600}).encode())
    signing_input = header + b"." + payload
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + _b64url(sig)).decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="/api/v1/config/requests")
    ap.add_argument("--method", default="POST")
    ap.add_argument("--data", default=None, help="JSON 请求体；缺省且为 POST 时给最小合法示例")
    ap.add_argument("--host", default=None)
    ap.add_argument("--run", action="store_true", help="直接执行生成的 curl")
    args = ap.parse_args()

    env = load_env(ROOT / ".env")
    dev_user = env.get("DEV_USER_ID", "")
    dev_tenant = env.get("DEV_TENANT_ID", "dev-tenant")
    secret = env.get("JWT_SECRET", "")
    alg = env.get("JWT_ALGORITHM", "HS256")
    trust = env.get("TRUST_HEADERS", "False").lower() == "true"
    user_header = env.get("USER_HEADER", "X-User-Id")
    tenant_header = env.get("TENANT_HEADER", "X-Tenant-Id")
    host = args.host or env.get("API_HOST", "http://localhost:8000")

    if not dev_user:
        print("⚠️ .env 未配置 DEV_USER_ID；请先设置后再生成 curl", file=sys.stderr)
        sys.exit(1)

    headers: list[str] = []
    # 租户头始终带上（后端 tenant_id 取自 X-Tenant-Id，缺省才用 DEV_TENANT_ID）
    headers.append(f'-H "{tenant_header}: {dev_tenant}"')

    if trust:
        headers.append(f'-H "{user_header}: {dev_user}"')
        mode = "信任头(TRUST_HEADERS=True)"
    elif secret:
        token = make_jwt(dev_user, secret, alg)
        headers.append(f'-H "Authorization: Bearer {token}"')
        mode = "Bearer JWT(HS256)"
    else:
        headers.append(f'-H "{user_header}: {dev_user}"')
        mode = "回退信任头(无 JWT_SECRET，需手动开 TRUST_HEADERS)"

    data = args.data
    if data is None and args.method.upper() == "POST":
        data = json.dumps(
            {
                "namespace": "agent-platform",
                "group_id": "DEFAULT_GROUP",
                "data_id": "demo.prompt",
                "op_type": 1,
                "title": "dev smoke test",
                "content_new": "{}",
                "reason": "smoke test",
            },
            ensure_ascii=False,
        )

    # 请求体写入文件，避免 Windows 下引号转义问题（curl -d @file）
    body_path = ROOT / "tmp" / "dev_curl_body.json"
    if data is not None:
        body_path.parent.mkdir(exist_ok=True)
        body_path.write_text(data, encoding="utf-8")

    cmd = [f'curl -X {args.method} "{host}{args.path}"']
    cmd += headers
    cmd += ['-H "Content-Type: application/json"']
    if data is not None:
        cmd.append(f"-d @{body_path}")
    curl = " \\\n  ".join(cmd)

    print(f"# 认证模式: {mode} | user={dev_user} tenant={dev_tenant} (角色/权限由库 agent_user_tenant→agent_role→agent_role_permission 解析)")
    print(curl)
    if args.run:
        print("\n# 执行中...")
        subprocess.run(curl, shell=True)


if __name__ == "__main__":
    main()
