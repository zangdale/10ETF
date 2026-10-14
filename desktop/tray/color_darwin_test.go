package main

import "testing"

func TestMenuTitleColor(t *testing.T) {
	// 溢价放在涨跌幅前面，颜色只跟涨跌幅走。
	if got := probeMenuTitleColor(rowTitle(1, "中证红利", "-1.00%", "+0.83%")); got != 1 {
		t.Fatalf("涨幅颜色=%d，期望红色 1", got)
	}
	if got := probeMenuTitleColor(rowTitle(2, "巴西ETF", "+2.00%", "-1.64%")); got != -1 {
		t.Fatalf("跌幅颜色=%d，期望绿色 -1", got)
	}
	if got := probeMenuTitleColor(rowTitle(3, "国债ETF", "+1.00%", "0.00%")); got != 0 {
		t.Fatalf("平盘颜色=%d，期望原色 0", got)
	}
}
