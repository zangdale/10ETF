package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"sync"
	"syscall"
	"time"

	"github.com/getlantern/systray"
)

const refreshEvery = 15 * time.Second

func main() {
	hideDockIcon()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		fmt.Println("收到退出信号:", <-sig)
		systray.Quit()
	}()
	systray.Run(onReady, func() { fmt.Println("菜单栏已退出") })
}

func onReady() {
	installMenuTitleColor()

	icon := trayIcon()
	systray.SetTemplateIcon(icon, icon)
	// systray.SetTitle("10ETF")
	systray.SetTooltip("10ETF 今日涨幅")

	header := systray.AddMenuItem("今日涨幅", "按今日涨跌幅从高到低")
	header.Disable()

	etfs, err := loadETFs()
	var slots []*systray.MenuItem
	if err != nil {
		bad := systray.AddMenuItem(err.Error(), "")
		bad.Disable()
	} else {
		slots = make([]*systray.MenuItem, len(etfs))
		for i := range slots {
			slots[i] = systray.AddMenuItem("…", "")
		}
	}

	systray.AddSeparator()
	market := systray.AddMenuItem("大盘", "主要指数今日涨幅")
	specs := marketIndices()
	indexBoard := &rankBoard{}
	indexBoard.set(indexPlaceholders(specs))
	prepareIndexMenu(len(specs))
	for i, spec := range specs {
		setIndexMenuItem(i, indexTitle(spec.Name, "…"), xueqiuSymbolURL(spec.Symbol))
	}
	go func() {
		for range market.ClickedCh {
			popIndexMenu()
		}
	}()

	systray.AddSeparator()
	status := systray.AddMenuItem("正在获取行情…", "")
	status.Disable()
	refresh := systray.AddMenuItem("刷新", "重新获取今日涨幅")
	quit := systray.AddMenuItem("退出", "退出 10ETF")

	refreshCh := make(chan struct{}, 1)
	go func() {
		for {
			select {
			case <-refresh.ClickedCh:
				select {
				case refreshCh <- struct{}{}:
				default:
				}
			case <-quit.ClickedCh:
				systray.Quit()
				return
			}
		}
	}()

	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		go poll(nil, nil, status, refreshCh, nil, indexBoard)
		return
	}
	fmt.Println("10ETF 已在菜单栏，点击图标查看今日涨幅")
	board := &rankBoard{}
	for i, slot := range slots {
		go watchQuoteClick(slot, board, i)
	}
	go poll(etfs, slots, status, refreshCh, board, indexBoard)
}

func indexPlaceholders(specs []indexSpec) []quote {
	out := make([]quote, len(specs))
	for i, spec := range specs {
		out[i] = quote{Code: spec.Symbol, Name: spec.Name}
	}
	return out
}

func watchQuoteClick(slot *systray.MenuItem, board *rankBoard, index int) {
	for range slot.ClickedCh {
		q, ok := board.at(index)
		if !ok {
			continue
		}
		if err := openURL(xueqiuURL(q.Code)); err != nil {
			fmt.Fprintf(os.Stderr, "打开详情失败 %s: %v\n", q.Code, err)
		}
	}
}

func openURL(raw string) error {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", raw)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", raw)
	default:
		cmd = exec.Command("xdg-open", raw)
	}
	return cmd.Start()
}

type rankBoard struct {
	mu     sync.Mutex
	quotes []quote
}

func (b *rankBoard) set(quotes []quote) {
	b.mu.Lock()
	b.quotes = append([]quote(nil), quotes...)
	b.mu.Unlock()
}

func (b *rankBoard) snapshot() []quote {
	if b == nil {
		return nil
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	return append([]quote(nil), b.quotes...)
}

func (b *rankBoard) at(i int) (quote, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if i < 0 || i >= len(b.quotes) {
		return quote{}, false
	}
	return b.quotes[i], true
}

func poll(etfs []etf, slots []*systray.MenuItem, status *systray.MenuItem, refreshCh <-chan struct{}, board *rankBoard, indexBoard *rankBoard) {
	ticker := time.NewTicker(refreshEvery)
	defer ticker.Stop()
	var shown bool
	for {
		if slots != nil && board != nil {
			shown = updateMenu(etfs, slots, status, shown, board)
		}
		updateIndices(indexBoard)
		select {
		case <-ticker.C:
		case <-refreshCh:
		}
	}
}

func updateIndices(board *rankBoard) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	rows, err := fetchIndices(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "指数行情获取失败: %v\n", err)
		return
	}
	for i, q := range rows {
		setIndexMenuItem(i, indexTitle(q.Name, formatPctOrDash(q.Pct)), xueqiuSymbolURL(q.Code))
	}
	board.set(rows)
}

func updateMenu(etfs []etf, slots []*systray.MenuItem, status *systray.MenuItem, shown bool, board *rankBoard) bool {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	quotes, err := fetchQuotes(ctx, etfs)
	if err == nil && board != nil {
		keepPremiums(board.snapshot(), quotes)
	}
	if err != nil {
		if shown {
			status.SetTitle("行情获取失败，显示上次结果")
		} else {
			status.SetTitle("行情获取失败")
		}
		fmt.Fprintf(os.Stderr, "行情获取失败: %v\n", err)
		return shown
	}
	for i, q := range quotes {
		if i >= len(slots) {
			break
		}
		prem := ""
		if q.Premium != nil {
			prem = formatPct(*q.Premium)
		}
		slots[i].SetTitle(rowTitle(i+1, q.Name, prem, formatPctOrDash(q.Pct)))
		slots[i].SetTooltip(q.tip())
	}
	board.set(quotes)
	status.SetTitle(time.Now().Format("15:04:05") + " 更新")
	tip := "10ETF 今日涨幅"
	if len(quotes) > 0 {
		q := quotes[0]
		tip = fmt.Sprintf("%s · %s %s %s %s", tip, q.Name, formatPrice(q.Price), formatPctOrDash(q.Pct), formatPctOrDash(q.Premium))
	}
	systray.SetTooltip(tip)
	fmt.Printf("%s  %s\n", time.Now().Format("15:04:05"), summaryLine(quotes))
	return true
}
