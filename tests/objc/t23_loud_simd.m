// flags: -fobjc-arc -framework SceneKit
// A host method whose parameter is a SIMD vector: the runtime encodes it as nothing ("v32@0:816"), so a send typed from
// the encoding would silently drop the argument. The translated send must stop loudly instead (natively it prints 2.0).
#import <SceneKit/SceneKit.h>
#include <stdio.h>

int main(void) {
  @autoreleasepool {
    SCNNode* n = [SCNNode node];
    printf("node created\n");
    n.simdPosition = simd_make_float3(1, 2, 3);
    printf("y %.1f\n", n.position.y);
  }
  return 0;
}
