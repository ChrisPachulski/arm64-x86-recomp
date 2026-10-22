// An exception raised inside a guest -initWithCoder: (with a guest @finally and ARC locals) and caught by HOST code
// (-[NSKeyedUnarchiver decodeTopLevelObjectForKey:error:] turns it into an NSError). Does the guest @finally run?
#import <Foundation/Foundation.h>
static int deallocs;
@interface Tmp : NSObject @end
@implementation Tmp - (void)dealloc { deallocs++; } @end
@interface Bad : NSObject <NSCoding> @end
@implementation Bad
- (void)encodeWithCoder:(NSCoder*)c { [c encodeInt:1 forKey:@"k"]; }
- (instancetype)initWithCoder:(NSCoder*)c {
  Tmp* local = [Tmp new];
  @try {
    [NSException raise:NSInvalidUnarchiveOperationException format:@"bad %d", 7];
  } @finally {
    printf("guest finally ran (local %s)\n", local ? "live" : "nil");
  }
  return self;
}
@end
int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  @autoreleasepool {
    NSData* d = [NSKeyedArchiver archivedDataWithRootObject:[Bad new] requiringSecureCoding:NO error:NULL];
    NSKeyedUnarchiver* u = [[NSKeyedUnarchiver alloc] initForReadingFromData:d error:NULL];
    u.requiresSecureCoding = NO;
    NSError* err = nil;
    @autoreleasepool {
      id o = [u decodeTopLevelObjectForKey:NSKeyedArchiveRootObjectKey error:&err];
      printf("object %s error %ld\n", o ? "yes" : "nil", (long)err.code);
    }
    [u finishDecoding];
  }
  printf("Tmp deallocs %d\n", deallocs);
  return 0;
}
