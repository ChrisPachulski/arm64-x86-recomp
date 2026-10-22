// flags: -fno-objc-arc
// MRC: a capturing STACK block (copy helper and dispose helper are guest code) handed to objc_setAssociatedObject with the
// copy policy: the host's _Block_copy runs the helpers; the host then invokes the copy through KVC, and the association's
// release runs the dispose helper (the captured object's dealloc is counted).
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
static char key;
static int deallocs;
@interface Cap : NSObject @end
@implementation Cap - (void)dealloc { deallocs++; [super dealloc]; } - (NSString*)description { return @"captured"; } @end
@interface H : NSObject - (id)stored; @end
@implementation H - (id)stored { return objc_getAssociatedObject(self, &key); } @end
int main(void) {
  NSAutoreleasePool* pool = [NSAutoreleasePool new];
  H* h = [H new];
  Cap* c = [Cap new];
  void (^blk)(void) = ^{ printf("stack block copy invoked by host: %s\n", [[c description] UTF8String]); };
  objc_setAssociatedObject(h, &key, (id)blk, OBJC_ASSOCIATION_COPY);
  [c release];
  printf("after release, deallocs %d\n", deallocs);
  [h valueForKeyPath:@"stored.invoke"];
  objc_setAssociatedObject(h, &key, nil, OBJC_ASSOCIATION_COPY);
  printf("after clearing, deallocs %d\n", deallocs);
  [h release];
  [pool drain];
  return 0;
}
