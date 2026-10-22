// Guest blocks reaching native code as plain objects: a global and a capturing block returned as `id` by guest methods
// that the host calls (KVC "make.invoke": the host invokes them), and a block stored through objc_setAssociatedObject
// (a C import taking id) with the copy policy, then invoked by the host through KVC.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
static char key;
@interface M : NSObject @property (nonatomic, copy) NSString* tag; - (id)make; - (id)capture; - (id)stored; @end
@implementation M
- (id)make { return ^{ printf("global block invoked by host\n"); }; }
- (id)capture { NSString* t = self.tag; return ^{ printf("capturing block invoked by host: %s\n", t.UTF8String); }; }
- (id)stored { return objc_getAssociatedObject(self, &key); }
@end
int main(void) {
  @autoreleasepool {
    M* m = [M new];
    m.tag = [NSString stringWithFormat:@"tag-%d", 7];
    id r = [m valueForKeyPath:@"make.invoke"];
    printf("kvc result %s\n", r ? "obj" : "nil");
    [m valueForKeyPath:@"capture.invoke"];
    NSString* local = [NSString stringWithFormat:@"assoc-%d", 9];
    objc_setAssociatedObject(m, &key, ^{ printf("associated block: %s\n", local.UTF8String); }, OBJC_ASSOCIATION_COPY);
    [m valueForKeyPath:@"stored.invoke"];
  }
  return 0;
}
