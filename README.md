# 10ETF

单页持仓展示：`index.html` 读取根目录 **`etf_hold.json`**。历史折线见 **`history.html`**（`etf_hold/*.json`）。历史日 K 见 **`kline.html`**（`kline/yyyy/code.json`）。组合定投回测见 **`backtest.html`**。

## 拉取持仓

`.env` 中配置 `ADB_PATH`（可选 `ADB_DEVICE`）。若配置了 `TIINGO_API_KEY`，会额外拉取 Tiingo 名称。手机/模拟器已打开同花顺交易页时：

```bash
make hold
```

配置了 `TIINGO_API_KEY` 时，`make hold` 会请求 Tiingo 并写入 `tiingo_name`；未配置则跳过。页面图例与名称列使用 `name`（同花顺简称），显示为 `名称[代码]`。`515180` 固定为「中证红利」。

- `etf_hold.json`：最新快照（当前持仓页）
- `etf_hold/yyyy-mm-dd.json`：当日历史（同日多次运行会覆盖；历史持仓页按日期画折线）
- `etf_hold/index.json`：历史日期清单（本地 `serve.py` 也会按目录动态列出）

## 拉取日 K

`.env` 中配置 `TIINGO_API_KEY` 后：

```bash
make kline
```

默认**增量**：读取 `kline/info.json` 与已有年份文件，只拉取本地 `end` 之后的新 K 线并合并；某只 ETF 无本地数据时自动全量。强制全量重拉：

```bash
make kline FULL=1
```

- `kline/yyyy/code.json`：按年保存的日 K（open/high/low/close/volume）
- `kline/info.json`：每只 ETF 的数据起止日期与条数

## 本地预览

```bash
make serve
```

默认打开 `http://127.0.0.1:8080/index.html`，并**前台**运行 `serve.py`（Ctrl+C 结束）。若端口已被占用，会先结束占用进程再启动。换端口：`make serve PORT=9000`。不要用 `file://` 打开页面。

## 雪球同屏

```bash
make desktop
```

在 `http://127.0.0.1:8765/` 把 `kline/info.json` 里的 10 只 ETF 雪球页裁到同一屏，只留主体（报价、走势、讨论）。换端口：`make desktop DESKTOP_PORT=8766`。页面里的「微调」可改上下左右偏移。

## 菜单栏涨幅

```bash
make tray
```

在菜单栏显示 **10ETF**。点击展开今日涨跌幅榜（高到低），每行带上现价和相对实时净值的溢价。涨为红色，跌为绿色，平盘为系统原色。点某一只打开对应的雪球页。约 15 秒刷新一次，菜单里也可以点「刷新」。Ctrl+C 或菜单「退出」结束。

打包成可双击的菜单栏应用（不出现在程序坞）：

```bash
make tray-build
```

生成项目根目录的 `10ETF.app`。构建时会把当时的 `kline/info.json` 放进应用包。

## 部署

GitHub Actions 将根目录 `*.html`、`etf_hold.json`、`etf_hold/` 与 `kline/` 复制到 `dist/` 后部署 Cloudflare Pages（项目名示例：`10etf`）。
