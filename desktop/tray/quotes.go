package main

import (
	"context"
	"encoding/json"
	"errors"
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

// rowMark 是菜单行的零宽前缀。color_darwin.m 靠它给涨跌幅上色，界面上不显示。
const rowMark = "\u200b"

type etf struct {
	Code string
	Name string
}

type quote struct {
	Code    string
	Name    string
	Price   *float64
	Pct     *float64
	Premium *float64 // 溢价%：(现价 / IOPV - 1) * 100
}

func bundleInfoPath(exe string) string {
	return filepath.Join(filepath.Dir(exe), "..", "Resources", "kline", "info.json")
}

func findInfoJSON() (string, error) {
	var roots []string
	if exe, err := os.Executable(); err == nil {
		if resolved, err := filepath.EvalSymlinks(exe); err == nil {
			exe = resolved
		}
		if bundled := bundleInfoPath(exe); fileExists(bundled) {
			return bundled, nil
		}
		roots = append(roots, filepath.Dir(exe))
	}
	if wd, err := os.Getwd(); err == nil {
		roots = append(roots, wd)
	}
	seen := map[string]bool{}
	for _, root := range roots {
		dir := root
		for i := 0; i < 8; i++ {
			if seen[dir] {
				break
			}
			seen[dir] = true
			cand := filepath.Join(dir, "kline", "info.json")
			if fi, err := os.Stat(cand); err == nil && !fi.IsDir() {
				return cand, nil
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	return "", errors.New("找不到 kline/info.json")
}

func fileExists(path string) bool {
	fi, err := os.Stat(path)
	return err == nil && !fi.IsDir()
}

func loadETFs() ([]etf, error) {
	path, err := findInfoJSON()
	if err != nil {
		return nil, err
	}
	body, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var data struct {
		Items []struct {
			Code string `json:"code"`
			Name string `json:"name"`
		} `json:"items"`
	}
	if err := json.Unmarshal(body, &data); err != nil {
		return nil, err
	}
	out := make([]etf, 0, len(data.Items))
	seen := map[string]bool{}
	for _, it := range data.Items {
		code := strings.TrimSpace(it.Code)
		if code == "" || seen[code] {
			continue
		}
		seen[code] = true
		name := strings.TrimSpace(it.Name)
		if name == "" {
			name = code
		}
		out = append(out, etf{Code: code, Name: name})
	}
	if len(out) == 0 {
		return nil, errors.New("kline/info.json 里没有 ETF")
	}
	return out, nil
}

// secid 与 desktop/server.py 的交易所规则一致：1 开头为深市，其余为沪市。
func secid(code string) string {
	market := "1"
	if strings.HasPrefix(code, "1") {
		market = "0"
	}
	return market + "." + code
}

var quoteHosts = []string{
	"https://push2.eastmoney.com/api/qt/ulist.np/get",
	"https://push2delay.eastmoney.com/api/qt/ulist.np/get",
}

var httpClient = &http.Client{Timeout: 8 * time.Second}

func fetchQuotes(ctx context.Context, etfs []etf) ([]quote, error) {
	var last error
	for _, host := range quoteHosts {
		quotes, err := fetchQuotesFrom(ctx, host, etfs)
		if err == nil {
			attachPremiums(quotes)
			return quotes, nil
		}
		last = err
	}
	quotes, err := fetchSina(ctx, etfs)
	if err != nil {
		if last != nil {
			return nil, last
		}
		return nil, err
	}
	attachPremiums(quotes)
	return quotes, nil
}

func fetchQuotesFrom(ctx context.Context, host string, etfs []etf) ([]quote, error) {
	ids := make([]string, len(etfs))
	for i, e := range etfs {
		ids[i] = secid(e.Code)
	}
	q := url.Values{}
	q.Set("fltt", "2")
	q.Set("fields", "f2,f3,f12,f14")
	q.Set("secids", strings.Join(ids, ","))
	q.Set("ut", "fa5fd1943c7b386f172d6893dbfba10b")
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, host+"?"+q.Encode(), nil)
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
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("行情接口 HTTP %d", resp.StatusCode)
	}
	return parseQuotes(etfs, body)
}

// 溢价率 = 现价 / IOPV - 1。IOPV 取东方财富 f131，与现价 f43 同一次返回。
// 单独计时，避免行情请求占满上层超时后把溢价全部清空。
func attachPremiums(quotes []quote) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
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
			price, iopv, err := fetchIOPV(ctx, quotes[i].Code)
			if err != nil {
				return
			}
			if price == nil || *price <= 0 {
				price = quotes[i].Price
			}
			v, ok := premiumFromIOPV(price, iopv)
			if !ok {
				return
			}
			quotes[i].Premium = &v
		}(i)
	}
	wg.Wait()
}

