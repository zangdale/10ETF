package main

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
)

func trayIcon() []byte {
	const n = 32
	img := image.NewNRGBA(image.Rect(0, 0, n, n))
	heights := []int{12, 18, 26, 16}
	const barW, gap, bottom = 5, 3, 4
	total := len(heights)*barW + (len(heights)-1)*gap
	x0 := (n - total) / 2
	ink := color.NRGBA{A: 255}
	for i, h := range heights {
		x := x0 + i*(barW+gap)
		y0 := n - bottom - h
		for y := y0; y < n-bottom; y++ {
			for dx := 0; dx < barW; dx++ {
				img.SetNRGBA(x+dx, y, ink)
			}
		}
	}
	var buf bytes.Buffer
	_ = png.Encode(&buf, img)
	return buf.Bytes()
}
