.PHONY: hold serve

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
