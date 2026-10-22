// The class and protocol of t17_categories, in a guest dylib: the executable's categories on it are not merged by the
// linker, so the loader attaches them.
#import <Foundation/Foundation.h>
@protocol HasAnswer
@property (class, nonatomic, readonly) int answer;
@property (nonatomic, readonly) int inst;
@end
@interface Person : NSObject <HasAnswer> - (NSString*)kind; + (NSString*)species; @end
@implementation Person
- (NSString*)kind { return @"base"; }
+ (NSString*)species { return @"human"; }
+ (int)answer { return 42; }
- (int)inst { return 1; }
@end
