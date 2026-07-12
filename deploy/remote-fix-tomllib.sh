#!/usr/bin/env bash
# 在云服务器上修复 tomllib / 旧 Python 兼容问题
# 用法（本机）：
#   scp deploy/remote-fix-tomllib.sh checkin.py requirements.txt user@your-vps:/tmp/
#   ssh user@your-vps 'sudo bash /tmp/remote-fix-tomllib.sh'
#
# 或一条命令（本机在 hyperdown-checkin 目录）：
#   ssh user@your-vps 'bash -s' < deploy/remote-fix-tomllib.sh
#   （需先 scp 更新 checkin.py，或脚本内联修补）

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/hyperdown-checkin}"
APP_USER="${APP_USER:-hyperdown}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 sudo 运行" >&2
  exit 1
fi

if [[ ! -f "${APP_DIR}/checkin.py" ]]; then
  echo "未找到 ${APP_DIR}/checkin.py" >&2
  exit 1
fi

# 若 /tmp 里有上传的新文件则优先用
if [[ -f /tmp/checkin.py ]]; then
  cp /tmp/checkin.py "${APP_DIR}/checkin.py"
  echo "已从 /tmp/checkin.py 更新 checkin.py"
fi
if [[ -f /tmp/requirements.txt ]]; then
  cp /tmp/requirements.txt "${APP_DIR}/requirements.txt"
  echo "已更新 requirements.txt"
fi

# 若仍是旧版 import tomllib，做最小补丁
if grep -q '^import tomllib$' "${APP_DIR}/checkin.py"; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/opt/hyperdown-checkin/checkin.py")
t = p.read_text(encoding="utf-8")
old = "import tomllib\n"
new = """try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore
"""
if old not in t:
    raise SystemExit("checkin.py 已不是旧版 import，跳过 sed 式补丁")
p.write_text(t.replace(old, new, 1), encoding="utf-8")
print("已就地补丁 import tomllib")
PY
fi

chown "${APP_USER}:${APP_USER}" "${APP_DIR}/checkin.py" "${APP_DIR}/requirements.txt" 2>/dev/null || true

VENV_PY="${APP_DIR}/.venv/bin/python"
VENV_PIP="${APP_DIR}/.venv/bin/pip"
if [[ ! -x "${VENV_PIP}" ]]; then
  echo "缺少 venv: ${APP_DIR}/.venv" >&2
  exit 1
fi

# 旧 Python 需要 tomli
"${VENV_PIP}" install -q 'tomli>=2.0.0' || true
"${VENV_PIP}" install -q -r "${APP_DIR}/requirements.txt" || true

echo "==> Python: $(${VENV_PY} --version)"
echo "==> 语法检查"
"${VENV_PY}" -m py_compile "${APP_DIR}/checkin.py"

echo "==> 试跑服务"
systemctl start hyperdown-checkin.service || true
sleep 1
journalctl -u hyperdown-checkin.service -n 40 --no-pager

echo "完成。"
