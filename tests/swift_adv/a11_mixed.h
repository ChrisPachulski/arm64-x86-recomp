#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
typedef struct { double x, y; int tag; } MXPoint;
@protocol MXSource
- (NSInteger)valueAt:(NSInteger)i;
- (NSString *)nameFor:(MXPoint)p;
@end
@interface MXEngine : NSObject
@property (nonatomic) NSInteger ticks;
@property (nonatomic, copy) NSString *title;
- (instancetype)initWithTitle:(NSString *)t;
- (NSString *)step;
- (NSString *)hook:(NSInteger)n;
- (NSInteger)sumFrom:(id<MXSource>)src count:(NSInteger)n;
- (NSArray<NSString *> *)mapNames:(NSArray *)objs with:(NSString *(^)(id obj, NSUInteger idx))f;
+ (MXEngine *)makeByName:(NSString *)cls;
@end
MXPoint MXMid(MXPoint a, MXPoint b);
NSString *MXDescribe(id obj);
NS_ASSUME_NONNULL_END
