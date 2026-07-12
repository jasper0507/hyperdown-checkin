# Hyperdown 自动签到 — 收底状态（2026-07-12）

## 服务器部署（通用）

| 项 | 说明 |
|----|------|
| 安装路径 | `/opt/hyperdown-checkin` |
| 密钥文件 | `/etc/hyperdown-checkin.env`（建议 `chmod 600`） |
| 定时 | `hyperdown-checkin.timer`，默认每天约 08:05（服务器本地时区） |
| 时区 / NTP | 建议 `Asia/Shanghai`，开启 NTP |
| Python | 3.10+ + venv（&lt;3.11 需 `tomli`） |

### 运维命令

```bash
sudo systemctl start hyperdown-checkin.service          # 立刻跑一次
sudo journalctl -u hyperdown-checkin.service -n 50      # 看日志
systemctl list-timers hyperdown-checkin.timer           # 看下次触发
tail -f /opt/hyperdown-checkin/logs/checkin.log
```

### 同步代码

在开发机 `hyperdown-checkin` 目录：

```bash
export KEY=/path/to/your.pem
export HOST=user@your-vps-ip
bash deploy/sync-and-verify.sh
```

## 功能矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| 登录 / 刷新 token | ✅ | `POST /auth/login`、`/auth/refresh` |
| 查询用户 / 是否已签到 | ✅ | `GET /me/` |
| 今日已签到 → 退出 0 | ✅ | 幂等，适合 cron |
| 真正发起签到 API | ⚠️ | 安全封包仍可能返回 `secure_request_invalid` |
| systemd 定时触发 | ✅ | timer 可正常启用与触发 |

## 剩余技术债（签到加密）

客户端 `secureapi.SealJSON` 已逆向到：

- Header: `X-Hyperdown-Secure: v1`
- 算法: HKDF-SHA256 + XChaCha20-Poly1305 + HMAC-SHA256(Base64)
- 主密钥、盐前缀、敏感路径列表
- AAD 字段顺序: `method\npath\nnonce\nts`

但多种 KDF / 线格式 / 签名拼法实测仍可能 `secure_request_invalid`。  
**未签到日**会走到签到 API 并失败（exit 3）；**已签到日**不会调签到 API，脚本成功。

### 建议闭环方式

1. Windows 开官方 Hyperdown，mitmproxy/Fiddler 抓一次「点击签到」请求体  
2. 把 JSON（`ts/nonce/ciphertext/sign`）对照 `secure_api.py`  
3. 同步服务器后再 `systemctl start hyperdown-checkin.service` 验证  

## 文件清单

```text
hyperdown-checkin/
├── checkin.py / client.py / secure_api.py
├── config.example.toml / requirements.txt
├── README.md / STATUS.md
└── deploy/
    ├── install.sh
    ├── sync-and-verify.sh
    ├── remote-fix-tomllib.sh
    ├── hyperdown-checkin.service
    ├── hyperdown-checkin.timer
    ├── env.example
    └── crontab.example
```
