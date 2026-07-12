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
user_agent = "Mozilla/5.0 Hyperdown/3.0"
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
| `secure_request_invalid` / 退出码 3 | 签到安全封包未对齐 | 见 [第 8 节](#8-当前能力与已知限制) |
| Python 报缺 `tomllib` | 系统 Python &lt; 3.11 且未装 tomli | 在 venv 中 `pip install tomli`，或跑 `deploy/remote-fix-tomllib.sh` |

---

## 6. 命令行参数与退出码

### 参数

| 参数 | 含义 |
|------|------|
| （无） | 登录 + 签到 |
| `--login-only` | 仅登录并保存 token |
| `--me-only` | 仅查询用户信息 |
| `--probe-secure` | 探测安全封包 KDF/线格式变体（调试） |
| `--force` | 即使已签到也强制再调签到接口 |
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

| 变量 | 含义 |
|------|------|
| `HYPERDOWN_EMAIL` | 登录邮箱 |
| `HYPERDOWN_PASSWORD` | 登录密码 |
| `HYPERDOWN_API_BASE` | API 根，默认 `https://hyperdown.net` |
| `HYPERDOWN_PROXY` | HTTP/HTTPS 代理 |
| `HYPERDOWN_USER_AGENT` | User-Agent |
| `HYPERDOWN_KDF_VARIANT` | 安全封包 KDF 变体（调试） |
| `HYPERDOWN_WIRE_VARIANT` | 安全封包线格式变体（调试） |
| `HYPERDOWN_SIGN_VARIANT` | 签名消息拼法变体（调试） |
| `HYPERDOWN_SECURE_MASTER_KEY` | 覆盖内嵌主密钥 hex（一般无需改） |

云上推荐只写 `/etc/hyperdown-checkin.env`，无需 `config.toml`。

---

## 8. 当前能力与已知限制

更细的收底说明见 [STATUS.md](./STATUS.md)。

| 能力 | 状态 | 说明 |
|------|------|------|
| 登录 / 刷新 token | ✅ | `POST /auth/login`、`/auth/refresh` |
| 查询用户 / 是否已签到 | ✅ | `GET /me/` |
| 今日已签到 → 退出 0 | ✅ | 幂等，适合 cron |
| 真正发起签到 API | ⚠️ | 安全封包可能仍返回 `secure_request_invalid` |
| systemd 定时触发 | ✅ | timer 可正常启用与触发 |

### 安全封包（签到接口）

签到需要客户端 `secureapi.SealJSON` 风格封包。逆向已确认：

| 项 | 值 |
|----|-----|
| Header | `X-Hyperdown-Secure: v1` |
| 算法 | HKDF-SHA256 + XChaCha20-Poly1305 + HMAC-SHA256 |
| Envelope | `{ "ts", "nonce", "ciphertext", "sign" }` |
| 签名编码 | HMAC 摘要再 **Base64** |
| 敏感路径示例 | `/api/v1/me/checkins` 等 |
| 登录 | **无需**封包 |

结构正确时，错误会从 `secure_request_required` 变为 `secure_request_invalid`（说明过了「要不要封包」这道门，差在 KDF / AAD / 线格式精确拼法）。

### 若返回 `secure_request_invalid`

1. 确认服务器时间准确（NTP）
2. 运行 `python3 checkin.py --probe-secure` 试变体
3. 按 README 第 7 节调整 `HYPERDOWN_*_VARIANT`
4. **推荐闭环**：用官方客户端 + mitmproxy/Fiddler 抓一次「点击签到」的请求体（`ts/nonce/ciphertext/sign`），对照修改 `secure_api.py` 后同步到服务器再试跑

**说明**：在**已签到日**，脚本不会调用签到 API，只会查询并成功退出；在**未签到日**才会真正打签到接口，此时若封包未对齐会失败（退出码 3）。

---

## 9. 安全与合规

- **切勿**把 `config.toml`、`tokens.json`、`/etc/hyperdown-checkin.env` 提交到 Git（已在 `.gitignore` 中忽略前两者）
- 服务器上密钥文件请保持 `chmod 600`
- 自动化可能违反服务条款，请**仅限个人学习 / 自用**
- 客户端升级后协议可能变化，届时需重新对照官方客户端
- 本仓库默认建议设为 **Private**

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
├── STATUS.md                  # 收底状态与技术债
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
