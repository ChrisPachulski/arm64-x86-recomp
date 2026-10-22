// Sorting with a guest C function pointer (sortedArrayUsingFunction:context:, an NSInteger(*)(id, id, void*) parameter).
#import <Foundation/Foundation.h>
static NSInteger byInt(id a, id b, void* ctx) { int dir = *(int*)ctx; return dir * [a compare:b]; }
int main(void) {
  @autoreleasepool {
    int dir = -1;
    NSArray* a = [@[@3, @1, @2, @5, @4] sortedArrayUsingFunction:byInt context:&dir];
    printf("%s\n", [a componentsJoinedByString:@","].UTF8String);
  }
  return 0;
}
