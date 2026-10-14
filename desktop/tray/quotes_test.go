package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFormatPct(t *testing.T) {
	cases := []struct {
		in   float64
		want string
	}{
		{0, "0.00%"},
		{0.004, "0.00%"},
		{-0.004, "0.00%"},
		{0.83, "+0.83%"},
		{-1.64, "-1.64%"},
		{0.005, "+0.01%"},
	}
	for _, c := range cases {
		if got := formatPct(c.in); got != c.want {
			t.Errorf("formatPct(%v)=%q, want %q", c.in, got, c.want)
		}
	}
}

func TestRowTitleUsesColorMark(t *testing.T) {
	got := rowTitle(1, "中证红利", "-1.00%", "+0.83%")
	if !strings.HasPrefix(got, rowMark) || rowMark != "\u200b" {
		t.Fatalf("title %q", got)
	}
	if !strings.Contains(got, "中证红利") || !strings.HasSuffix(got, "\t+0.83%") {
		t.Fatalf("title %q", got)
	}
	if !strings.Contains(got, "\t-1.00%\t") {
		t.Fatalf("premium column %q", got)
	}
	body, err := os.ReadFile("color_darwin.m")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(body, []byte(`@"\u200b"`)) {
		t.Fatal("color_darwin.m 必须识别 rowMark")
	}
}

func TestParseQuotesRanksByPct(t *testing.T) {
	etfs := []etf{
		{Code: "515180", Name: "中证红利"},
		{Code: "159307", Name: "100红利"},
		{Code: "511010", Name: "国债ETF"},
		{Code: "520870", Name: "巴西ETF"},
	}
	body := []byte(`{"rc":0,"data":{"diff":[
		{"f2":1.463,"f3":0.83,"f12":"515180"},
		{"f2":1.042,"f3":0.97,"f12":"159307"},
		{"f2":140.853,"f3":0,"f12":"511010"},
		{"f2":1.32,"f3":-1.64,"f12":"520870"}
	]}}`)
	got, err := parseQuotes(etfs, body)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"159307", "515180", "511010", "520870"}
	for i, code := range want {
		if got[i].Code != code {
			t.Fatalf("rank %d = %s, want %s", i+1, got[i].Code, code)
		}
	}
	if formatPct(*got[0].Pct) != "+0.97%" || formatPct(*got[2].Pct) != "0.00%" || formatPct(*got[3].Pct) != "-1.64%" {
		t.Fatalf("%s %s %s", formatPct(*got[0].Pct), formatPct(*got[2].Pct), formatPct(*got[3].Pct))
	}
}

func TestParseSina(t *testing.T) {
	etfs := []etf{
		{Code: "515180", Name: "中证红利"},
		{Code: "159307", Name: "100红利"},
	}
	body := []byte(`var hq_str_sh515180="name,1.453,1.451,1.465,1.469";
var hq_str_sz159307="name,1.032,1.032,1.041,1.044";`)
	got, err := parseSina(etfs, body)
	if err != nil {
		t.Fatal(err)
	}
	if got[0].Code != "515180" || formatPct(*got[0].Pct) != "+0.96%" {
		t.Fatalf("%s %s", got[0].Code, formatPct(*got[0].Pct))
	}
	if got[1].Code != "159307" || formatPct(*got[1].Pct) != "+0.87%" {
		t.Fatalf("%s %s", got[1].Code, formatPct(*got[1].Pct))
	}
}

func TestKeepPremiums(t *testing.T) {
	old, other := 7.5, -1.25
	prev := []quote{{Code: "513650", Name: "标普ETF", Premium: &old}, {Code: "520870", Name: "巴西ETF", Premium: &other}}
	next := []quote{{Code: "513650", Name: "标普ETF"}, {Code: "511010", Name: "国债ETF"}, {Code: "520870", Name: "巴西ETF"}}
	keepPremiums(prev, next)
	if next[0].Premium == nil || formatPct(*next[0].Premium) != "+7.50%" || formatPct(*next[2].Premium) != "-1.25%" {
		t.Fatal("missing premium should keep the previous value")
	}
	if next[1].Premium != nil {
		t.Fatal("code without history should stay empty")
	}
	fresh := 1.2
	newer := []quote{{Code: "513650", Name: "标普ETF", Premium: &fresh}}
	keepPremiums(prev, newer)
	if formatPct(*newer[0].Premium) != "+1.20%" {
		t.Fatal("a fresh premium should replace the previous one")
	}
}

