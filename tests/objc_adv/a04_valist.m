// A guest variadic logging helper that forwards its va_list to Foundation (-initWithFormat:arguments:).
#import <Foundation/Foundation.h>
static NSString* Fmt(NSString* f, ...) {
  va_list ap; va_start(ap, f);
  NSString* s = [[NSString alloc] initWithFormat:f arguments:ap];
  va_end(ap);
  return s;
}
static NSString* FmtLoc(NSString* f, ...) {
  va_list ap; va_start(ap, f);
  NSString* s = [[NSString alloc] initWithFormat:f locale:nil arguments:ap];
  va_end(ap);
  return s;
}
int main(void) {
  @autoreleasepool {
    printf("%s\n", Fmt(@"valist %d %@ %.3f %s", 5, @"obj", 2.5, "cstr").UTF8String);
    printf("%s\n", FmtLoc(@"valist-loc %d %@", 6, @"o2").UTF8String);
  }
  return 0;
}
