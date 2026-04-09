/*
 * Sample C file for parser test fixtures.
 *
 * Covers: system includes, local includes, path includes, conditional includes,
 *         named struct, named enum, regular function, static function.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "utils.h"
#include "subdir/helper.h"

#ifdef DEBUG
#include <assert.h>
#endif

struct Node {
    int value;
    struct Node *next;
};

enum Color {
    RED,
    GREEN,
    BLUE,
};

int add(int a, int b) {
    return a + b;
}

static int internal_helper(int x) {
    return x * 2;
}

int main(void) {
    printf("hello\n");
    return 0;
}