func TestPremiumFromIOPV(t *testing.T) {
	price, iopv := 2.035, 1.893
	got, ok := premiumFromIOPV(&price, &iopv)
	if !ok || formatPct(got) != "+7.50%" {
		t.Fatalf("ok=%v pct=%s", ok, formatPct(got))
	}
	if _, ok := premiumFromIOPV(nil, &iopv); ok {
		t.Fatal("missing price should not produce a premium")
	}
}

func TestXueqiuURL(t *testing.T) {
	if xueqiuURL("515180") != "https://xueqiu.com/S/SH515180" || xueqiuURL("159307") != "https://xueqiu.com/S/SZ159307" {
		t.Fatalf("%s %s", xueqiuURL("515180"), xueqiuURL("159307"))
	}
}

func TestParseIndicesKeepsOrder(t *testing.T) {
	specs := marketIndices()
	if len(specs) != 14 {
		t.Fatalf("len=%d", len(specs))
	}
	wantSymbols := []string{
		"SH000001", "SZ399001", "SZ399006", "SH000688", "SH000016", "SH000300", "BJ899050",
		"HKHSI", "HKHSCEI", "HKHSTECH", ".DJI", ".IXIC", ".NDX", ".INX",
	}
	for i, symbol := range wantSymbols {
		if specs[i].Symbol != symbol {
			t.Fatalf("index %d = %s, want %s", i, specs[i].Symbol, symbol)
		}
	}
	body := `var hq_str_s_sh000001="n,0,0,0.07";
var hq_str_s_sz399001="n,0,0,-0.33";
var hq_str_gb_dji="n,0,-0.35";
var hq_str_gb_ixic="n,0,-0.15";
var hq_str_gb_ndx="n,0,-0.31";
var hq_str_gb_inx="n,0,-0.02";
var hq_str_rt_hkHSI="n,0,0,0,0,0,0,0,-0.040";
var hq_str_rt_hkHSCEI="n,0,0,0,0,0,0,0,-0.040";
var hq_str_rt_hkHSTECH="n,0,0,0,0,0,0,0,0.920";`
	got, err := parseIndices(specs, body)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != len(specs) || got[0].Code != "SH000001" || got[len(got)-1].Code != ".INX" {
		t.Fatalf("order %s ... %s", got[0].Code, got[len(got)-1].Code)
	}
	if formatPct(*got[0].Pct) != "+0.07%" || formatPct(*got[1].Pct) != "-0.33%" {
		t.Fatalf("cn %s %s", formatPct(*got[0].Pct), formatPct(*got[1].Pct))
	}
	if formatPct(*got[7].Pct) != "-0.04%" || formatPct(*got[9].Pct) != "+0.92%" {
		t.Fatalf("hk %s %s", formatPct(*got[7].Pct), formatPct(*got[9].Pct))
	}
	if formatPct(*got[10].Pct) != "-0.35%" || formatPct(*got[11].Pct) != "-0.15%" || formatPct(*got[12].Pct) != "-0.31%" {
		t.Fatalf("us %s %s %s", formatPct(*got[10].Pct), formatPct(*got[11].Pct), formatPct(*got[12].Pct))
	}
	if got[2].Pct != nil || got[6].Pct != nil {
		t.Fatal("missing lines should stay empty")
	}
	title := indexTitle(got[0].Name, formatPct(*got[0].Pct))
	if !strings.HasPrefix(title, rowMark) || !strings.HasSuffix(title, "\t+0.07%") {
		t.Fatalf("title %q", title)
	}
	if xueqiuSymbolURL(".DJI") != "https://xueqiu.com/S/.DJI" || xueqiuSymbolURL("HKHSI") != "https://xueqiu.com/S/HKHSI" {
		t.Fatalf("%s %s", xueqiuSymbolURL(".DJI"), xueqiuSymbolURL("HKHSI"))
	}
}

func TestSecid(t *testing.T) {
	if secid("159307") != "0.159307" || secid("515180") != "1.515180" {
		t.Fatalf("%s %s", secid("159307"), secid("515180"))
	}
}

func TestBundleInfoPath(t *testing.T) {
	got := filepath.Clean(bundleInfoPath("/tmp/10ETF.app/Contents/MacOS/10ETF"))
	want := "/tmp/10ETF.app/Contents/Resources/kline/info.json"
	if got != want {
		t.Fatalf("%s", got)
	}
}

func TestLoadETFs(t *testing.T) {
	etfs, err := loadETFs()
	if err != nil {
		t.Fatal(err)
	}
	if len(etfs) != 10 {
		t.Fatalf("len=%d", len(etfs))
	}
}
