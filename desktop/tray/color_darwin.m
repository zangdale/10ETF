#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#include <stdio.h>

// rowMark（U+200B）开头的菜单标题，涨跌幅按 A 股习惯着色：涨红、跌绿、0 保持系统原色。

static IMP etfOriginalSetTitle = NULL;
static int etfApplyingColor = 0;

static NSAttributedString *etfColoredTitle(NSString *shown) {
	NSMutableAttributedString *attr = [[NSMutableAttributedString alloc] initWithString:shown];
	NSUInteger len = shown.length;
	if (len == 0) {
		return attr;
	}
	NSFont *font = [NSFont menuFontOfSize:0];
	if (font == nil) {
		font = [NSFont systemFontOfSize:[NSFont systemFontSize]];
	}
	[attr addAttribute:NSFontAttributeName value:font range:NSMakeRange(0, len)];
	[attr addAttribute:NSForegroundColorAttributeName value:[NSColor labelColor] range:NSMakeRange(0, len)];

	NSRange tab = [shown rangeOfString:@"\t" options:NSBackwardsSearch];
	if (tab.location == NSNotFound) {
		return attr;
	}
	if (tab.location + 1 >= len) {
		return attr;
	}
	NSRange firstTab = [shown rangeOfString:@"\t"];
	NSRange pctRange = NSMakeRange(tab.location + 1, len - (tab.location + 1));
	NSString *pct = [shown substringWithRange:pctRange];
	NSFont *digits = [NSFont monospacedDigitSystemFontOfSize:font.pointSize weight:NSFontWeightRegular];
	if (digits == nil) {
		digits = font;
	}
	NSDictionary *textAttrs = @{NSFontAttributeName: font};
	NSDictionary *pctAttrs = @{NSFontAttributeName: digits};
	BOOL quoteRow = firstTab.location != tab.location;
	NSMutableParagraphStyle *style = [[NSMutableParagraphStyle alloc] init];
	[style setAlignment:NSTextAlignmentLeft];
	[style setLineBreakMode:NSLineBreakByClipping];
	if (quoteRow) {
		// 名称左对齐，溢价在名称和涨跌幅之间居中，涨跌幅靠右并贴近菜单右缘。
		NSString *sampleName = @"10  中证红利";
		NSString *samplePrem = @"+100.00%";
		NSString *samplePct = @"+12.34%";
		CGFloat nameWidth = ceil([sampleName sizeWithAttributes:textAttrs].width);
		NSString *left = [shown substringToIndex:firstTab.location];
		CGFloat actualName = ceil([left sizeWithAttributes:textAttrs].width);
		if (actualName > nameWidth) {
			nameWidth = actualName;
		}
		CGFloat premWidth = ceil([samplePrem sizeWithAttributes:pctAttrs].width);
		NSString *premium = [shown substringWithRange:NSMakeRange(firstTab.location + 1, tab.location - firstTab.location - 1)];
		CGFloat actualPrem = ceil([premium sizeWithAttributes:pctAttrs].width);
		if (actualPrem > premWidth) {
			premWidth = actualPrem;
		}
		CGFloat pctWidth = ceil([samplePct sizeWithAttributes:pctAttrs].width);
		CGFloat actualPct = ceil([pct sizeWithAttributes:pctAttrs].width);
		if (actualPct > pctWidth) {
			pctWidth = actualPct;
		}
		CGFloat gap = 12;
		CGFloat right = nameWidth + gap + premWidth + gap + pctWidth;
		CGFloat center = (nameWidth + (right - pctWidth)) / 2.0;
		NSTextTab *mid = [[NSTextTab alloc] initWithTextAlignment:NSTextAlignmentCenter location:center options:@{}];
		NSTextTab *end = [[NSTextTab alloc] initWithTextAlignment:NSTextAlignmentRight location:right options:@{}];
		[style setTabStops:@[mid, end]];
		if (premium.length > 0) {
			[attr addAttribute:NSFontAttributeName value:digits range:NSMakeRange(firstTab.location + 1, premium.length)];
		}
	} else {
		NSString *samplePrefix = @"恒生科技";
		NSString *samplePct = @"+100.00%";
		CGFloat prefixWidth = ceil([samplePrefix sizeWithAttributes:textAttrs].width);
		CGFloat pctWidth = ceil([samplePct sizeWithAttributes:pctAttrs].width);
		NSString *prefix = [shown substringToIndex:tab.location];
		CGFloat actualPrefix = ceil([prefix sizeWithAttributes:textAttrs].width);
		CGFloat actualPct = ceil([pct sizeWithAttributes:pctAttrs].width);
		if (actualPrefix > prefixWidth) {
			prefixWidth = actualPrefix;
		}
		if (actualPct > pctWidth) {
			pctWidth = actualPct;
		}
		CGFloat location = prefixWidth + 16 + pctWidth;
		NSTextTab *stop = [[NSTextTab alloc] initWithTextAlignment:NSTextAlignmentRight location:location options:@{}];
		[style setTabStops:[NSArray arrayWithObject:stop]];
	}
	[attr addAttribute:NSParagraphStyleAttributeName value:style range:NSMakeRange(0, len)];
	if ([pct containsString:@"%"]) {
		double value = 0;
		const char *utf8 = pct.UTF8String;
		if (utf8 != NULL) {
			sscanf(utf8, "%lf", &value);
		}
		NSColor *color = nil;
		if (value > 0) {
			color = [NSColor systemRedColor];
		} else if (value < 0) {
			color = [NSColor systemGreenColor];
		}
		if (color != nil) {
			[attr addAttribute:NSForegroundColorAttributeName value:color range:pctRange];
		}
		[attr addAttribute:NSFontAttributeName value:digits range:pctRange];
	}
	return attr;
}

