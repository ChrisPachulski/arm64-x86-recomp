// super through three guest levels on top of host classes (NSNumberFormatter, NSObject), class-method super, a guest
// category overriding host methods (instance and class), a host method calling back into guest overrides.
#import <Foundation/Foundation.h>
@interface FA : NSNumberFormatter @end
@interface FB : FA @end
@interface FC : FB @end
@implementation FA
- (NSString*)stringFromNumber:(NSNumber*)n { return [NSString stringWithFormat:@"A(%@)", [super stringFromNumber:n]]; }
+ (NSString*)who { return @"A"; }
- (NSString*)description { return [@"descA:" stringByAppendingString:NSStringFromClass([super class])]; }
@end
@implementation FB
- (NSString*)stringFromNumber:(NSNumber*)n { return [NSString stringWithFormat:@"B(%@)", [super stringFromNumber:@(n.intValue + 1)]]; }
+ (NSString*)who { return [@"B>" stringByAppendingString:[super who]]; }
@end
@implementation FC
- (instancetype)init { if ((self = [super init])) { self.numberStyle = NSNumberFormatterDecimalStyle; self.locale = [NSLocale localeWithLocaleIdentifier:@"en_US"]; } return self; }
- (NSString*)stringFromNumber:(NSNumber*)n { return [NSString stringWithFormat:@"C(%@)", [super stringFromNumber:@(n.intValue * 1000)]]; }
+ (NSString*)who { return [@"C>" stringByAppendingString:[super who]]; }
- (NSString*)description { return [@"descC>" stringByAppendingString:[super description]]; }
@end

@interface Base : NSObject - (NSString*)name; @end
@implementation Base - (NSString*)name { return @"base"; } @end

@implementation NSValueTransformer (Guest)
+ (BOOL)allowsReverseTransformation { return NO; }
- (id)transformedValue:(id)v { return [NSString stringWithFormat:@"cat<%@>", v]; }
@end
@implementation Base (Guest)
- (NSString*)name { return @"category-wins"; }
@end
@implementation NSString (GuestExtra)
- (NSString*)shout { return [[self uppercaseString] stringByAppendingString:@"!"]; }
+ (NSString*)greeting { return @"hello from a class category"; }
@end

int main(void) {
  @autoreleasepool {
    FC* f = [FC new];
    printf("chain: %s\n", [f stringFromNumber:@12].UTF8String);
    printf("via host: %s\n", [f stringForObjectValue:@3].UTF8String);    // host NSFormatter path into the guest override
    printf("class: %s\n", [FC who].UTF8String);
    printf("desc: %s\n", f.description.UTF8String);
    printf("value transformer: %s reverse %d\n", [(NSString*)[[NSValueTransformer new] transformedValue:@5] UTF8String],
           (int)[NSValueTransformer allowsReverseTransformation]);
    printf("guest cat over guest: %s\n", [Base new].name.UTF8String);
    printf("cat on NSString: %s %s\n", [@"abc" shout].UTF8String, [NSString greeting].UTF8String);
    printf("responds %d %d\n", (int)[@"x" respondsToSelector:@selector(shout)], (int)[NSString respondsToSelector:@selector(greeting)]);
  }
  return 0;
}
