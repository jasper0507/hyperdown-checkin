# 状态与算法备忘

> 面向运维与二次开发。日常使用请先看 [README.md](./README.md)。

## 结论（2026-07-14）

| 项 | 状态 |
|----|------|
| 安全签到封包 | ✅ 与官方抓包对齐，服务端接受 |
| 幂等（已签到 → exit 0） | ✅ 含 `--force` 时服务端 `already_checked_in` |
| 云上 systemd timer | ✅ 约每天 08:05（本地时区，建议 Asia/Shanghai） |
| GitHub Actions | ✅ `.github/workflows/checkin.yml`（UTC 00:05 / 12:05 + 月度保活） |
| 默认变体 | `KDF=ecdh_re_primary` · `SIGN=v3_token_nul` · `B64=rawurl` |
| User-Agent | `Go-http-client/1.1` |

验证方式：

```bash
# 正常路径
sudo systemctl start hyperdown-checkin.service
sudo journalctl -u hyperdown-checkin.service -n 20 --no-pager

# 强制走签到 API（封包路径）
sudo bash -c 'set -a; source /etc/hyperdown-checkin.env; set +a; \
  sudo -u hyperdown env HYPERDOWN_EMAIL="$HYPERDOWN_EMAIL" \
  HYPERDOWN_PASSWORD="$HYPERDOWN_PASSWORD" \
  /opt/hyperdown-checkin/.venv/bin/python /opt/hyperdown-checkin/checkin.py --force'
```

期望：`--force` 在已签到日返回「今天已经签到过了」且 **exit 0**（不是 `secure_request_invalid`）。

---

## 工作算法（官方 SealJSON 对齐）

```text
1. eph = X25519.GenerateKey()
2. shared = ECDH(eph.Private, NewPublicKey(embedded_32B_hex))  # 内嵌 = 对端公钥
3. request_id = randomHex(16)
4. key = HKDF-SHA256(
      ikm  = shared,
      salt = SHA256(request_id + ":" + ts),
      info = "hyperdown-secure-api:v1:" + METHOD + ":" + path,
      len  = 32)
5. aad = METHOD + "\n" + path + "\n" + request_id + "\n" + ts
6. sealed = XChaCha20-Poly1305.Seal(key, nonce24, body, aad)
7. Envelope:
   v, request_id, ts,
   nonce      = RawURLBase64(nonce24),
   pub        = hex(eph.Public),
   ciphertext = RawURLBase64(sealed),   # 无前置 AEAD nonce
   sign       = RawURLBase64(HMAC-SHA256(key, msg))
8. sign msg = join("\0",
     "v1", METHOD, path, request_id, str(ts), nonce, pub, ciphertext, access_token)
9. Header: X-Hyperdown-Secure: v1
   UA: Go-http-client/1.1
```

关键点：HMAC 必须包含 **access_token**（与官方 `SealJSON(method, path, token, body)` 一致）。

HTTP 路径：`POST {base}/me/checkins`（base 默认含 `/api/v1`）。  
封包 path 字符串：`/api/v1/me/checkins`。

---

## 服务器布局

| 项 | 路径 / 值 |
|----|-----------|
| 代码 | `/opt/hyperdown-checkin` |
| 密钥 | `/etc/hyperdown-checkin.env`（仅 EMAIL / PASSWORD 即可） |
| 定时 | `hyperdown-checkin.timer` ≈ 08:05 |
| 日志 | `journalctl -u hyperdown-checkin.service` · `logs/checkin.log` |
| 运行用户 | `hyperdown`（systemd drop 权限） |

```bash
sudo systemctl start hyperdown-checkin.service
sudo journalctl -u hyperdown-checkin.service -n 40 --no-pager
systemctl list-timers hyperdown-checkin.timer
```

成功日志示例：

```text
已登录: … | 流量 … | 今日已签到=False
开始签到（KDF=ecdh_re_primary, SIGN=v3_token_nul, B64=rawurl）…
签到成功！本次奖励 …
```

或：

```text
今日已签到。…
# --force: 服务端确认今日已签到: 今天已经签到过了
```

---

## 排错提示

1. **NTP / 时区**：`timedatectl` 应显示 synchronized + 建议 `Asia/Shanghai`。  
2. **勿在 env 设置过期调试变量**：如已删除的 `HYPERDOWN_WIRE_VARIANT`、错误 KDF 名。  
3. **env 权限**：`root:root 600` 正确；手动跑请用 root `source` 后再 `sudo -u hyperdown env …`。  
4. 客户端大版本升级后协议可能变，需重新抓包对照 `secure_api.py`。
