// "...WithFormat:" methods whose format is not NSString's: NSExpression (predicate format language, %K key paths).
#import <Foundation/Foundation.h>
int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  @autoreleasepool {
    NSExpression* e = [NSExpression expressionWithFormat:@"%K + %@", @"age", @5];
    printf("expr type %lu value %s\n", (unsigned long)e.expressionType, [[e expressionValueWithObject:@{@"age": @10} context:nil] description].UTF8String);
  }
  return 0;
}
