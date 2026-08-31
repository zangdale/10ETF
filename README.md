# 10ETF

单页持仓展示：`index.html` 读取根目录 **`etf_hold.json`**。历史折线见 **`history.html`**（`etf_hold/*.json`）。

## 拉取持仓

`.env` 中配置 `ADB_PATH`（可选 `ADB_DEVICE`）。若配置了 `TIINGO_API_KEY`，会额外拉取 Tiingo 名称。手机/模拟器已打开同花顺交易页时：

```bash
make hold
```

配置了 `TIINGO_API_KEY` 时，`make hold` 会请求 Tiingo 并写入 `tiingo_name`；未配置则跳过。页面图例与名称列使用 `name`（同花顺简称），显示为 `名称[代码]`。`515180` 固定为「中证红利」。

- `etf_hold.json`：最新快照（当前持仓页）
- `etf_hold/yyyy-mm-dd.json`：当日历史（同日多次运行会覆盖；历史持仓页按日期画折线）
- `etf_hold/index.json`：历史日期清单（本地 `serve.py` 也会按目录动态列出）

## 本地预览

```bash
make serve
```

默认打开 `http://127.0.0.1:8080/index.html`。本地服务会监视 `index.html`、`etf_hold.json`，保存后浏览器自动刷新（不要用 `file://`）。换端口：`make serve PORT=9000`。若 8080 已被旧的 `http.server` 占用，先结束该进程或换端口，否则没有热更新。

## 部署

GitHub Actions 将根目录 `*.html`、`etf_hold.json` 与 `etf_hold/` 复制到 `dist/` 后部署 Cloudflare Pages（项目名示例：`10etf`）。
