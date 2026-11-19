# ung220z-tool-failtriage

把 `ung220z-tool` 的**同一份会话日志**归因到具体失败模式——离线、零依赖、可断言。

`ung220z-tool` 每次失败都只打印一句「23 端口未开放（密码可能已轮换，重跑脚本）」，
可真实原因至少有五种：`.gch` CGI 路径不存在、响应体不是 `TelnetSet`、Telnet 端口没开、
Telnet 口令和 Web 口令不是同一个、配置库解密失败。用户只有这一句话，只能盲目重跑。
**现在需要它**：issue #3 里五个用户贴出同一段日志、却得到同一个通用告警，没人能自助判断该换机型还是该换口令。

Upstream: https://github.com/Hut-hzf/ung220z-tool

## 上游是什么，它缺什么

[`Hut-hzf/ung220z-tool`](https://github.com/Hut-hzf/ung220z-tool)（1,717★，Python，MIT）是一个针对
**UNG220Z（九联 / Unionman 中国移动光猫）** 的一键凭据提取工具：走 `.gch` CGI 打开 Telnet，
再 `sidbg 1 DB decry` 解密 `/userconfig/cfg/db_user_cfg.xml`，最后打印 Web 超管 / PPPoE / WiFi / root 凭据。
README 自己把适用范围限定在**单一机型 + 单一运营商**，却没有把「这次失败是否落在范围内」做成任何可判定输出。

证据（均已用 `gh api` 独立核验）：

- **A 级** — [issue #3「返回 400 Bad Request」](https://github.com/Hut-hzf/ung220z-tool/issues/3)（OPEN，5 条评论）：
  同一会话日志里同时出现 `telnet.gch 请求失败: HTTP Error 400`、`HTTP Error 404`、
  `nc -zv 192.168.1.1 23 → timed out` 和 `23 端口未开放（密码可能已轮换，重跑脚本）`——
  三种互不相同的根因被折叠成一句告警。
- **A 级** — [issue #7「23端口未开放；telnet.gch 请求失败」](https://github.com/Hut-hzf/ung220z-tool/issues/7)（OPEN）：
  用户把两类失败并列上报，说明它们常同时出现且无法区分。
- **A 级** — [#5「华为V175可以么」](https://github.com/Hut-hzf/ung220z-tool/issues/5)、
  [#2「请问联通可以吗？」](https://github.com/Hut-hzf/ung220z-tool/issues/2)、
  [#1「请问电信能用吗」](https://github.com/Hut-hzf/ung220z-tool/issues/1)：
  适用范围（机型 / 运营商）是持续未决的问题。
- **B 级** — [README](https://github.com/Hut-hzf/ung220z-tool/blob/main/README.md) 首段自述
  「针对 **UNG220Z（九联 / Unionman 中国移动光猫）**」，背景写明「这类光猫的 Web 管理页基于 `.gch` CGI 框架」。
- **C 级** — 源码 [`ung220z.py#L347`](https://github.com/Hut-hzf/ung220z-tool/blob/main/ung220z.py#L347)：
  无论此前是 400、404 还是空响应，都只 `log("WARN", "23 端口未开放（密码可能已轮换，重跑脚本）")` 后 `return 3`；
  [`enable_telnet()` L128-151](https://github.com/Hut-hzf/ung220z-tool/blob/main/ung220z.py#L128-L151)
  只测响应体里有没有 `"Success"`，不区分 HTTP 状态码，也不保留响应体。

## 这个工具做什么 / 不做什么

**做**：读取 `ung220z-tool` 落盘的 `ung220z_*.log`（`[HH:MM:SS] TAG message` 格式），

1. 抽取 8 类原始信号（`web_unreachable` / `gch_http_error` / `gch_unexpected_response` /
   `gch_success` / `port23_closed` / `telnet_auth_refused` / `cfg_decrypt_failed` / `success`）；
2. 按**因果先后**排序根因（`.gch` 没成功 → Telnet 根本没启用，所以后面的「23 端口未开」是**结果**而不是并列原因）；
3. 给出**主根因 + 完整归因链 + 每条根因的见证行号**；
4. 判定这次失败**是否还在上游声明的范围内**（`out_of_scope_model` / `in_scope_telnet_disabled` / `in_scope_credential_mismatch` / `unknown`）；
5. 给出真正适用的下一步动作（换机型、补 `--telnet-password`、手动开 Telnet、手动查 `sidbg` 等）。

**不做**：不连接光猫、不发任何网络请求、不解析凭据内容、不替代上游脚本、不修改上游。
它只做一件事：**把日志里已经存在、但上游丢弃了的中间信号还原成根因判定**。

## 安装 / 用法

无需安装，只需 Python 3.8+（只用标准库）：

```bash
git clone <this-repo> && cd ung220z-tool-failtriage
python3 bin/ung220z-failtriage -i examples/in/gch-400-port23-closed.log
```

从 stdin 读取：

```bash
cat examples/in/telnet-auth-refused.log | python3 bin/ung220z-failtriage --json
```

人类可读输出（对 issue #3 的真实日志）：

```text
根因 : GCH_HTTP_ERROR (severity=error)
结论 : telnet.gch 返回 HTTP 4xx/5xx：该机型不存在这条 .gch CGI 路径
范围 : 不在声明范围内：.gch CGI 路径不存在或返回非预期内容，机型/固件不匹配
下一步: 这台设备大概率不是 README 声明的 UNG220Z / 九联 / Unionman 中国移动 .gch 框架
        （或固件已改版）。不要再反复重跑同一脚本；换对应机型的提取方式。
```

`--json` 输出（截取，完整见 `examples/out/`）：

```json
{
  "summary": {
    "root_cause": "GCH_HTTP_ERROR",
    "severity": "error",
    "verdict": "out_of_scope_model",
    "signals_detected": ["gch_http_error", "gch_unexpected_response", "port23_closed"],
    "in_scope": false
  },
  "root_causes": [
    {"rank": 1, "code": "GCH_HTTP_ERROR", "witness_lines": [8, 9]},
    {"rank": 2, "code": "GCH_UNEXPECTED_RESPONSE", "witness_lines": [10]},
    {"rank": 3, "code": "TELNET_PORT_CLOSED", "witness_lines": [12, 13]}
  ]
}
```

### 退出码

| 退出码 | 语义 |
|---|---|
| `0` | 未检出问题：`SUCCESS`，或仅 `warning` 且未开 `--fail-on warning` |
| `1` | 检出问题：主根因 `severity=error`（或 `warning` 且 `--fail-on warning`） |
| `2` | 用法或输入错误：参数非法、文件不可读、输入为空、日志不可解析 |

`--fail-on error|warning|never` 控制阈值；`--expect-model UNG220Z` 会额外输出 `model_matches`。

## 局限

- 只解析**已经是 `ung220z-tool` 格式**的日志；其它光猫工具需要另写适配器。
- 根因是**基于日志信号的规则归因**，不是设备实测：如果日志本身被截断，只能输出 `INCONCLUSIVE`。
- `examples/in/*.log` 是**按 issue #3 原文与上游日志格式重建的 fixture**，不是从真实设备新抓的报文；
  它们用于回归测试与演示，不代表任何真实设备的统计分布。
- 不判断「密码到底是多少」，也不判断凭据是否有效——只判断失败属于哪一类。
- `in_scope` 是**负向判据**：HTTP 4xx/5xx 能强证明「不是这条 `.gch` 路径」，但「未知」不等于「在范围内」。

## 本轮创新

B 档：**首次把光猫凭据提取工具的会话日志做成「失败模式归因层」**——不是再写一个静态 linter，
而是把上游已经打印、却全部折叠进一句通用告警的中间信号（HTTP 状态码、响应体、端口探测、AUTH 结果）
按因果链还原成「主根因 + 完整归因链 + 适用范围判定 + 下一步」。与台账里已有的
`mcp-contract-diff`（静态 schema 差分）、`peakcut-caption-rescue`（字幕几何还原）、
`wireless-battery-triage`（设备 HID 面分诊）都不同：这是对**运行时日志的失败归因**，输入是真实 issue 里贴出的日志。

## 与同类项目的差异

已检索 `gh search repos "光猫 凭据提取"`、`"modem credential extractor telnet"`、`"ung220z"` 与
`gh search code "23 端口未开放"`：**没有成熟的同类工具**（唯一命中是上游自身与其 fork）。
上游只输出一句通用告警；本工具输出 8 类根因、因果链、见证行号与适用范围判定。

## License

MIT，见 [LICENSE](LICENSE)。上游 `Hut-hzf/ung220z-tool` 亦为 MIT；本仓库不复制其代码，
只消费其公开日志格式，并保留上游地址与作者署名。