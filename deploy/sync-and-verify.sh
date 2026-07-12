#!/usr/bin/env bash
# 从开发机同步代码到云服务器并验证服务
# 用法：
#   KEY=/path/to/your.pem HOST=user@your-vps-ip bash deploy/sync-and-verify.sh
#
# 环境变量（必填 KEY / HOST）：
#   KEY     SSH 私钥路径
#   HOST    user@host
#   APP_DIR 远程安装目录，默认 /opt/hyperdown-checkin

set -euo pipefail
KEY="${KEY:-}"
HOST="${HOST:-}"
APP_DIR="${APP_DIR:-/opt/hyperdown-checkin}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -z "${KEY}" || -z "${HOST}" ]]; then
  echo "请设置 KEY 与 HOST，例如：" >&2
  echo "  KEY=/path/to/your.pem HOST=user@your-vps-ip bash deploy/sync-and-verify.sh" >&2
  exit 1
fi
if [[ ! -f "${KEY}" ]]; then
  echo "私钥不存在: ${KEY}" >&2
  exit 1
fi

SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o ConnectTimeout=20)
SCP=(scp -i "$KEY" -o IdentitiesOnly=yes)

echo "==> 同步源码"
"${SCP[@]}" \
  "$SRC/checkin.py" "$SRC/client.py" "$SRC/secure_api.py" "$SRC/requirements.txt" \
  "$HOST:/tmp/hd-sync/"

# ensure remote tmp dir
"${SSH[@]}" "$HOST" 'mkdir -p /tmp/hd-sync'
"${SCP[@]}" \
  "$SRC/checkin.py" "$SRC/client.py" "$SRC/secure_api.py" "$SRC/requirements.txt" \
  "$SRC/deploy/hyperdown-checkin.service" "$SRC/deploy/hyperdown-checkin.timer" \
  "$HOST:/tmp/hd-sync/"

echo "==> 安装到 ${APP_DIR}"
"${SSH[@]}" "$HOST" "sudo bash -s" <<EOF
set -euo pipefail
APP_DIR=${APP_DIR}
cp /tmp/hd-sync/checkin.py /tmp/hd-sync/client.py /tmp/hd-sync/secure_api.py /tmp/hd-sync/requirements.txt "\$APP_DIR/"
cp /tmp/hd-sync/hyperdown-checkin.service /tmp/hd-sync/hyperdown-checkin.timer /etc/systemd/system/
chown -R hyperdown:hyperdown "\$APP_DIR"
chmod +x "\$APP_DIR/.venv/bin/"* 2>/dev/null || true
# 依赖
sudo -u hyperdown "\$APP_DIR/.venv/bin/pip" install -q -r "\$APP_DIR/requirements.txt" || \
  "\$APP_DIR/.venv/bin/pip" install -q -r "\$APP_DIR/requirements.txt"
# tomli for py<3.11
"\$APP_DIR/.venv/bin/pip" install -q 'tomli>=2.0.0' || true
systemctl daemon-reload
systemctl enable hyperdown-checkin.timer
systemctl restart hyperdown-checkin.timer
echo "==> 试跑"
systemctl start hyperdown-checkin.service || true
sleep 1
journalctl -u hyperdown-checkin.service -n 30 --no-pager
echo "==> timer"
systemctl list-timers hyperdown-checkin.timer --no-pager
echo "==> python"
sudo -u hyperdown "\$APP_DIR/.venv/bin/python" -c 'import tomllib,nacl,cryptography; print("imports_ok", __import__("sys").version)'
EOF

echo "完成。"