static void etfColoredSetTitle(id self, SEL _cmd, NSString *title) {
	if (etfApplyingColor) {
		return;
	}
	if (etfOriginalSetTitle == NULL) {
		return;
	}
	if (title == nil || ![title hasPrefix:@"\u200b"]) {
		((void (*)(id, SEL, NSString *))etfOriginalSetTitle)(self, _cmd, title);
		return;
	}
	NSString *shown = [title substringFromIndex:1];
	((void (*)(id, SEL, NSString *))etfOriginalSetTitle)(self, _cmd, shown);
	etfApplyingColor = 1;
	[(NSMenuItem *)self setAttributedTitle:etfColoredTitle(shown)];
	etfApplyingColor = 0;
}

static void etfInstallColor(void) {
	if (etfOriginalSetTitle != NULL) {
		return;
	}
	Class cls = [NSMenuItem class];
	SEL sel = @selector(setTitle:);
	Method method = class_getInstanceMethod(cls, sel);
	if (method == NULL) {
		return;
	}
	IMP replacement = (IMP)etfColoredSetTitle;
	if (class_addMethod(cls, sel, replacement, method_getTypeEncoding(method))) {
		etfOriginalSetTitle = method_getImplementation(method);
		return;
	}
	etfOriginalSetTitle = method_setImplementation(method, replacement);
}

void installMenuTitleColor(void) {
	etfInstallColor();
}

int probeMenuTitleColor(const char *utf8Title) {
	@autoreleasepool {
		installMenuTitleColor();
		if (utf8Title == NULL) {
			return -2;
		}
		NSString *title = [NSString stringWithUTF8String:utf8Title];
		NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:@"placeholder" action:NULL keyEquivalent:@""];
		[item setTitle:title];
		NSAttributedString *attr = item.attributedTitle;
		if (attr == nil || attr.length == 0) {
			return -2;
		}
		NSRange tab = [attr.string rangeOfString:@"\t" options:NSBackwardsSearch];
		if (tab.location == NSNotFound || tab.location + 1 >= attr.length) {
			return -3;
		}
		NSColor *color = [attr attribute:NSForegroundColorAttributeName atIndex:tab.location + 1 effectiveRange:NULL];
		NSColor *rgb = [color colorUsingColorSpace:[NSColorSpace sRGBColorSpace]];
		if (rgb == nil) {
			return 0;
		}
		CGFloat r = 0, g = 0, b = 0, a = 0;
		[rgb getRed:&r green:&g blue:&b alpha:&a];
		if (r > 0.55 && r > g + 0.2 && r > b + 0.2) {
			return 1;
		}
		if (g > 0.35 && g > r + 0.15 && g > b) {
			return -1;
		}
		return 0;
	}
}

// 大盘单独弹出，主菜单不再为子菜单箭头留出右侧空白。
static NSMenu *etfIndexMenu = nil;

@interface ETFIndexTarget : NSObject
@property(copy) NSString *url;
- (void)open:(id)sender;
@end

@implementation ETFIndexTarget
- (void)open:(id)sender {
	if (self.url.length == 0) {
		return;
	}
	[[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:self.url]];
}
@end

static void etfOnMain(void (^block)(void)) {
	if ([NSThread isMainThread]) {
		block();
	} else {
		dispatch_sync(dispatch_get_main_queue(), block);
	}
}

void setIndexMenuItemCount(int count) {
	if (count < 0) {
		count = 0;
	}
	etfOnMain(^{
		if (etfIndexMenu == nil) {
			etfIndexMenu = [[NSMenu alloc] initWithTitle:@"大盘"];
			etfIndexMenu.autoenablesItems = NO;
		}
		while ((int)etfIndexMenu.numberOfItems < count) {
			ETFIndexTarget *target = [ETFIndexTarget new];
			NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:@"" action:@selector(open:) keyEquivalent:@""];
			item.target = target;
			item.representedObject = target;
			[etfIndexMenu addItem:item];
		}
		while ((int)etfIndexMenu.numberOfItems > count) {
			[etfIndexMenu removeItemAtIndex:etfIndexMenu.numberOfItems - 1];
		}
	});
}

void setIndexMenuItem(int index, const char *title, const char *url) {
	etfOnMain(^{
		if (etfIndexMenu == nil || index < 0 || index >= (int)etfIndexMenu.numberOfItems) {
			return;
		}
		NSMenuItem *item = [etfIndexMenu itemAtIndex:index];
		NSString *shown = title == NULL ? @"" : [NSString stringWithUTF8String:title];
		NSString *link = url == NULL ? @"" : [NSString stringWithUTF8String:url];
		[item setTitle:shown];
		ETFIndexTarget *target = item.representedObject;
		target.url = link;
	});
}

void popIndexMenu(void) {
	dispatch_async(dispatch_get_main_queue(), ^{
		if (etfIndexMenu == nil || etfIndexMenu.numberOfItems == 0) {
			return;
		}
		[etfIndexMenu popUpMenuPositioningItem:nil atLocation:[NSEvent mouseLocation] inView:nil];
	});
}

void hideDockIcon(void) {
	if (NSApp == nil) {
		return;
	}
	[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
}
