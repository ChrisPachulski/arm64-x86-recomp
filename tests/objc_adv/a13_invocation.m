// NSInvocation built by guest code (guest and host targets, scalar/float/SEL/char*/struct/object args, retainArguments),
// performSelector: family (afterDelay on the run loop, onMainThread from a background thread, inBackground), and a guest
// NSProxy subclass forwarding to a host object and a guest object via forwardInvocation:.
#import <Foundation/Foundation.h>
static NSMutableArray* events;
@interface T : NSObject
- (NSString*)a:(int)i b:(double)d c:(SEL)s d:(const char*)p e:(NSRange)r f:(id)o g:(float)f h:(long long)ll;
- (void)tick:(id)o;
- (void)bg:(id)o;
@end
@implementation T
- (NSString*)a:(int)i b:(double)d c:(SEL)s d:(const char*)p e:(NSRange)r f:(id)o g:(float)f h:(long long)ll {
  return [NSString stringWithFormat:@"%d %g %s %s %lu/%lu %@ %g %lld", i, d, sel_getName(s), p, (unsigned long)r.location, (unsigned long)r.length, o, f, ll];
}
- (void)tick:(id)o { @synchronized(events) { [events addObject:[NSString stringWithFormat:@"tick %@ main=%d", o, (int)[NSThread isMainThread]]]; } }
- (void)bg:(id)o { [self performSelectorOnMainThread:@selector(tick:) withObject:[o stringByAppendingString:@"-from-bg"] waitUntilDone:YES]; }
@end
@interface Fwd : NSProxy { id _t; } + (id)to:(id)t; @end
@implementation Fwd
+ (id)to:(id)t { Fwd* f = [Fwd alloc]; f->_t = t; return f; }
- (NSMethodSignature*)methodSignatureForSelector:(SEL)s { return [_t methodSignatureForSelector:s]; }
- (void)forwardInvocation:(NSInvocation*)inv { @synchronized(events) { [events addObject:[@"fwd " stringByAppendingString:NSStringFromSelector(inv.selector)]]; } [inv invokeWithTarget:_t]; }
@end
int main(void) {
  events = [NSMutableArray array];
  @autoreleasepool {
    T* t = [T new];
    SEL sel = @selector(a:b:c:d:e:f:g:h:);
    NSInvocation* inv = [NSInvocation invocationWithMethodSignature:[t methodSignatureForSelector:sel]];
    inv.target = t; inv.selector = sel;
    int i = 7; double d = 2.5; SEL s = @selector(tick:); const char* p = "cstr"; NSRange r = NSMakeRange(3, 4); id o = @"obj"; float f = 0.75f; long long ll = -99;
    [inv setArgument:&i atIndex:2]; [inv setArgument:&d atIndex:3]; [inv setArgument:&s atIndex:4]; [inv setArgument:&p atIndex:5];
    [inv setArgument:&r atIndex:6]; [inv setArgument:&o atIndex:7]; [inv setArgument:&f atIndex:8]; [inv setArgument:&ll atIndex:9];
    [inv retainArguments];
    [inv invoke];
    __unsafe_unretained NSString* res; [inv getReturnValue:&res];
    printf("invocation guest: %s\n", res.UTF8String);
    NSString* host = @"hello world";
    NSInvocation* hi = [NSInvocation invocationWithMethodSignature:[host methodSignatureForSelector:@selector(substringWithRange:)]];
    hi.target = host; hi.selector = @selector(substringWithRange:);
    NSRange hr = NSMakeRange(6, 5); [hi setArgument:&hr atIndex:2]; [hi invoke];
    __unsafe_unretained NSString* hres; [hi getReturnValue:&hres];
    printf("invocation host: %s\n", hres.UTF8String);
    printf("performSelector: %s\n", [[t performSelector:@selector(description)] length] ? "desc" : "empty");
    printf("performSelector 2: %s\n", [[@"abc" performSelector:@selector(stringByAppendingString:) withObject:@"def"] UTF8String]);
    [t performSelector:@selector(tick:) withObject:@"delayed" afterDelay:0.01];
    [t performSelectorInBackground:@selector(bg:) withObject:@"x"];
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.5]];
    id pf = [Fwd to:@"proxied string"];
    printf("proxy host: %lu %s\n", (unsigned long)[pf length], [[pf uppercaseString] UTF8String]);
    id pg = [Fwd to:t];
    printf("proxy guest: %s\n", [[pg a:1 b:2 c:@selector(x) d:"p" e:NSMakeRange(0, 1) f:nil g:3 h:4] UTF8String]);
    printf("proxy isKind %d responds %d\n", (int)[pf isKindOfClass:[NSString class]], (int)[pg respondsToSelector:@selector(tick:)]);
  }
  NSArray* sorted = [events sortedArrayUsingSelector:@selector(compare:)];
  for (NSString* e in sorted) printf("%s\n", e.UTF8String);
  return 0;
}
