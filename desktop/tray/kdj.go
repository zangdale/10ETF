package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const kdjPeriod = 9

type klineBar struct {
	Date  string
	Open  float64
	High  float64
	Low   float64
	Close float64
}

type klineCache struct {
	mu   sync.Mutex
	bars map[string][]klineBar
}

var klineData klineCache

func (c *klineCache) get(code string) ([]klineBar, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	b, ok := c.bars[code]
	if !ok {
		return nil, false
	}
	return append([]klineBar(nil), b...), true
}

func (c *klineCache) set(code string, bars []klineBar) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.bars == nil {
		c.bars = map[string][]klineBar{}
	}
	c.bars[code] = append([]klineBar(nil), bars...)
}

func findKlineDir() (string, error) {
	info, err := findInfoJSON()
	if err != nil {
		return "", err
	}
	return filepath.Dir(info), nil
}

func loadLocalKlineBars(code string) ([]klineBar, error) {
	dir, err := findKlineDir()
	if err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	var all []klineBar
	for _, ent := range entries {
		if !ent.IsDir() {
			continue
		}
		name := ent.Name()
		if len(name) != 4 {
			continue
		}
		path := filepath.Join(dir, name, code+".json")
		bars, err := readKlineFile(path)
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return nil, err
		}
		all = append(all, bars...)
	}
	if len(all) == 0 {
		return nil, os.ErrNotExist
	}
	sortKlineBars(all)
	return all, nil
}

func readKlineFile(path string) ([]klineBar, error) {
	body, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var payload struct {
		Items []struct {
			Date   string  `json:"date"`
			Open   float64 `json:"open"`
			High   float64 `json:"high"`
			Low    float64 `json:"low"`
			Close  float64 `json:"close"`
			Volume int64   `json:"volume"`
		} `json:"items"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, err
	}
	out := make([]klineBar, 0, len(payload.Items))
	for _, it := range payload.Items {
		date := strings.TrimSpace(it.Date)
		if date == "" {
			continue
		}
		out = append(out, klineBar{
			Date:  date,
			Open:  it.Open,
			High:  it.High,
			Low:   it.Low,
			Close: it.Close,
		})
	}
	return out, nil
}

func sortKlineBars(bars []klineBar) {
	sort.Slice(bars, func(i, j int) bool { return bars[i].Date < bars[j].Date })
}

func mergeTodayBar(bars []klineBar, price *float64, today string) []klineBar {
	if price == nil || *price <= 0 || len(bars) == 0 {
		return bars
	}
	out := append([]klineBar(nil), bars...)
	last := out[len(out)-1]
	p := *price
	if last.Date == today {
		last.Close = p
		if p > last.High {
			last.High = p
		}
		if p < last.Low || last.Low <= 0 {
			last.Low = p
		}
		out[len(out)-1] = last
		return out
	}
	if last.Date > today {
		return out
	}
	open := last.Close
	if open <= 0 {
		open = p
	}
	hi, lo := open, open
	if p > hi {
		hi = p
	}
	if p < lo {
		lo = p
	}
	out = append(out, klineBar{Date: today, Open: open, High: hi, Low: lo, Close: p})
	return out
}

func calcKDJK(bars []klineBar) (float64, bool) {
	if len(bars) < kdjPeriod {
		return 0, false
	}
	k, d := 50.0, 50.0
	for i := range bars {
		if i < kdjPeriod-1 {
			continue
		}
		start := i - kdjPeriod + 1
		hi, lo := bars[start].High, bars[start].Low
		for j := start + 1; j <= i; j++ {
			if bars[j].High > hi {
				hi = bars[j].High
			}
			if bars[j].Low < lo {
				lo = bars[j].Low
			}
		}
		close := bars[i].Close
		var rsv float64
		if hi > lo {
			rsv = (close - lo) / (hi - lo) * 100
		} else {
			rsv = 50
		}
		k = k*2/3 + rsv/3
		d = d*2/3 + k/3
		_ = d
	}
	return k, true
}

func fetchEastmoneyKline(ctx context.Context, code, start, end string) ([]klineBar, error) {
	q := url.Values{}
	q.Set("secid", secid(code))
	q.Set("fields1", "f1,f2,f3,f4,f5,f6")
	q.Set("fields2", "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61")
	q.Set("klt", "101")
	q.Set("fqt", "0")
	q.Set("beg", strings.ReplaceAll(start, "-", ""))
	q.Set("end", strings.ReplaceAll(end, "-", ""))
	q.Set("lmt", "1000000")
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://push2his.eastmoney.com/api/qt/stock/kline/get?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	req.Header.Set("Referer", "https://quote.eastmoney.com/")
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("K 线 HTTP %d", resp.StatusCode)
	}
	var payload struct {
		Data *struct {
			Klines []string `json:"klines"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, err
	}
	if payload.Data == nil {
		return nil, fmt.Errorf("K 线为空")
	}
	out := make([]klineBar, 0, len(payload.Data.Klines))
	for _, line := range payload.Data.Klines {
		parts := strings.Split(line, ",")
		if len(parts) < 6 {
			continue
		}
		day := strings.TrimSpace(parts[0])
		if len(day) != 10 {
			continue
		}
		open, err1 := strconv.ParseFloat(strings.TrimSpace(parts[1]), 64)
		close, err2 := strconv.ParseFloat(strings.TrimSpace(parts[2]), 64)
		high, err3 := strconv.ParseFloat(strings.TrimSpace(parts[3]), 64)
		low, err4 := strconv.ParseFloat(strings.TrimSpace(parts[4]), 64)
		if err1 != nil || err2 != nil || err3 != nil || err4 != nil {
			continue
		}
		out = append(out, klineBar{Date: day, Open: open, High: high, Low: low, Close: close})
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("K 线为空")
	}
	sortKlineBars(out)
	return out, nil
}

