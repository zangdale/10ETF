//go:build ignore

// 生成 10ETF.app 用的图标：go run appicon.go out.png
package main

import (
	"image"
	"image/color"
	"image/png"
	"os"
)

func main() {
	if len(os.Args) != 2 {
		os.Stderr.WriteString("usage: go run appicon.go out.png\n")
		os.Exit(2)
	}
	const n = 1024
	img := image.NewNRGBA(image.Rect(0, 0, n, n))
	bg := color.NRGBA{R: 14, G: 20, B: 32, A: 255}
	r := n * 22 / 100
	for y := 0; y < n; y++ {
		for x := 0; x < n; x++ {
			if inRound(x, y, n, r) {
				img.SetNRGBA(x, y, bg)
			}
		}
	}
	bars := []struct {
		h int
		c color.NRGBA
	}{
		{h: 280, c: color.NRGBA{R: 226, G: 75, B: 75, A: 255}},
		{h: 460, c: color.NRGBA{R: 201, G: 168, B: 76, A: 255}},
		{h: 620, c: color.NRGBA{R: 47, G: 158, B: 107, A: 255}},
		{h: 360, c: color.NRGBA{R: 232, G: 237, B: 245, A: 255}},
	}
	const barW, gap = 120, 48
	total := len(bars)*barW + (len(bars)-1)*gap
	x0 := (n - total) / 2
	bottom := n * 18 / 100
	for i, bar := range bars {
		x := x0 + i*(barW+gap)
		y0 := n - bottom - bar.h
		for y := y0; y < n-bottom; y++ {
			for dx := 0; dx < barW; dx++ {
				px, py := x+dx, y
				if inRound(px, py, n, r) {
					img.SetNRGBA(px, py, bar.c)
				}
			}
		}
	}
	f, err := os.Create(os.Args[1])
	if err != nil {
		os.Stderr.WriteString(err.Error() + "\n")
		os.Exit(1)
	}
	defer f.Close()
	if err := png.Encode(f, img); err != nil {
		os.Stderr.WriteString(err.Error() + "\n")
		os.Exit(1)
	}
}

func inRound(x, y, n, r int) bool {
	if x < 0 || y < 0 || x >= n || y >= n {
		return false
	}
	cx, cy := -1, -1
	switch {
	case x < r && y < r:
		cx, cy = r, r
	case x >= n-r && y < r:
		cx, cy = n-r-1, r
	case x < r && y >= n-r:
		cx, cy = r, n-r-1
	case x >= n-r && y >= n-r:
		cx, cy = n-r-1, n-r-1
	default:
		return true
	}
	dx, dy := x-cx, y-cy
	return dx*dx+dy*dy <= r*r
}
