package main

import "testing"

func TestCalcKDJK(t *testing.T) {
	bars := make([]klineBar, 12)
	for i := range bars {
		bars[i] = klineBar{
			Date:  "2026-01-01",
			Open:  10,
			High:  10 + float64(i%3),
			Low:   9,
			Close: 9.5 + float64(i)*0.1,
		}
		bars[i].Date = bars[i].Date[:8] + string(rune('0'+i%10))
	}
	k, ok := calcKDJK(bars)
	if !ok || k <= 0 || k > 100 {
		t.Fatalf("k=%v ok=%v", k, ok)
	}
	if _, ok := calcKDJK(bars[:kdjPeriod-1]); ok {
		t.Fatal("too few bars should not produce K")
	}
}

func TestMergeTodayBar(t *testing.T) {
	bars := []klineBar{{Date: "2026-11-02", Open: 1, High: 1.1, Low: 0.9, Close: 1.05}}
	price := 1.08
	got := mergeTodayBar(bars, &price, "2026-11-03")
	if len(got) != 2 || got[1].Close != 1.08 || got[1].High != 1.08 {
		t.Fatalf("%+v", got)
	}
	got = mergeTodayBar(got, &price, "2026-11-03")
	if len(got) != 2 || got[1].Close != 1.08 {
		t.Fatalf("update today %+v", got)
	}
}

func TestFormatPremiumK(t *testing.T) {
	prem, k := 1.23, 66.66
	got := formatPremiumK(&prem, &k)
	if got != "+1.23% K66.7" {
		t.Fatalf("%q", got)
	}
	if formatPremiumK(nil, nil) != "— K—" {
		t.Fatal(formatPremiumK(nil, nil))
	}
}

func TestLoadLocalKlineBars(t *testing.T) {
	bars, err := loadLocalKlineBars("515180")
	if err != nil {
		t.Skip(err)
	}
	if len(bars) < kdjPeriod {
		t.Fatalf("len=%d", len(bars))
	}
	k, ok := calcKDJK(bars)
	if !ok {
		t.Fatal("calc failed")
	}
	t.Logf("515180 K=%.1f bars=%d", k, len(bars))
}
