/*
 * Sample C++ file for parser test fixtures.
 *
 * Covers: C++ STL headers, local includes, class with methods,
 *         standalone function, static function, namespace, enum class.
 */
#include <iostream>
#include <vector>
#include <string>
#include <memory>

#include <cstdio>
#include <cstdlib>

#include "engine.h"
#include "utils/math.h"

namespace demo {

class Greeter {
public:
    std::string greet(const std::string& name) const {
        return "Hello, " + name;
    }

    void reset() {}
};

struct Point {
    double x;
    double y;
};

enum class Direction {
    North,
    South,
    East,
    West,
};

std::string make_greeting(const std::string& name) {
    return "Hi, " + name;
}

} // namespace demo

static void file_local() {}
