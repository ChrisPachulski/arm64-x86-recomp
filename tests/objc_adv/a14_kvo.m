// KVO on guest properties: automatic and manual notification, Old/New/Initial/Prior options, context, dependent keys,
// nested key paths, guest observer; KVC collection operators over guest objects.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
static int ctx = 42;
@interface P : NSObject
@property (nonatomic) int age;
@property (nonatomic, copy) NSString* first;
@property (nonatomic, copy) NSString* last;
@property (nonatomic, readonly) NSString* full;
@property (nonatomic) double manual;
@property (nonatomic, strong) P* friend;
@property (nonatomic) NSRect frame;
@end
@implementation P
+ (NSSet*)keyPathsForValuesAffectingFull { return [NSSet setWithArray:@[@"first", @"last"]]; }
+ (BOOL)automaticallyNotifiesObserversOfManual { return NO; }
- (NSString*)full { return [NSString stringWithFormat:@"%@ %@", _first, _last]; }
- (void)setManual:(double)m { [self willChangeValueForKey:@"manual"]; _manual = m; [self didChangeValueForKey:@"manual"]; }
@end
@interface Obs : NSObject @property (strong) NSMutableArray* seen; @end
@implementation Obs
- (instancetype)init { if ((self = [super init])) _seen = [NSMutableArray array]; return self; }
- (void)observeValueForKeyPath:(NSString*)kp ofObject:(id)o change:(NSDictionary*)ch context:(void*)c {
  NSString* line = [NSString stringWithFormat:@"%@ old=%@ new=%@ prior=%@ ctx=%d", kp, ch[NSKeyValueChangeOldKey], ch[NSKeyValueChangeNewKey],
                    ch[NSKeyValueChangeNotificationIsPriorKey] ?: @0, c ? *(int*)c : -1];
  [_seen addObject:line];
}
@end
int main(void) {
  @autoreleasepool {
    P* p = [P new]; p.first = @"Ada"; p.last = @"L";
    P* q = [P new]; q.age = 5; p.friend = q;
    Obs* o = [Obs new];
    NSKeyValueObservingOptions opt = NSKeyValueObservingOptionNew | NSKeyValueObservingOptionOld;
    [p addObserver:o forKeyPath:@"age" options:opt | NSKeyValueObservingOptionInitial context:&ctx];
    [p addObserver:o forKeyPath:@"full" options:opt context:&ctx];
    [p addObserver:o forKeyPath:@"manual" options:opt | NSKeyValueObservingOptionPrior context:NULL];
    [p addObserver:o forKeyPath:@"friend.age" options:opt context:&ctx];
    [p addObserver:o forKeyPath:@"frame" options:opt context:&ctx];
    printf("class %s isa-changed %d\n", NSStringFromClass([p class]).UTF8String, object_getClass(p) != [P class]);
    p.age = 30; p.age = 31;
    p.last = @"Lovelace";
    p.manual = 1.5;
    q.age = 6;
    p.friend = [P new];
    p.frame = NSMakeRect(1, 2, 3, 4);
    [p setValue:@40 forKey:@"age"];
    [p removeObserver:o forKeyPath:@"age"];
    p.age = 99;
    [p removeObserver:o forKeyPath:@"full"]; [p removeObserver:o forKeyPath:@"manual"]; [p removeObserver:o forKeyPath:@"friend.age"];
    [p removeObserver:o forKeyPath:@"frame"];
    for (NSString* s in o.seen) printf("%s\n", s.UTF8String);
    NSMutableArray* ps = [NSMutableArray array];
    for (int i = 1; i <= 10; i++) { P* x = [P new]; x.age = i * 3; x.first = i % 2 ? @"odd" : @"even"; [ps addObject:x]; }
    printf("%s\n", [NSString stringWithFormat:@"@sum %@ @avg %@ @max %@ distinct %lu", [ps valueForKeyPath:@"@sum.age"], [ps valueForKeyPath:@"@avg.age"],
           [ps valueForKeyPath:@"@max.age"], (unsigned long)[[ps valueForKeyPath:@"@distinctUnionOfObjects.first"] count]].UTF8String);
    printf("filtered %lu\n", (unsigned long)[ps filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(P* x, NSDictionary* b) { return x.age > 15; }]].count);
  }
  return 0;
}
