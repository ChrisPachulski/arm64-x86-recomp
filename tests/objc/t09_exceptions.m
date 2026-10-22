// An Objective-C exception raised by the host (here NSRangeException) reaches the guest @catch around the send.
#import <Foundation/Foundation.h>

int main(void) {
  @autoreleasepool {
    @try {
      NSArray* a = @[@1];
      printf("about to fail\n");
      fflush(stdout);
      [a objectAtIndex:5];
      printf("not reached\n");
    } @catch (NSException* e) {
      printf("caught %s\n", e.name.UTF8String);
    }
  }
  return 0;
}
