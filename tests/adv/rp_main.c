/* #8: executable with LC_RPATH @loader_path/lib, linked against the plugin run/plugins/librpa.dylib. */
void a_report(void);
int main(void) {
    a_report();
    return 0;
}
