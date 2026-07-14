# Hyperdown 自动签到 — 最终状态（2026-07-14）

## 结论

**安全封包已打通，服务器定时任务已就绪，技术债已收底。**

验证：

- `--force` 调签到 API → 服务端返回 `already_checked_in`（**不再是** `secure_request_invalid`）→ 脚本 exit 0  
- 正常路径：今日已签到 → 直接 exit 0  
- `hyperdown-checkin.timer`：enabled + active，约每天 08:05 本地时区（建议 Asia/Shanghai）  

## 工作算法（对照官方抓包 + 逆向）

```text
1. eph = X25519.GenerateKey()
2. shared = ECDH(eph.Private, NewPublicKey(embedded_32B_hex))  # 内嵌 hex = 对端公钥
3. request_id = randomHex(16)
4. key = HKDF-SHA256(
      ikm  = shared,
      salt = SHA256(request_id + ":" + ts),
      info = "hyperdown-secure-api:v1:" + METHOD + ":" + path,
      len  = 32)
5. aad = METHOD + "\n" + path + "\n" + request_id + "\n" + ts
6. sealed = XChaCha20-Poly1305.Seal(key, nonce24, body, aad)
7. Envelope JSON:
   v=v1, request_id, ts,
   nonce      = RawURLBase64(nonce24),
   pub        = hex(eph.Public),
   ciphertext = RawURLBase64(sealed),   # 无前置 AEAD nonce
   sign       = RawURLBase64(HMAC-SHA256(key, msg))
8. sign msg = join("\0",
     "v1", METHOD, path, request_id, str(ts), nonce, pub, ciphertext, access_token)
9. Header: X-Hyperdown-Secure: v1
   UA: Go-http-client/1.1
```

关键点：签名必须带上 **access_token**（与官方 `SealJSON(method, path, token, body)` 一致）。

默认变体（无需设置 env）：

| 项 | 值 |
|----|-----|
| KDF | `ecdh_re_primary` |
| SIGN | `v3_token_nul` |
| B64 | `rawurl` |

## 服务器

| 项 | 值 |
|----|-----|
| 代码 | `/opt/hyperdown-checkin` |
| 密钥 | `/etc/hyperdown-checkin.env`（`HYPERDOWN_EMAIL` / `HYPERDOWN_PASSWORD`） |
| 定时 | `hyperdown-checkin.timer` ≈ 08:05 |
| 日志 | `journalctl -u hyperdown-checkin.service` 与 `logs/checkin.log` |

### 运维

```bash
sudo systemctl start hyperdown-checkin.service          # 立刻跑一次
sudo journalctl -u hyperdown-checkin.service -n 40      # 看结果
systemctl list-timers hyperdown-checkin.timer
# 强制打签到 API（已签到日也应 exit 0）
sudo systemctl start hyperdown-checkin.service
# 或：
# KEY=... HOST=user@host bash deploy/sync-and-verify.sh
```

手动以 env 试跑时注意：env 文件通常是 root:root `600`，不要用 `sudo -u hyperdown source /etc/...`。

### 成功日志示例

```text
已登录: … | 流量 … | 今日已签到=False
开始签到（KDF=ecdh_re_primary, SIGN=v3_token_nul, B64=rawurl）…
签到成功！本次奖励 …
```

或已签到：

```text
今日已签到。…
# --force 时: 服务端确认今日已签到: 今天已经签到过了
```

## 技术债收底清单（已完成）

| 项 | 处理 |
|----|------|
| ECDH + token-in-sign 封包 | 默认路径，生产可用 |
| `already_checked_in` → exit 0 | 含 `--force` |
| UA 与官方一致 | 默认 `Go-http-client/1.1` |
| 删除失效 `--probe-secure` 矩阵 | 已移除 |
| README / env.example 与 STATUS 对齐 | 已更新 |
| `sync-and-verify.sh` 先 mkdir 再 scp | 已修 |
| `install.sh` 始终 `chmod 600` env、检查 rsync | 已修 |
| `.gitignore` 增补 `.env` / `*.pem` / `*.key` | 已修 |
| 空 token 时签名仍保留末字段 | 已修 |

未纳入本仓库（可选后续）：单元测试锁定信封字段与 sign 串布局。