func barsForKDJ(ctx context.Context, code string) ([]klineBar, error) {
	if cached, ok := klineData.get(code); ok && len(cached) >= kdjPeriod {
		return cached, nil
	}
	bars, err := loadLocalKlineBars(code)
	if err != nil || len(bars) < kdjPeriod {
		end := time.Now().Format("2006-01-02")
		start := time.Now().AddDate(0, -6, 0).Format("2006-01-02")
		fetched, fetchErr := fetchEastmoneyKline(ctx, code, start, end)
		if fetchErr == nil && len(fetched) > 0 {
			bars = fetched
			err = nil
		} else if len(bars) == 0 {
			if fetchErr != nil {
				return nil, fetchErr
			}
			return nil, err
		}
	}
	klineData.set(code, bars)
	return bars, nil
}

func attachKDJK(ctx context.Context, quotes []quote) {
	today := time.Now().Format("2006-01-02")
	var wg sync.WaitGroup
	sem := make(chan struct{}, 4)
	for i := range quotes {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				return
			}
			bars, err := barsForKDJ(ctx, quotes[i].Code)
			if err != nil {
				return
			}
			bars = mergeTodayBar(bars, quotes[i].Price, today)
			k, ok := calcKDJK(bars)
			if !ok {
				return
			}
			quotes[i].KDJK = &k
		}(i)
	}
	wg.Wait()
}

func keepKDJK(prev, next []quote) {
	saved := map[string]float64{}
	for _, q := range prev {
		if q.KDJK != nil {
			saved[q.Code] = *q.KDJK
		}
	}
	for i := range next {
		if next[i].KDJK != nil {
			continue
		}
		v, ok := saved[next[i].Code]
		if !ok {
			continue
		}
		next[i].KDJK = &v
	}
}

func formatK(v *float64) string {
	if v == nil {
		return "K—"
	}
	r := math.Round(*v*10) / 10
	return fmt.Sprintf("K%.1f", r)
}

func formatPremiumK(premium, k *float64) string {
	return formatPctOrDash(premium) + " " + formatK(k)
}