func fetchIOPV(ctx context.Context, code string) (price, iopv *float64, err error) {
	hosts := []string{
		"https://push2.eastmoney.com/api/qt/stock/get",
		"https://82.push2.eastmoney.com/api/qt/stock/get",
		"https://push2delay.eastmoney.com/api/qt/stock/get",
	}
	var last error
	for _, host := range hosts {
		reqCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
		price, iopv, err = fetchIOPVFrom(reqCtx, host, code)
		cancel()
		if err == nil {
			return price, iopv, nil
		}
		last = err
		if ctx.Err() != nil {
			break
		}
	}
	return nil, nil, last
}

// keepPremiums 在本轮没拿到 IOPV 时沿用上一轮溢价，避免刷新后显示成「—」。
func keepPremiums(prev, next []quote) {
	saved := map[string]float64{}
	for _, q := range prev {
		if q.Premium != nil {
			saved[q.Code] = *q.Premium
		}
	}
	for i := range next {
		if next[i].Premium != nil {
			continue
		}
		v, ok := saved[next[i].Code]
		if !ok {
			continue
		}
		next[i].Premium = &v
	}
}

func fetchIOPVFrom(ctx context.Context, host, code string) (price, iopv *float64, err error) {
	q := url.Values{}
	q.Set("invt", "2")
	q.Set("fltt", "2")
	q.Set("secid", secid(code))
	q.Set("fields", "f43,f131")
	q.Set("ut", "fa5fd1943c7b386f172d6893dbfba10b")
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, host+"?"+q.Encode(), nil)
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	req.Header.Set("Referer", "https://quote.eastmoney.com/")
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, nil, fmt.Errorf("净值接口 HTTP %d", resp.StatusCode)
	}
	var payload struct {
		Rc   int `json:"rc"`
		Data *struct {
			Price flexFloat `json:"f43"`
			IOPV  flexFloat `json:"f131"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, nil, err
	}
	if payload.Rc != 0 || payload.Data == nil {
		return nil, nil, fmt.Errorf("净值接口 rc=%d", payload.Rc)
	}
	return payload.Data.Price.ptr(), payload.Data.IOPV.ptr(), nil
}

func premiumFromIOPV(price, iopv *float64) (float64, bool) {
	if price == nil || iopv == nil || *price <= 0 || *iopv <= 0 {
		return 0, false
	}
	return (*price / *iopv - 1) * 100, true
}

func xueqiuURL(code string) string {
	exch := "SH"
	if strings.HasPrefix(code, "1") {
		exch = "SZ"
	}
	return "https://xueqiu.com/S/" + exch + code
}

func xueqiuSymbolURL(symbol string) string {
	return "https://xueqiu.com/S/" + symbol
}

// indexSpec 是大盘子菜单的固定顺序。PctAt 是新浪返回里涨跌幅所在的字段下标。
type indexSpec struct {
	Symbol string
	Name   string
	Sina   string
	PctAt  int
}

func marketIndices() []indexSpec {
	return []indexSpec{
		{"SH000001", "上证指数", "s_sh000001", 3},
		{"SZ399001", "深证成指", "s_sz399001", 3},
		{"SZ399006", "创业板指", "s_sz399006", 3},
		{"SH000688", "科创50", "s_sh000688", 3},
		{"SH000016", "上证50", "s_sh000016", 3},
		{"SH000300", "沪深300", "s_sh000300", 3},
		{"BJ899050", "北证50", "s_bj899050", 3},
		{"HKHSI", "恒生指数", "rt_hkHSI", 8},
		{"HKHSCEI", "国企指数", "rt_hkHSCEI", 8},
		{"HKHSTECH", "恒生科技", "rt_hkHSTECH", 8},
		{".DJI", "道琼斯", "gb_dji", 2},
		{".IXIC", "纳斯达克", "gb_ixic", 2},
		{".NDX", "纳指100", "gb_ndx", 2},
		{".INX", "标普500", "gb_inx", 2},
	}
}

func fetchIndices(ctx context.Context) ([]quote, error) {
	specs := marketIndices()
	syms := make([]string, len(specs))
	for i, spec := range specs {
		syms[i] = spec.Sina
	}
	text, err := fetchSinaText(ctx, syms)
	if err != nil {
		return nil, err
	}
	return parseIndices(specs, text)
}

func parseIndices(specs []indexSpec, text string) ([]quote, error) {
	out := make([]quote, 0, len(specs))
	found := 0
	for _, spec := range specs {
		q := quote{Code: spec.Symbol, Name: spec.Name}
		if pct, ok := sinaPct(text, spec.Sina, spec.PctAt); ok {
			q.Pct = &pct
			found++
		}
		out = append(out, q)
	}
	if found == 0 {
		return nil, errors.New("指数行情为空")
	}
	return out, nil
}

func sinaPct(text, symbol string, at int) (float64, bool) {
	key := "hq_str_" + symbol + "=\""
	i := strings.Index(text, key)
	if i < 0 {
		return 0, false
	}
	rest := text[i+len(key):]
	end := strings.Index(rest, "\"")
	if end <= 0 {
		return 0, false
	}
	fields := strings.Split(rest[:end], ",")
	if at < 0 || at >= len(fields) {
		return 0, false
	}
	pct, err := strconv.ParseFloat(strings.TrimSpace(fields[at]), 64)
	if err != nil {
		return 0, false
	}
	return pct, true
}

func sinaSymbol(code string) string {
	if strings.HasPrefix(code, "1") {
		return "sz" + code
	}
	return "sh" + code
}

func fetchSina(ctx context.Context, etfs []etf) ([]quote, error) {
	syms := make([]string, len(etfs))
	for i, e := range etfs {
		syms[i] = sinaSymbol(e.Code)
	}
	text, err := fetchSinaText(ctx, syms)
	if err != nil {
		return nil, err
	}
	return parseSina(etfs, []byte(text))
}

func fetchSinaText(ctx context.Context, symbols []string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://hq.sinajs.cn/list="+strings.Join(symbols, ","), nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "Mozilla/5.0")
	req.Header.Set("Referer", "https://finance.sina.com.cn")
	resp, err := httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return "", err
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("新浪行情 HTTP %d", resp.StatusCode)
	}
	return string(body), nil
}

func parseSina(etfs []etf, body []byte) ([]quote, error) {
	text := string(body)
	out := make([]quote, 0, len(etfs))
	found := 0
	for _, e := range etfs {
		q := quote{Code: e.Code, Name: e.Name}
		key := "hq_str_" + sinaSymbol(e.Code) + "=\""
		if i := strings.Index(text, key); i >= 0 {
			rest := text[i+len(key):]
			if end := strings.Index(rest, "\""); end > 0 {
				fields := strings.Split(rest[:end], ",")
				if len(fields) >= 4 {
					prev, err1 := strconv.ParseFloat(fields[2], 64)
					price, err2 := strconv.ParseFloat(fields[3], 64)
					if err1 == nil && err2 == nil && prev > 0 && price > 0 {
						q.Price = &price
						pct := (price - prev) / prev * 100
						q.Pct = &pct
						found++
					}
				}
			}
		}
		out = append(out, q)
	}
	if found == 0 {
		return nil, errors.New("新浪行情为空")
	}
	sortQuotes(out)
	return out, nil
}

type flexFloat struct {
	set bool
	v   float64
}

func (n *flexFloat) UnmarshalJSON(b []byte) error {
	if string(b) == "null" || string(b) == `""` || string(b) == `"-"` {
		return nil
	}
	var f float64
	if err := json.Unmarshal(b, &f); err == nil {
		n.set = true
		n.v = f
		return nil
	}
	var s string
	if err := json.Unmarshal(b, &s); err != nil {
		return nil
	}
	s = strings.TrimSpace(strings.TrimSuffix(s, "%"))
	if s == "" || s == "-" {
		return nil
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return nil
	}
	n.set = true
	n.v = f
	return nil
}

func (n flexFloat) ptr() *float64 {
	if !n.set {
		return nil
	}
	v := n.v
	return &v
}

func parseQuotes(etfs []etf, body []byte) ([]quote, error) {
	var payload struct {
		Rc   int `json:"rc"`
		Data *struct {
			Diff []struct {
				Price flexFloat `json:"f2"`
				Pct   flexFloat `json:"f3"`
				Code  string    `json:"f12"`
			} `json:"diff"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, err
	}
	if payload.Rc != 0 || payload.Data == nil {
		return nil, fmt.Errorf("行情接口 rc=%d", payload.Rc)
	}
	byCode := map[string]struct {
		price *float64
		pct   *float64
	}{}
	for _, row := range payload.Data.Diff {
		code := strings.TrimSpace(row.Code)
		if code == "" {
			continue
		}
		byCode[code] = struct {
			price *float64
			pct   *float64
		}{price: row.Price.ptr(), pct: row.Pct.ptr()}
	}
	out := make([]quote, 0, len(etfs))
	for _, e := range etfs {
		q := quote{Code: e.Code, Name: e.Name}
		if row, ok := byCode[e.Code]; ok {
			q.Price = row.price
			q.Pct = row.pct
		}
		out = append(out, q)
	}
	sortQuotes(out)
	return out, nil
}

