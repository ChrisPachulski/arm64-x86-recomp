// objc_methods: every method of every class defined in the frameworks named on the command line (x86_64, headless: no
// class is messaged, so no +initialize runs), and every method description of protocols whose names start with a
// prefix given after "--". One line each: selector TAB owner TAB kind (i/c instance or class method, P/p required or
// optional protocol method, then i/c) TAB type encoding.
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <objc/runtime.h>
#include <stdio.h>
#include <string.h>

static void methods(Class k, const char* owner, char kind) {
  unsigned n = 0;
  Method* ml = class_copyMethodList(k, &n);
  for (unsigned i = 0; i < n; i++) printf("%s\t%s\t%c\t%s\n", sel_getName(method_getName(ml[i])), owner, kind, method_getTypeEncoding(ml[i]) ?: "");
  free(ml);
}

int main(int argc, char** argv) {
  int dash = argc;
  for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "--")) dash = i;
  for (int i = 1; i < dash; i++) if (!dlopen(argv[i], RTLD_LAZY)) fprintf(stderr, "cannot load %s\n", argv[i]);
  for (uint32_t im = 0; im < _dyld_image_count(); im++) {
    const char* path = _dyld_get_image_name(im);
    int want = 0;
    for (int i = 1; i < dash; i++) want |= !strcmp(path, argv[i]);
    if (!want) continue;
    unsigned n = 0;
    const char** names = objc_copyClassNamesForImage(path, &n);
    for (unsigned i = 0; i < n; i++) {
      Class k = objc_getClass(names[i]);
      if (!k) continue;
      methods(k, names[i], 'i');
      methods(object_getClass((id)k), names[i], 'c');
    }
    free(names);
  }
  unsigned np = 0;
  Protocol* __unsafe_unretained* ps = objc_copyProtocolList(&np);
  for (unsigned i = 0; i < np; i++) {
    const char* pn = protocol_getName(ps[i]);
    int want = 0;
    for (int j = dash + 1; j < argc; j++) want |= !strncmp(pn, argv[j], strlen(argv[j]));
    if (!want) continue;
    for (int req = 0; req < 2; req++)
      for (int inst = 0; inst < 2; inst++) {
        unsigned nd = 0;
        struct objc_method_description* d = protocol_copyMethodDescriptionList(ps[i], req, inst, &nd);
        for (unsigned k = 0; k < nd; k++)
          printf("%s\t%s\t%c%c\t%s\n", sel_getName(d[k].name), pn, req ? 'P' : 'p', inst ? 'i' : 'c', d[k].types ?: "");
        free(d);
      }
  }
  free(ps);
  return 0;
}
