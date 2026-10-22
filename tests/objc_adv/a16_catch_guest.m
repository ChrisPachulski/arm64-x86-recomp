// Guest @throw caught by a guest @catch (with @finally). Native prints the catch; the design says the translated program
// must fail loudly, never continue silently.
#import <Foundation/Foundation.h>
int main(void) {
  @autoreleasepool {
    @try {
      @throw [NSException exceptionWithName:@"GuestEx" reason:@"thrown by guest" userInfo:nil];
    } @catch (NSException* e) {
      printf("caught %s\n", e.name.UTF8String);
    } @finally {
      printf("finally\n");
    }
  }
  return 0;
}
