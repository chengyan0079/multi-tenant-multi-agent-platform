"""
gen_dev_curl - 生成带 Bearer JWT 的 curl 命令（开发/联调用）。

开发环境绕过登录接口，直接用 .env 的 JWT_SECRET 现签一个 token：
 - payload 必含 user_id（整数）；传 --tenant-id 则含 tenant_id（走后端租户分支），
   不传则签超管 token（后端超管分支：user_id + 主租户 + admin 角色判定）
 - 不含任何硬编码身份：user_id / tenant_id 一律由命令行传入，不再读 .env 的固定 id
脚本输出可复制执行的 curl；加 --run 直接执行。

用法：
  python scripts/gen_dev_curl.py --user-id 1 [--tenant-id 1] [PATH]
      [--method POST] [--data '{"k":"v"}'] [--host http://localhost:9800] [--run]
  PATH 默认 /api/v1/admin/config/requests（超管专用，可验证 require_super_admin）
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

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _b64url(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def make_jwt(
    user_id: int,
    secret: str,
    alg: str = "HS256",
    exp_hours: int = 24,
    tenant_id: int | None = None,
) -> str:
    """stdlib 版 HS256 JWT（与 jose 兼容），避免额外依赖。"""
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    claims: dict[str, object] = {
        "user_id": user_id,
        "exp": int(time.time()) + exp_hours * 3600,
    }
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    payload = _b64url(json.dumps(claims).encode())
    signing_input = header + b"." + payload
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return (signing_input + b"." + _b64url(sig)).decode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="/api/v1/admin/config/requests")
    ap.add_argument("--method", default="POST")
    ap.add_argument("--data", default=None, help="JSON 请求体；缺省且为 POST 时给最小合法示例")
    ap.add_argument("--host", default=None)
    ap.add_argument(
        "--user-id", type=int, required=True, help="JWT 的 user_id（须已存在于库中）"
    )
    ap.add_argument(
        "--tenant-id",
        type=int,
        default=None,
        help="JWT 的 tenant_id；不传则签发超管 token（无租户上下文）",
    )
    ap.add_argument("--run", action="store_true", help="直接执行生成的 curl")
    args = ap.parse_args()

    load_dotenv(dotenv_path=ROOT / ".env", override=True)
    env = os.environ
    secret = env.get("JWT_SECRET", "")
    alg = env.get("JWT_ALGORITHM", "HS256")
    host = args.host or env.get("API_HOST") or f"http://localhost:{env.get('PORT', '8000')}"

    if not secret:
        print("⚠️ .env 未配置 JWT_SECRET，无法签发 token", file=sys.stderr)
        sys.exit(1)

    token = make_jwt(args.user_id, secret, alg, tenant_id=args.tenant_id)
    headers = [f'-H "Authorization: Bearer {token}"']
    if args.tenant_id is None:
        mode = "Bearer JWT（超管：token 无 tenant_id）"
    else:
        mode = f"Bearer JWT（租户 {args.tenant_id}）"

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

    tenant_desc = "超管(无租户)" if args.tenant_id is None else args.tenant_id
    print(
        f"# 认证模式: {mode} | user_id={args.user_id} tenant_id={tenant_desc} "
        f"(角色/权限由库 agent_user_tenant→agent_role→agent_role_permission 解析)"
    )
    print(curl)
    if args.run:
        print("\n# 执行中...")
        subprocess.run(curl, shell=True)


if __name__ == "__main__":
    main()
