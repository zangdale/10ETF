package main

import "testing"

func TestMenuTitleColor(t *testing.T) {
	// 溢价放在涨跌幅前面，颜色只跟涨跌幅走。
	if got := probeMenuTitleColor(rowTitle(1, "中证红利", "-1.00% K55.0", "+0.83%")); got != 1 {
		t.Fatalf("涨幅颜色=%d，期望红色 1", got)
	}
	if got := probeMenuTitleColor(rowTitle(2, "巴西ETF", "+2.00% K40.0", "-1.64%")); got != -1 {
		t.Fatalf("跌幅颜色=%d，期望绿色 -1", got)
	}
	if got := probeMenuTitleColor(rowTitle(3, "国债ETF", "+1.00% K50.0", "0.00%")); got != 0 {
		t.Fatalf("平盘颜色=%d，期望原色 0", got)
	}
	if got := probeMenuTitleKColor(rowTitle(1, "中证红利", "+1.00% K15.0", "+0.83%")); got != 1 {
		t.Fatalf("K<20 颜色=%d，期望红色 1", got)
	}
	if got := probeMenuTitleKColor(rowTitle(2, "巴西ETF", "+2.00% K25.0", "-1.64%")); got != 0 {
		t.Fatalf("20<=K<=80 颜色=%d，期望原色 0", got)
	}
	if got := probeMenuTitleKColor(rowTitle(3, "国债ETF", "+1.00% K85.0", "0.00%")); got != -1 {
		t.Fatalf("K>80 颜色=%d，期望绿色 -1", got)
	}
}
