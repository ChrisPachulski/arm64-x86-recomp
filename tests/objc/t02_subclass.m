// Guest NSObject subclasses: ivars, properties, class methods, KVC, KVO, respondsToSelector:, -description used by the
// host's %@ formatting, -compare: called by the host's sort, ARC ivars released by .cxx_destruct, dealloc order.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>

@interface Tracked : NSObject
@property (nonatomic, copy) NSString* name;
@end
@implementation Tracked
- (void)dealloc { printf("dealloc Tracked %s\n", _name.UTF8String); }
@end

@interface Item : NSObject {
@public
  int _raw;
  double _weight;
}
@property (nonatomic) NSInteger rank;
@property (nonatomic, strong) Tracked* tag;
@property (nonatomic, copy) NSString* title;
@property (nonatomic) BOOL flag;
@property (nonatomic) double score;
+ (instancetype)itemWithRank:(NSInteger)r title:(NSString*)t;
+ (int)instances;
- (NSComparisonResult)compare:(Item*)other;
@end

static int g_instances;
@implementation Item
+ (instancetype)itemWithRank:(NSInteger)r title:(NSString*)t {
  Item* i = [[self alloc] init]; i.rank = r; i.title = t; g_instances++; return i;
}
+ (int)instances { return g_instances; }
- (NSString*)description { return [NSString stringWithFormat:@"<Item %ld %@>", (long)_rank, _title]; }
- (NSComparisonResult)compare:(Item*)other { return _rank < other.rank ? NSOrderedAscending : _rank > other.rank ? NSOrderedDescending : NSOrderedSame; }
- (void)dealloc { printf("dealloc Item %ld\n", (long)_rank); }
@end

@interface Watcher : NSObject
@property (nonatomic) int seen;
@end
@implementation Watcher
- (void)observeValueForKeyPath:(NSString*)kp ofObject:(id)o change:(NSDictionary*)ch context:(void*)ctx {
  _seen++;
  printf("kvo %s: %s -> %s\n", kp.UTF8String, [ch[NSKeyValueChangeOldKey] description].UTF8String, [ch[NSKeyValueChangeNewKey] description].UTF8String);
}
@end

int main(void) {
  Item *a, *b, *c;
  @autoreleasepool {                         /* every autoreleased object (the ARC return handoff is not bridged) ends here */
    a = [Item itemWithRank:3 title:@"three"];
    b = [Item itemWithRank:1 title:@"one"];
    c = [Item itemWithRank:2 title:@"two"];
    a->_raw = 77; a->_weight = 0.5;
    printf("ivars: %d %g instances %d\n", a->_raw, a->_weight, [Item instances]);
    printf("description via %%@: %s\n", [NSString stringWithFormat:@"%@ and %@", a, b].UTF8String);
    NSArray* arr = @[a, b, c];
    printf("array description: %s\n", [[arr description] stringByReplacingOccurrencesOfString:@"\n" withString:@""].UTF8String);
    NSArray* s = [arr sortedArrayUsingSelector:@selector(compare:)];
    printf("host sort with guest compare: %s %s %s\n", [s[0] title].UTF8String, [s[1] title].UTF8String, [s[2] title].UTF8String);
    printf("responds: %d %d %d\n", [a respondsToSelector:@selector(compare:)], [a respondsToSelector:@selector(nothing)],
           [Item respondsToSelector:@selector(instances)]);
    [a setValue:@99 forKey:@"rank"];
    [a setValue:@"kvc-title" forKey:@"title"];
    [a setValue:@YES forKey:@"flag"];
    [a setValue:@2.75 forKey:@"score"];
    printf("kvc: %s %s %s %s raw %s\n", [[a valueForKey:@"rank"] description].UTF8String, [[a valueForKey:@"title"] UTF8String],
           [[a valueForKey:@"flag"] description].UTF8String, [[a valueForKey:@"score"] description].UTF8String,
           [[a valueForKey:@"_raw"] description].UTF8String);
    printf("kvc keypath: %s\n", [[arr valueForKeyPath:@"@max.rank"] description].UTF8String);
    Watcher* w = [Watcher new];
    [b addObserver:w forKeyPath:@"rank" options:NSKeyValueObservingOptionOld | NSKeyValueObservingOptionNew context:NULL];
    b.rank = 5; b.rank = 6;
    [b removeObserver:w forKeyPath:@"rank"];
    b.rank = 7;
    printf("kvo seen %d, class after removal %s\n", w.seen, class_getName(object_getClass(b)));
    Tracked* t = [Tracked new]; t.name = @"tag-a";
    a.tag = t; t = nil;
    printf("tag set\n");
    a.tag = nil;
    printf("tag cleared\n");
    c.tag = [Tracked new]; c.tag.name = @"tag-c";
    printf("isKindOfClass %d %d isMemberOfClass %d superclass %s\n", [a isKindOfClass:[NSObject class]], [a isKindOfClass:[NSString class]],
           [a isMemberOfClass:[Item class]], class_getName([Item superclass]));
  }
  printf("pool drained\n");
  b = nil; a = nil; c = nil;
  printf("locals cleared\n");
  return 0;
}
