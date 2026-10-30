.PHONY: hold kline serve tray tray-build

PORT ?= 8080

ifneq (,$(wildcard .env))
include .env
export
endif

# 通过 adb 读取同花顺持仓，写入 etf_hold.json 与 etf_hold/yyyy-mm-dd.json
hold:
	@if [ ! -f .env ]; then \
		echo "未找到 .env，请创建该文件并配置 ADB_PATH"; \
		exit 1; \
	fi
	@if [ -z "$(strip $(ADB_PATH))" ]; then \
		echo "未配置 ADB_PATH，请在 .env 中设置，例如："; \
		echo "ADB_PATH=/Users/you/Library/Android/sdk/platform-tools/adb"; \
		exit 1; \
	fi
	@test -x "$(ADB_PATH)" || (echo "找不到可执行文件: $(ADB_PATH)" && exit 1)
	python3 fetch_hold.py

# 拉取 10 只 ETF 日 K（东财失败时改用腾讯），写入 kline/yyyy/code.json 与 kline/info.json；分红记在对应交易日的 dps
# 默认增量；全量：make kline FULL=1
kline:
	python3 kline.py $(if $(FULL),--full,)

# 本地预览：前台运行 serve.py（Ctrl+C 结束）
serve:
	@echo "http://127.0.0.1:$(PORT)/index.html"
	@pids=$$(lsof -nP -tiTCP:$(PORT) -sTCP:LISTEN 2>/dev/null); \
	if [ -n "$$pids" ]; then \
		echo "端口 $(PORT) 已被占用，结束进程 $$pids 后前台启动"; \
		kill $$pids 2>/dev/null || true; \
		sleep 0.3; \
	fi
	@(sleep 0.4 && python3 -c "import webbrowser; webbrowser.open('http://127.0.0.1:$(PORT)/index.html')") &
	python3 serve.py $(PORT)

# 菜单栏显示 10 只 ETF 今日涨幅（点击图标展开；Ctrl+C 结束）
tray:
	cd desktop/tray && CGO_ENABLED=1 go run .

# 打包菜单栏程序为 10ETF.app（仅 macOS，不显示在程序坞）
tray-build:
	@if [ "$$(uname)" != "Darwin" ]; then \
		echo "tray-build 仅支持 macOS"; \
		exit 1; \
	fi
	rm -rf 10ETF.app
	mkdir -p 10ETF.app/Contents/MacOS 10ETF.app/Contents/Resources/kline
	cd desktop/tray && CGO_ENABLED=1 go build -ldflags "-s -w" -o ../../10ETF.app/Contents/MacOS/10ETF .
	cp desktop/tray/Info.plist 10ETF.app/Contents/Info.plist
	cp kline/info.json 10ETF.app/Contents/Resources/kline/info.json
	@set -e; \
	tmp=$$(mktemp -d); \
	trap 'rm -rf "$$tmp"' EXIT; \
	(cd desktop/tray && go run appicon.go "$$tmp/icon.png"); \
	iconset="$$tmp/10ETF.iconset"; \
	mkdir -p "$$iconset"; \
	sips -z 16 16 "$$tmp/icon.png" --out "$$iconset/icon_16x16.png" >/dev/null; \
	sips -z 32 32 "$$tmp/icon.png" --out "$$iconset/icon_16x16@2x.png" >/dev/null; \
	sips -z 32 32 "$$tmp/icon.png" --out "$$iconset/icon_32x32.png" >/dev/null; \
	sips -z 64 64 "$$tmp/icon.png" --out "$$iconset/icon_32x32@2x.png" >/dev/null; \
	sips -z 128 128 "$$tmp/icon.png" --out "$$iconset/icon_128x128.png" >/dev/null; \
	sips -z 256 256 "$$tmp/icon.png" --out "$$iconset/icon_128x128@2x.png" >/dev/null; \
	sips -z 256 256 "$$tmp/icon.png" --out "$$iconset/icon_256x256.png" >/dev/null; \
	sips -z 512 512 "$$tmp/icon.png" --out "$$iconset/icon_256x256@2x.png" >/dev/null; \
	sips -z 512 512 "$$tmp/icon.png" --out "$$iconset/icon_512x512.png" >/dev/null; \
	sips -z 1024 1024 "$$tmp/icon.png" --out "$$iconset/icon_512x512@2x.png" >/dev/null; \
	iconutil -c icns "$$iconset" -o 10ETF.app/Contents/Resources/10ETF.icns
	codesign --force --sign - 10ETF.app
	@echo "已生成 10ETF.app"
