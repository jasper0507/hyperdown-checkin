# Hyperdown 每日自动签到

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: Personal Use](https://img.shields.io/badge/license-personal%20use-lightgrey.svg)](#许可与免责)

用 **Python 3** 在 Linux 云服务器上自动完成 [Hyperdown](https://hyperdown.net) 每日签到，领取免费高速流量。  
协议对齐官方桌面客户端（v1.1.3）的登录 / 查询 / 安全签到接口，**不依赖** Windows 客户端常驻运行。

| 你想做什么 | 直接看 |
|------------|--------|
| 在 VPS 上装好、每天自动跑 | [一、云服务器部署（推荐）](#一云服务器部署推荐) |
| 本机临时试跑 | [二、本机快速使用](#二本机快速使用) |
| 看日志、改时间、排错 | [三、日常运维](#三日常运维) |
| 参数 / 退出码 / 环境变量 | [四、参考](#四参考) |
| 安全封包原理 | [STATUS.md](./STATUS.md) |

---

## 它做什么

```text
登录（邮箱+密码） → 查询是否已签到 → 未签则 POST /me/checkins（安全封包）→ 写日志退出
```

| 能力 | 说明 |
|------|------|
| 登录 / 刷新 token | 自动落盘 `tokens.json`（权限 600） |
| 查询账号 | 流量余额、今日是否已签到 |
| 安全签到 | 复现官方 `SealJSON`（ECDH + HKDF + XChaCha20 + HMAC） |
| 幂等 | 今日已签到 → 直接 **exit 0**（适合 timer / cron） |
| 云部署 | `deploy/install.sh` + systemd timer（默认约 **08:05**） |

签到接口需要带 `X-Hyperdown-Secure: v1` 的加密信封；本仓库默认算法已与官方抓包对齐，可直接用于生产定时任务。细节见 [STATUS.md](./STATUS.md)。

---

## 环境要求

- **Python 3.8+**（推荐 3.10 / 3.11 / 3.12）
- 能访问 `https://hyperdown.net`
- 云服务器建议：**时区 `Asia/Shanghai` + NTP 开启**（签名里的时间戳会校验）

依赖（`requirements.txt`）：

```text
cryptography>=42
PyNaCl>=1.5
tomli>=2.0          # 仅 Python < 3.11
```

---

## 一、云服务器部署（推荐）

适合 Ubuntu / Debian / CentOS 等 Linux VPS。  
账号密码只放在服务器 `/etc/hyperdown-checkin.env`，**不要**写进 Git。

### 1. 获取代码

```bash
git clone https://github.com/jasper0507/hyperdown-checkin.git
cd hyperdown-checkin
```

### 2. 一键安装

```bash
sudo bash deploy/install.sh
```

脚本会：

1. 创建系统用户 `hyperdown`
2. 安装代码到 `/opt/hyperdown-checkin`，创建 venv 并装依赖
3. 安装 systemd 单元：`hyperdown-checkin.service` / `hyperdown-checkin.timer`
4. 若尚无密钥文件，从模板生成 `/etc/hyperdown-checkin.env`（`chmod 600`）
5. 启用定时器（默认每天 **08:05**，约 2 分钟随机抖动）

> `install.sh` 使用 `rsync --delete` 同步源码树；`config.toml` / `tokens.json` / `.venv` / `logs` 已排除，不会被清掉。

### 3. 填写账号

```bash
sudo nano /etc/hyperdown-checkin.env
```

至少配置：

```bash
HYPERDOWN_EMAIL=you@example.com
HYPERDOWN_PASSWORD=your-password
```

```bash
sudo chmod 600 /etc/hyperdown-checkin.env
```

### 4. 时区与 NTP（重要）

```bash
sudo timedatectl set-timezone Asia/Shanghai
sudo timedatectl set-ntp true
timedatectl   # 确认 System clock synchronized: yes
```

### 5. 立刻试跑

```bash
sudo systemctl start hyperdown-checkin.service
sudo journalctl -u hyperdown-checkin.service -n 40 --no-pager
```

成功时常见两类日志：

```text
# 未签到日
开始签到（KDF=ecdh_re_primary, SIGN=v3_token_nul, B64=rawurl）…
签到成功！本次奖励 …

# 已签到日（幂等）
今日已签到。流量余额 …，累计签到流量 …
```

### 6. 确认定时器

```bash
systemctl is-enabled hyperdown-checkin.timer   # enabled
systemctl list-timers hyperdown-checkin.timer  # 看 NEXT
```

### 从其他机器更新服务器代码

在**已 clone 的开发机**项目根目录：

```bash
export KEY=/path/to/your.pem
export HOST=user@your-vps-ip
bash deploy/sync-and-verify.sh
```

或在服务器上直接：

```bash
cd /opt/hyperdown-checkin   # 若用 git 部署
sudo git pull               # 仅当你以 git 方式维护该目录时
# 更常见：本机 scp / rsync 三个 py + requirements 后：
sudo systemctl start hyperdown-checkin.service
```

### 不用 systemd？用 cron

见 [`deploy/crontab.example`](./deploy/crontab.example)。  
注意：`/etc/hyperdown-checkin.env` 通常为 `root:root 600`，请用 **root 的 crontab** `source` 该文件。

---

## 二、本机快速使用

适合临时验证账号或调试，**生产仍推荐上节的 systemd 方案**。

```bash
git clone https://github.com/jasper0507/hyperdown-checkin.git
cd hyperdown-checkin
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp config.example.toml config.toml
chmod 600 config.toml
# 编辑 config.toml，填写 email / password

python3 checkin.py --login-only    # 仅登录
python3 checkin.py --me-only       # 查流量 / 是否已签
python3 checkin.py                 # 登录 + 签到
```

也可用环境变量代替 `config.toml`：

```bash
export HYPERDOWN_EMAIL=you@example.com
export HYPERDOWN_PASSWORD=your-password
python3 checkin.py
```

日志：`logs/checkin.log`。

---

## 三、日常运维

### 常用命令

```bash
# 立刻再跑一次
sudo systemctl start hyperdown-checkin.service

# 服务日志（推荐）
sudo journalctl -u hyperdown-checkin.service -n 50 --no-pager
sudo journalctl -u hyperdown-checkin.service -f

# 应用日志文件
sudo tail -f /opt/hyperdown-checkin/logs/checkin.log

# 下次触发时间
systemctl list-timers hyperdown-checkin.timer

# 停用 / 启用定时
sudo systemctl disable --now hyperdown-checkin.timer
sudo systemctl enable --now hyperdown-checkin.timer
```

### 修改每天几点跑

```bash
sudo systemctl edit hyperdown-checkin.timer
# 或编辑 /etc/systemd/system/hyperdown-checkin.timer 中的 OnCalendar=
sudo systemctl daemon-reload
sudo systemctl restart hyperdown-checkin.timer
```

### 强制打签到 API（调试封包）

即使账号显示「今日已签到」，也可强制请求（服务端若已签仍返回业务码，脚本 **exit 0**）：

```bash
sudo bash -c 'set -a; source /etc/hyperdown-checkin.env; set +a; \
  sudo -u hyperdown env \
    HYPERDOWN_EMAIL="$HYPERDOWN_EMAIL" \
    HYPERDOWN_PASSWORD="$HYPERDOWN_PASSWORD" \
    /opt/hyperdown-checkin/.venv/bin/python /opt/hyperdown-checkin/checkin.py --force'
```

> 不要用 `sudo -u hyperdown source /etc/hyperdown-checkin.env`：env 文件多为 root 可读，hyperdown 用户读不到。

### 故障对照

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 退出码 1 | 未配置账号 | 检查 `/etc/hyperdown-checkin.env` 或 `config.toml` |
| 退出码 2 | 邮箱/密码错误或 token 失效 | 改密码后重跑；删 `tokens.json` 再登录 |
| 退出码 4 | 出网 / DNS / 代理 | 在服务器上 `curl -I https://hyperdown.net` |
| 退出码 3 / `secure_request_invalid` | 时间不准，或 env 里残留错误 `HYPERDOWN_*_VARIANT` | 开 NTP；去掉调试用变体变量；见 [STATUS.md](./STATUS.md) |
| 缺 `tomllib` | 系统 Python &lt; 3.11 且无 tomli | venv 中 `pip install tomli`，或 `deploy/remote-fix-tomllib.sh` |

---

## 四、参考

### 命令行

| 参数 | 含义 |
|------|------|
| （无） | 登录 + 签到 |
| `--login-only` | 仅登录并保存 token |
| `--me-only` | 仅查询用户信息 |
| `--force` | 忽略本地「已签到」标志，仍请求签到 API |
| `--config PATH` | 指定配置文件 |

### 退出码

| Code | 含义 |
|------|------|
| 0 | 签到成功，或今日已签到（幂等成功） |
| 1 | 配置错误 |
| 2 | 登录 / 鉴权失败 |
| 3 | 签到或安全封包失败 |
| 4 | 网络错误 |

### 环境变量

**生产只需：**

| 变量 | 含义 |
|------|------|
| `HYPERDOWN_EMAIL` | 登录邮箱 |
| `HYPERDOWN_PASSWORD` | 登录密码 |

**可选：**

| 变量 | 默认 | 含义 |
|------|------|------|
| `HYPERDOWN_API_BASE` | `https://hyperdown.net` | API 根 |
| `HYPERDOWN_PROXY` | （空） | HTTP(S) 代理 |
| `HYPERDOWN_USER_AGENT` | `Go-http-client/1.1` | 与官方客户端一致 |

**调试用（生产请勿设置；代码内默认已通过服务端校验）：**

| 变量 | 默认 |
|------|------|
| `HYPERDOWN_KDF_VARIANT` | `ecdh_re_primary` |
| `HYPERDOWN_SIGN_VARIANT` | `v3_token_nul` |
| `HYPERDOWN_B64_VARIANT` | `rawurl` |
| `HYPERDOWN_SECURE_PEER_PUB` | 内嵌对端 X25519 公钥 hex |

完整算法与服务器运维备忘：[STATUS.md](./STATUS.md)。

---

## 五、项目结构

```text
hyperdown-checkin/
├── checkin.py                 # 入口：登录 / 查询 / 签到
├── client.py                  # HTTP API 客户端
├── secure_api.py              # 官方 SealJSON 安全封包复现
├── config.example.toml        # 本机配置模板 → 复制为 config.toml
├── requirements.txt
├── README.md                  # 本文件
├── STATUS.md                  # 算法终态与运维备忘
├── .gitignore                 # 忽略密钥、token、日志、venv
└── deploy/
    ├── install.sh             # 云服务器一键安装
    ├── sync-and-verify.sh     # 开发机同步到 VPS 并试跑
    ├── hyperdown-checkin.service
    ├── hyperdown-checkin.timer
    ├── env.example            # /etc/hyperdown-checkin.env 模板
    ├── crontab.example        # 不用 systemd 时的 cron 示例
    └── remote-fix-tomllib.sh  # 旧 Python / tomli 修复
```

运行时数据（**不进仓库**）：

| 路径 | 用途 |
|------|------|
| `config.toml` / `tokens.json` | 本机账号与 token |
| `/etc/hyperdown-checkin.env` | 云上账号（systemd `EnvironmentFile`） |
| `logs/checkin.log` | 应用日志 |

---

## 六、安全与合规

1. **禁止**将 `config.toml`、`tokens.json`、`/etc/hyperdown-checkin.env`、SSH 私钥（`*.pem`）提交到 Git。  
2. 云上密钥文件保持 `chmod 600`；`install.sh` 会强制设置。  
3. 内嵌的 peer 公钥是官方客户端中的 **X25519 公钥材料**，不是你的账号密码。  
4. 官方客户端升级后，签到协议可能变化，需重新对照抓包更新 `secure_api.py`。  
5. 自动化可能违反服务条款，请**仅限个人学习与自用**。

---

## 许可与免责

本项目仅供个人学习与自用。使用本脚本产生的任何账号风险、服务条款问题或数据损失，由使用者自行承担。
