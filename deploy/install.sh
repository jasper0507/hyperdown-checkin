#!/usr/bin/env bash
# 在 Linux 云服务器上一键安装 Hyperdown 签到定时任务（systemd timer）
#
# 用法（在项目根目录执行）：
#   sudo bash deploy/install.sh
#   sudo nano /etc/hyperdown-checkin.env   # 填写邮箱密码
#   sudo systemctl start hyperdown-checkin.service   # 立刻试跑
#   sudo systemctl enable --now hyperdown-checkin.timer

set -euo pipefail

APP_USER="${APP_USER:-hyperdown}"
APP_DIR="${APP_DIR:-/opt/hyperdown-checkin}"
ENV_FILE="${ENV_FILE:-/etc/hyperdown-checkin.env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 运行：sudo bash deploy/install.sh" >&2
  exit 1
fi

echo "==> 安装目录: ${APP_DIR}"
echo "==> 运行用户: ${APP_USER}"

if ! command -v rsync &>/dev/null; then
  echo "未找到 rsync，请先安装（apt install rsync / dnf install rsync）" >&2
  exit 1
fi

if ! id -u "${APP_USER}" &>/dev/null; then
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_DIR}"
# 同步代码（排除本地密钥与缓存）。
# 注意：--delete 会删除 APP_DIR 下源码树中不存在的文件；
# .venv / config.toml / tokens.json / logs 已 exclude，不会被删。
rsync -a --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude 'config.toml' \
  --exclude 'tokens.json' \
  --exclude 'logs/*' \
  --exclude '.git' \
  "${SRC_DIR}/" "${APP_DIR}/"

mkdir -p "${APP_DIR}/logs"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${APP_DIR}/deploy/env.example" "${ENV_FILE}"
  echo "==> 已创建 ${ENV_FILE}，请编辑填写 HYPERDOWN_EMAIL / HYPERDOWN_PASSWORD"
else
  echo "==> 保留已有 ${ENV_FILE}"
fi
chmod 600 "${ENV_FILE}"

echo "==> 创建 Python venv 并安装依赖"
if ! command -v python3 &>/dev/null; then
  echo "未找到 python3，请先安装 Python 3.11+" >&2
  exit 1
fi
# 部分发行版需要 python3-venv
if ! python3 -m venv "${APP_DIR}/.venv" 2>/dev/null; then
  echo "创建 venv 失败，尝试安装 python3-venv…"
  if command -v apt-get &>/dev/null; then
    apt-get update -qq && apt-get install -y -qq python3-venv python3-pip
  elif command -v dnf &>/dev/null; then
    dnf install -y python3-virtualenv python3-pip
  fi
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install -q --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/.venv"

# 时区提示
if command -v timedatectl &>/dev/null; then
  TZ_NOW="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  echo "==> 当前时区: ${TZ_NOW:-unknown}（签到建议 Asia/Shanghai，且 NTP 开启）"
fi

echo "==> 安装 systemd unit"
install -m 644 "${APP_DIR}/deploy/hyperdown-checkin.service" /etc/systemd/system/
install -m 644 "${APP_DIR}/deploy/hyperdown-checkin.timer" /etc/systemd/system/
# 若 APP_DIR 不是默认路径，改写 unit 里的路径
if [[ "${APP_DIR}" != "/opt/hyperdown-checkin" ]]; then
  sed -i "s|/opt/hyperdown-checkin|${APP_DIR}|g" \
    /etc/systemd/system/hyperdown-checkin.service
fi
if [[ "${APP_USER}" != "hyperdown" ]]; then
  sed -i "s|^User=hyperdown|User=${APP_USER}|; s|^Group=hyperdown|Group=${APP_USER}|" \
    /etc/systemd/system/hyperdown-checkin.service
fi

systemctl daemon-reload
systemctl enable hyperdown-checkin.timer
systemctl start hyperdown-checkin.timer

echo
echo "安装完成。"
echo "1) 编辑密钥:  sudo nano ${ENV_FILE}"
echo "2) 立刻试跑:  sudo systemctl start hyperdown-checkin.service"
echo "3) 看日志:    sudo journalctl -u hyperdown-checkin.service -n 50 --no-pager"
echo "             或 tail -f ${APP_DIR}/logs/checkin.log"
echo "4) 看定时:    systemctl list-timers hyperdown-checkin.timer"
echo
echo "成功日志应含「签到成功」或「今日已签到」；详见 README / STATUS.md。"
