# Hyperdown 每日自动签到

基于 Hyperdown 桌面客户端（v1.1.3）逆向的 **Python 3** 签到脚本。  
通过 `https://hyperdown.net/api/v1` 完成登录、查询与每日签到，领取免费高速流量。

> **适用场景**：本机定时 / 云服务器（systemd timer 或 cron）。  
> **不依赖** Windows 官方客户端即可跑登录与「今日是否已签到」逻辑。

---

## 目录

1. [功能说明](#1-功能说明)
2. [环境要求](#2-环境要求)
3. [本机快速使用（分步）](#3-本机快速使用分步)
4. [云服务器部署（推荐，分步）](#4-云服务器部署推荐分步)
5. [日常运维与如何确认成功](#5-日常运维与如何确认成功)
6. [命令行参数与退出码](#6-命令行参数与退出码)
7. [环境变量一览](#7-环境变量一览)
8. [当前能力与已知限制](#8-当前能力与已知限制)
9. [安全与合规](#9-安全与合规)
10. [项目结构](#10-项目结构)

---

## 1. 功能说明

| 功能 | 说明 |
|------|------|
| 邮箱 + 密码登录 | 自动保存 / 刷新 `tokens.json` |
| 查询账号 | 流量余额、今日是否已签到等 |
| 每日签到 | 调用 `POST /me/checkins`（需安全封包） |
| 幂等 | 今日已签到则直接成功退出（适合 cron） |
| 云部署 | 一键 `install.sh` + systemd timer（默认每天约 08:05） |
| 日志 | 写入 `logs/checkin.log`，云上另有 `journalctl` |

---

## 2. 环境要求

- **Python 3.8+**（推荐 3.10 / 3.11 / 3.12）
  - 3.11+ 使用标准库 `tomllib`
  - 更低版本自动使用 `tomli`（已写入 `requirements.txt`）
- 能访问 `https://hyperdown.net`
- 云服务器建议开启 **NTP**，时区 **Asia/Shanghai**（签到与安全校验依赖时间）

依赖包（`requirements.txt`）：

```text
cryptography
PyNaCl
tomli   # 仅 Python < 3.11 需要
```

---

## 3. 本机快速使用（分步）

### 步骤 1：获取代码

```bash
git clone https://github.com/jasper0507/hyperdown-checkin.git
cd hyperdown-checkin
```

若仓库为私有，请先配置好 GitHub 登录（HTTPS Token 或 SSH 密钥）。

### 步骤 2：创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 步骤 3：填写账号配置

```bash
cp config.example.toml config.toml
chmod 600 config.toml
# 用编辑器打开 config.toml，填写 email / password
```

`config.example.toml` 示例字段：

```toml
api_base_url = "https://hyperdown.net"
email = "you@example.com"
password = "your-password"
user_agent = "Go-http-client/1.1"
# proxy = "http://127.0.0.1:7890"   # 可选
```

也可用环境变量代替文件（见 [第 7 节](#7-环境变量一览)）。

### 步骤 4：试跑

```bash
# 仅登录，写出 tokens.json
python3 checkin.py --login-only

# 查看账号信息（流量、是否已签到）
python3 checkin.py --me-only

# 执行签到（默认）
python3 checkin.py
```

### 步骤 5：看日志

```bash
tail -f logs/checkin.log
```

### 步骤 6（可选）：本机定时

- **Linux cron**：可参考 `deploy/crontab.example`
- **Windows**：任务计划程序每天执行 `python checkin.py`（工作目录设为项目根）

---

## 4. 云服务器部署（推荐，分步）

适合任意 Linux VPS（Ubuntu / Debian / CentOS 等）。账号密码放在服务器环境文件中，**不要**提交到 Git。

### 步骤 1：把代码放到服务器

任选一种方式：

```bash
# 方式 A：在服务器上 clone
git clone https://github.com/jasper0507/hyperdown-checkin.git
cd hyperdown-checkin

# 方式 B：从本机打包上传
scp -r hyperdown-checkin user@your-vps:/tmp/
ssh user@your-vps
cd /tmp/hyperdown-checkin
```

### 步骤 2：一键安装

```bash
sudo bash deploy/install.sh
```

安装脚本会：

1. 创建系统用户 `hyperdown`
2. 代码安装到 `/opt/hyperdown-checkin`，并创建 venv、安装依赖
3. 写入 systemd 单元：`hyperdown-checkin.service` / `hyperdown-checkin.timer`
4. 若尚无密钥文件，复制模板到 `/etc/hyperdown-checkin.env`（权限 600）
5. 启用定时器（默认每天 **08:05**，带约 2 分钟随机抖动）

### 步骤 3：填写邮箱与密码

```bash
sudo nano /etc/hyperdown-checkin.env
# 至少设置：
#   HYPERDOWN_EMAIL=你的邮箱
#   HYPERDOWN_PASSWORD=你的密码
sudo chmod 600 /etc/hyperdown-checkin.env
```

### 步骤 4：配置时区与 NTP（重要）

```bash
sudo timedatectl set-timezone Asia/Shanghai
sudo timedatectl set-ntp true
timedatectl   # 确认 NTP synchronized: yes
```

### 步骤 5：立刻试跑一次

```bash
sudo systemctl start hyperdown-checkin.service
sudo journalctl -u hyperdown-checkin.service -n 50 --no-pager
```

### 步骤 6：确认定时器已启用

```bash
systemctl list-timers hyperdown-checkin.timer
systemctl is-enabled hyperdown-checkin.timer
```

### 步骤 7（可选）：从开发机同步更新

在**开发机项目根目录**执行（按你的 SSH 配置改环境变量）：

```bash
export KEY=/path/to/your.pem
export HOST=user@your-vps-ip
bash deploy/sync-and-verify.sh
```

也可手动 `rsync` / `scp` 后再在服务器上 `sudo systemctl start hyperdown-checkin.service`。

### 备选：不用 systemd，改用 cron

见 `deploy/crontab.example`。环境变量放在 `/etc/hyperdown-checkin.env`，crontab 中 `source` 后执行即可。

### Docker（可选，无官方镜像）

可自行构建：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "checkin.py"]
```

再用宿主机 cron 或外部调度每天：

```bash
docker run --rm --env-file .env your-image
```

---

## 5. 日常运维与如何确认成功

### 手动再跑一次

```bash
sudo systemctl start hyperdown-checkin.service
```

### 看服务日志（推荐）

```bash
sudo journalctl -u hyperdown-checkin.service -n 50 --no-pager
# 持续跟踪
sudo journalctl -u hyperdown-checkin.service -f
```

### 看应用日志文件

```bash
tail -f /opt/hyperdown-checkin/logs/checkin.log
```

### 成功示例（今日已签到，幂等成功）

```text
[日期时间] 已登录: ... | 流量 x.xx GB | 今日已签到=True
[日期时间] 今日已签到。流量余额 ...，累计签到流量 ...
```

此时 `systemctl` 的 `Result=success`、`ExecMainStatus=0`。

### 查看下次定时触发

```bash
systemctl list-timers hyperdown-checkin.timer
```

### 修改定时时间

```bash
sudo systemctl edit hyperdown-checkin.timer
# 或编辑 /etc/systemd/system/hyperdown-checkin.timer 中的 OnCalendar
sudo systemctl daemon-reload
sudo systemctl restart hyperdown-checkin.timer
```

### 停用定时

```bash
sudo systemctl disable --now hyperdown-checkin.timer
```

### 故障对照（简表）

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 配置错误 / 退出码 1 | 未写 env 或 config | 检查 `/etc/hyperdown-checkin.env` 或 `config.toml` |
| 鉴权失败 / 退出码 2 | 邮箱密码错误 | 改密码后重试登录 |
| 网络错误 / 退出码 4 | 出网 / DNS / 代理 | 检查服务器能否访问 hyperdown.net |
| `secure_request_invalid` / 退出码 3 | 封包被服务端拒绝 | 确认 NTP/时区；勿在 env 中设置旧版 `HYPERDOWN_*_VARIANT`；见 [STATUS.md](./STATUS.md) |
| Python 报缺 `tomllib` | 系统 Python &lt; 3.11 且未装 tomli | 在 venv 中 `pip install tomli`，或跑 `deploy/remote-fix-tomllib.sh` |

---

## 6. 命令行参数与退出码

### 参数

| 参数 | 含义 |
|------|------|
| （无） | 登录 + 签到 |
| `--login-only` | 仅登录并保存 token |
| `--me-only` | 仅查询用户信息 |
| `--force` | 即使已签到也强制再调签到接口（服务端已签到仍 exit 0） |
| `--config PATH` | 指定配置文件路径 |

### 退出码

| Code | 含义 |
|------|------|
| 0 | 签到成功，或今日已签到 |
| 1 | 配置错误 |
| 2 | 登录 / 鉴权失败 |
| 3 | 签到或安全封包失败 |
| 4 | 网络错误 |

---

## 7. 环境变量一览

生产环境只需账号密码（云上写入 `/etc/hyperdown-checkin.env`，`chmod 600`）：

| 变量 | 含义 |
|------|------|
| `HYPERDOWN_EMAIL` | 登录邮箱 |
| `HYPERDOWN_PASSWORD` | 登录密码 |
| `HYPERDOWN_API_BASE` | API 根，默认 `https://hyperdown.net` |
| `HYPERDOWN_PROXY` | HTTP/HTTPS 代理 |
| `HYPERDOWN_USER_AGENT` | 默认 `Go-http-client/1.1`（与官方客户端一致） |

调试用（**默认已通过服务端校验，生产请勿设置**）：

| 变量 | 默认 | 含义 |
|------|------|------|
| `HYPERDOWN_KDF_VARIANT` | `ecdh_re_primary` | KDF 变体 |
| `HYPERDOWN_SIGN_VARIANT` | `v3_token_nul` | 签名字段拼法 |
| `HYPERDOWN_B64_VARIANT` | `rawurl` | Raw URL-safe Base64（无 padding） |
| `HYPERDOWN_SIGN_SEP` | `nul` | 签名字段分隔符 |
| `HYPERDOWN_SECURE_PEER_PUB` | 内嵌 hex | 覆盖对端 X25519 **公钥**（非账号密钥） |
| `HYPERDOWN_SECURE_MASTER_KEY` | （同上别名） | 兼容旧名，优先使用 `PEER_PUB` |

云上推荐只写 env 文件，无需 `config.toml`。

---

## 8. 当前能力与已知限制

更细的算法与运维说明见 [STATUS.md](./STATUS.md)。

| 能力 | 状态 | 说明 |
|------|------|------|
| 登录 / 刷新 token | ✅ | `POST /auth/login`、`/auth/refresh` |
| 查询用户 / 是否已签到 | ✅ | `GET /me/` |
| 今日已签到 → 退出 0 | ✅ | 幂等，适合 cron / timer |
| 真正发起签到 API | ✅ | 安全封包已对齐官方抓包；服务端已签到时 `--force` 仍 exit 0 |
| systemd 定时触发 | ✅ | 默认约每天 08:05（本地时区） |

### 安全封包（签到接口）

`POST /api/v1/me/checkins` 使用与官方 `SealJSON` 一致的信封（详见 STATUS.md）：

| 项 | 值 |
|----|-----|
| Header | `X-Hyperdown-Secure: v1` |
| 密钥协商 | 临时 X25519 + ECDH（对端公钥内嵌） |
| 派生 | HKDF-SHA256 |
| 加密 | XChaCha20-Poly1305 |
| 签名 | HMAC-SHA256（含 **access_token**） |
| 字段编码 | nonce / ciphertext / sign = **Raw URL Base64** |
| Envelope | `v, request_id, ts, nonce, pub, ciphertext, sign` |
| User-Agent | `Go-http-client/1.1` |
| 登录 | **无需**封包 |

### 运维注意

1. 保持服务器 **NTP** 与建议时区 **Asia/Shanghai**（`ts` 参与校验）
2. `/etc/hyperdown-checkin.env` 勿残留旧版 `HYPERDOWN_WIRE_VARIANT` 等无效变量
3. 已签到日默认只查询并 exit 0；未签到日才会真正打签到接口
4. 官方客户端升级后协议可能变化，届时需对照抓包更新 `secure_api.py`

---

## 9. 安全与合规

- **切勿**把 `config.toml`、`tokens.json`、`/etc/hyperdown-checkin.env`、私钥（`*.pem`）提交到 Git（见 `.gitignore`）
- 服务器上密钥文件请保持 `chmod 600`（`install.sh` 会强制设置）
- 手动调试请用 `sudo systemctl start hyperdown-checkin.service`，勿以 `hyperdown` 用户直接 `source` root 持有的 env
- 自动化可能违反服务条款，请**仅限个人学习 / 自用**
- 客户端升级后协议可能变化，届时需重新对照官方客户端
- 内嵌 `PEER_PUB` 是官方客户端中的 **X25519 公钥材料**，不是你的账号密码

---

## 10. 项目结构

```text
hyperdown-checkin/
├── checkin.py                 # 入口：登录 / 查询 / 签到
├── client.py                  # HTTP API 客户端
├── secure_api.py              # SealJSON 安全封包复现
├── config.example.toml        # 配置模板（复制为 config.toml）
├── requirements.txt
├── README.md                  # 本说明
├── STATUS.md                  # 算法与运维终态
├── .gitignore
└── deploy/
    ├── install.sh             # 云服务器一键安装
    ├── sync-and-verify.sh     # 从开发机同步并验证
    ├── remote-fix-tomllib.sh  # 旧 Python / tomli 修复
    ├── hyperdown-checkin.service
    ├── hyperdown-checkin.timer
    ├── env.example            # 云环境变量模板
    └── crontab.example        # cron 备选
```

---

## 许可与免责

本项目仅供个人学习与自用。使用本脚本产生的任何账号风险、服务条款问题，由使用者自行承担。