func sortQuotes(quotes []quote) {
	sort.SliceStable(quotes, func(i, j int) bool {
		a, b := quotes[i], quotes[j]
		switch {
		case a.Pct == nil && b.Pct == nil:
			return a.Code < b.Code
		case a.Pct == nil:
			return false
		case b.Pct == nil:
			return true
		case *a.Pct != *b.Pct:
			return *a.Pct > *b.Pct
		default:
			return a.Code < b.Code
		}
	})
}

func formatPct(v float64) string {
	r := math.Round(v*100) / 100
	if r == 0 {
		return "0.00%"
	}
	return fmt.Sprintf("%+.2f%%", r)
}

func formatPrice(v *float64) string {
	if v == nil || *v <= 0 {
		return "—"
	}
	return fmt.Sprintf("%.3f", *v)
}

func formatPctOrDash(v *float64) string {
	if v == nil {
		return "—"
	}
	return formatPct(*v)
}

func rowTitle(rank int, name, premium, pct string) string {
	// 名称靠左，溢价居中，涨跌幅靠右。两处制表位由 color_darwin.m 定位。
	return fmt.Sprintf("%s%2d  %s\t%s\t%s", rowMark, rank, name, premium, pct)
}

func indexTitle(name, pct string) string {
	return fmt.Sprintf("%s%s\t%s", rowMark, name, pct)
}

func (q quote) tip() string {
	return fmt.Sprintf("%s  当前 %s  溢价 %s  点击打开详情", q.Code, formatPrice(q.Price), formatPctOrDash(q.Premium))
}

func summaryLine(quotes []quote) string {
	parts := make([]string, 0, len(quotes))
	for _, q := range quotes {
		parts = append(parts, fmt.Sprintf("%s %s %s 溢价 %s", q.Name, formatPrice(q.Price), formatPctOrDash(q.Pct), formatPctOrDash(q.Premium)))
	}
	return strings.Join(parts, "  ")
}
