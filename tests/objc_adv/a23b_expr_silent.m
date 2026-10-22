// NSExpression expressionWithFormat: with only %@ / %d arguments (no conversion the C formatter rejects).
#import <Foundation/Foundation.h>
int main(void) {
  @autoreleasepool {
    NSExpression* e = [NSExpression expressionWithFormat:@"%@ + %d", @5, 1];
    printf("expr type %lu value %s\n", (unsigned long)e.expressionType, [[e expressionValueWithObject:nil context:nil] description].UTF8String);
    NSExpression* s = [NSExpression expressionWithFormat:@"%@", @"name"];
    printf("string expr type %lu value %s\n", (unsigned long)s.expressionType, [[s expressionValueWithObject:@{@"name": @"N"} context:nil] description].UTF8String);
  }
  return 0;
}
