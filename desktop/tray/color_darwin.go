package main

/*
#cgo darwin CFLAGS: -x objective-c -fobjc-arc
#cgo darwin LDFLAGS: -framework Cocoa
#include <stdlib.h>
void installMenuTitleColor(void);
void hideDockIcon(void);
int probeMenuTitleColor(const char *utf8Title);
void setIndexMenuItemCount(int count);
void setIndexMenuItem(int index, const char *title, const char *url);
void popIndexMenu(void);
*/
import "C"
import "unsafe"

func installMenuTitleColor() { C.installMenuTitleColor() }

func hideDockIcon() { C.hideDockIcon() }

func probeMenuTitleColor(title string) int {
	cstr := C.CString(title)
	defer C.free(unsafe.Pointer(cstr))
	return int(C.probeMenuTitleColor(cstr))
}

func prepareIndexMenu(count int) {
	C.setIndexMenuItemCount(C.int(count))
}

func setIndexMenuItem(index int, title, url string) {
	ctitle := C.CString(title)
	curl := C.CString(url)
	defer C.free(unsafe.Pointer(ctitle))
	defer C.free(unsafe.Pointer(curl))
	C.setIndexMenuItem(C.int(index), ctitle, curl)
}

func popIndexMenu() { C.popIndexMenu() }
