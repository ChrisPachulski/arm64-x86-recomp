// ARC runtime entry points: weak references zeroed at dealloc (objc_initWeak / loadWeakRetained / storeWeak / destroyWeak),
// nested autorelease pools, @synchronized, fast enumeration, CF bridging transfers, copy semantics of blocks capturing
// strong and weak references.
#import <Foundation/Foundation.h>

@interface Node : NSObject
@property (nonatomic, copy) NSString* tag;
@property (nonatomic, weak) Node* peer;
@property (nonatomic, strong) Node* next;
@end
@implementation Node
- (void)dealloc { printf("dealloc %s\n", _tag.UTF8String); }
@end

int main(void) {
  Node* keep;
  @autoreleasepool {
    __weak Node* w;
    @autoreleasepool {
      Node* a = [Node new]; a.tag = @"a";
      Node* b = [Node new]; b.tag = @"b";
      a.peer = b; b.peer = a; a.next = b;
      w = a;
      printf("weak before: %s peer %s\n", w.tag.UTF8String, b.peer.tag.UTF8String);
      keep = b;
      a = nil;
      printf("a released, weak now %s, b.peer %s\n", w ? "set" : "nil", b.peer ? "set" : "nil");
    }
    printf("inner pool drained, weak %s\n", w ? "set" : "nil");
    @synchronized (keep) { printf("synchronized on %s\n", keep.tag.UTF8String); }
    NSMutableArray* list = [NSMutableArray array];
    for (int i = 0; i < 4; i++) { Node* n = [Node new]; n.tag = [NSString stringWithFormat:@"n%d", i]; [list addObject:n]; }
    NSMutableString* tags = [NSMutableString string];
    for (Node* n in list) [tags appendString:n.tag];
    printf("fast enumeration: %s\n", tags.UTF8String);
    CFStringRef cf = (__bridge_retained CFStringRef)[NSString stringWithFormat:@"bridged %d", 1];
    printf("CF retain count >= 1: %d, %s\n", CFGetRetainCount(cf) >= 1, [(__bridge NSString*)cf UTF8String]);
    NSString* back = CFBridgingRelease(cf);
    printf("bridged back: %s\n", back.UTF8String);
    __weak Node* wk = keep;
    void (^blk)(void) = ^{ printf("block sees strong %s weak %s\n", keep.tag.UTF8String, wk.tag.UTF8String); };
    blk();
    [list removeAllObjects];
    printf("list cleared\n");
  }
  printf("outer pool drained\n");
  keep = nil;
  printf("done\n");
  return 0;
}
