/* P10 L3 library probe, the outside program on Linux: loads PROBE_LIB (a library the packaged backend also holds in
 * _internal/) by its soname through the normal search order, as any outside tool would, and appends one line to
 * <its own path>.log: the first argument (the route), the LD_LIBRARY_PATH it got, and the file the loader picked
 * ("-" when nothing loaded, and then it exits 7, so a route that loads nothing fails). Built by scripts/p10/sidecar_smoke.py with gcc -DPROBE_LIB='"libssl.so.3"'. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char self[4096], log[4200];
    ssize_t n = readlink("/proc/self/exe", self, sizeof(self) - 1);
    if (n <= 0) return 5;
    self[n] = 0;
    snprintf(log, sizeof(log), "%s.log", self);
    const char *loaded = "-";
    void *handle = dlopen(PROBE_LIB, RTLD_NOW | RTLD_LOCAL);
    struct link_map *map = NULL;
    if (handle && dlinfo(handle, RTLD_DI_LINKMAP, &map) == 0 && map && map->l_name) loaded = map->l_name;
    const char *path = getenv("LD_LIBRARY_PATH");
    FILE *out = fopen(log, "a");
    if (!out) return 6;
    fprintf(out, "%s\t%s\t%s\n", argc > 1 ? argv[1] : "-", path ? path : "", loaded);
    fclose(out);
    return loaded[0] == '-' ? 7 : 0;
}
