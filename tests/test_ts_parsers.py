"""Tests for ts_parsers.py — tree-sitter-backed import parsers."""

import pytest
from import_analysis import ImportType
from ts_parsers import (
    PythonImportParser,
    CImportParserTS,
    JavaScriptImportParserTS,
    TypeScriptImportParserTS,
    JavaImportParserTS,
    RustImportParser,
    JavaSymbolExtractor,
    PythonSymbolExtractor,
    JavaScriptSymbolExtractor,
    TypeScriptSymbolExtractor,
    RustSymbolExtractor,
    CSymbolExtractor,
    SymbolExtractorRegistry,
)


@pytest.fixture(scope="module")
def parser():
    return PythonImportParser()


def parse(parser, src: str):
    return parser.parse_file("test.py", src)


# ---------------------------------------------------------------------------
# import_statement forms
# ---------------------------------------------------------------------------

class TestImportStatement:
    def test_simple_system(self, parser):
        imports = parse(parser, "import os\n")
        assert len(imports) == 1
        imp = imports[0]
        assert imp.imported_name == "os"
        assert imp.import_type == ImportType.SYSTEM
        assert imp.line_number == 1
        assert imp.raw_statement == "import os"

    def test_simple_external(self, parser):
        imports = parse(parser, "import numpy\n")
        assert len(imports) == 1
        assert imports[0].imported_name == "numpy"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_dotted_system(self, parser):
        imports = parse(parser, "import os.path\n")
        assert imports[0].imported_name == "os.path"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_multiple_modules(self, parser):
        imports = parse(parser, "import os, sys\n")
        assert len(imports) == 2
        names = {i.imported_name for i in imports}
        assert names == {"os", "sys"}
        assert all(i.import_type == ImportType.SYSTEM for i in imports)
        # Both share the same raw_statement and line
        assert all(i.line_number == 1 for i in imports)

    def test_aliased(self, parser):
        imports = parse(parser, "import numpy as np\n")
        assert len(imports) == 1
        assert imports[0].imported_name == "numpy"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_aliased_system(self, parser):
        imports = parse(parser, "import collections as col\n")
        assert imports[0].imported_name == "collections"
        assert imports[0].import_type == ImportType.SYSTEM


# ---------------------------------------------------------------------------
# import_from_statement forms
# ---------------------------------------------------------------------------

class TestFromImportStatement:
    def test_from_system(self, parser):
        imports = parse(parser, "from pathlib import Path\n")
        assert len(imports) == 1
        imp = imports[0]
        assert imp.imported_name == "pathlib"
        assert imp.import_type == ImportType.SYSTEM
        assert imp.line_number == 1

    def test_from_external(self, parser):
        imports = parse(parser, "from numpy import array\n")
        assert imports[0].imported_name == "numpy"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_from_multiple_names_single_import(self, parser):
        # The module is what matters — names being imported are irrelevant for graphing
        imports = parse(parser, "from pathlib import Path, PurePath\n")
        assert len(imports) == 1
        assert imports[0].imported_name == "pathlib"

    def test_from_relative_dot(self, parser):
        imports = parse(parser, "from . import utils\n")
        assert len(imports) == 1
        imp = imports[0]
        assert imp.imported_name == "."
        assert imp.import_type == ImportType.LOCAL

    def test_from_relative_parent(self, parser):
        imports = parse(parser, "from .. import sibling\n")
        assert imports[0].imported_name == ".."
        assert imports[0].import_type == ImportType.LOCAL

    def test_from_relative_with_module(self, parser):
        imports = parse(parser, "from ..sibling import foo\n")
        assert imports[0].imported_name == "..sibling"
        assert imports[0].import_type == ImportType.LOCAL

    def test_from_multiline(self, parser):
        src = (
            "from collections import (\n"
            "    OrderedDict,\n"
            "    defaultdict,\n"
            ")\n"
        )
        imports = parse(parser, src)
        assert len(imports) == 1
        assert imports[0].imported_name == "collections"
        assert imports[0].import_type == ImportType.SYSTEM


# ---------------------------------------------------------------------------
# Multi-line files and line numbers
# ---------------------------------------------------------------------------

class TestLineNumbers:
    def test_line_numbers(self, parser):
        src = "import os\nimport sys\nfrom pathlib import Path\n"
        imports = parse(parser, src)
        assert imports[0].line_number == 1
        assert imports[1].line_number == 2
        assert imports[2].line_number == 3

    def test_leading_blank_lines(self, parser):
        src = "\n\nimport os\n"
        imports = parse(parser, src)
        assert imports[0].line_number == 3


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_file(self, parser):
        assert parse(parser, "") == []

    def test_no_imports(self, parser):
        src = "x = 1\ndef foo():\n    pass\n"
        assert parse(parser, src) == []

    def test_import_in_string_not_parsed(self, parser):
        src = 'x = "import os"\n'
        assert parse(parser, src) == []

    def test_import_in_comment_not_parsed(self, parser):
        src = "# import os\nimport sys\n"
        imports = parse(parser, src)
        assert len(imports) == 1
        assert imports[0].imported_name == "sys"

    def test_import_inside_function_not_included(self, parser):
        # Top-level walk only — imports inside functions are not graph edges
        # we care about at the file level (may revisit later)
        src = "def foo():\n    import os\n"
        assert parse(parser, src) == []

    def test_future_import(self, parser):
        src = "from __future__ import annotations\n"
        imports = parse(parser, src)
        assert imports[0].imported_name == "__future__"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_supported_extensions(self, parser):
        assert ".py" in parser.get_supported_extensions()
        assert ".pyw" in parser.get_supported_extensions()


# ===========================================================================
# C / C++
# ===========================================================================

@pytest.fixture(scope="module")
def c_parser():
    return CImportParserTS()


def parse_c(c_parser, src: str, filename="test.c"):
    return c_parser.parse_file(filename, src)


class TestCImportParserTS:
    def test_system_include(self, c_parser):
        imports = parse_c(c_parser, "#include <stdio.h>\n")
        assert len(imports) == 1
        imp = imports[0]
        assert imp.imported_name == "stdio.h"
        assert imp.import_type == ImportType.SYSTEM
        assert imp.line_number == 1

    def test_local_include(self, c_parser):
        imports = parse_c(c_parser, '#include "utils.h"\n')
        assert len(imports) == 1
        imp = imports[0]
        assert imp.imported_name == "utils.h"
        assert imp.import_type == ImportType.LOCAL

    def test_local_include_with_path(self, c_parser):
        imports = parse_c(c_parser, '#include "subdir/helper.h"\n')
        assert imports[0].imported_name == "subdir/helper.h"
        assert imports[0].import_type == ImportType.LOCAL

    def test_multiple_includes(self, c_parser):
        src = "#include <stdio.h>\n#include <stdlib.h>\n#include \"mylib.h\"\n"
        imports = parse_c(c_parser, src)
        assert len(imports) == 3
        assert imports[0].import_type == ImportType.SYSTEM
        assert imports[1].import_type == ImportType.SYSTEM
        assert imports[2].import_type == ImportType.LOCAL

    def test_include_inside_ifdef(self, c_parser):
        src = "#ifdef DEBUG\n#include <assert.h>\n#endif\n"
        imports = parse_c(c_parser, src)
        assert len(imports) == 1
        assert imports[0].imported_name == "assert.h"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_no_includes(self, c_parser):
        src = "int main() { return 0; }\n"
        assert parse_c(c_parser, src) == []

    def test_comment_not_parsed(self, c_parser):
        src = "// #include <stdio.h>\n#include <string.h>\n"
        imports = parse_c(c_parser, src)
        assert len(imports) == 1
        assert imports[0].imported_name == "string.h"

    def test_cpp_extensions_supported(self, c_parser):
        exts = c_parser.get_supported_extensions()
        for ext in (".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"):
            assert ext in exts

    def test_cpp_system_include(self, c_parser):
        imports = parse_c(c_parser, "#include <vector>\n", filename="test.cpp")
        assert imports[0].imported_name == "vector"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_line_numbers(self, c_parser):
        src = "#include <stdio.h>\n\n#include \"local.h\"\n"
        imports = parse_c(c_parser, src)
        assert imports[0].line_number == 1
        assert imports[1].line_number == 3


# ===========================================================================
# JavaScript
# ===========================================================================

@pytest.fixture(scope="module")
def js_parser():
    return JavaScriptImportParserTS()


def parse_js(js_parser, src: str, filename="test.js"):
    return js_parser.parse_file(filename, src)


class TestJavaScriptImportParserTS:
    def test_default_import_local(self, js_parser):
        imports = parse_js(js_parser, "import foo from './bar';\n")
        assert len(imports) == 1
        imp = imports[0]
        assert imp.imported_name == "./bar"
        assert imp.import_type == ImportType.LOCAL

    def test_named_import_external(self, js_parser):
        imports = parse_js(js_parser, "import { a, b } from 'lodash';\n")
        assert imports[0].imported_name == "lodash"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_namespace_import_system(self, js_parser):
        imports = parse_js(js_parser, "import * as fs from 'fs';\n")
        assert imports[0].imported_name == "fs"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_side_effect_import(self, js_parser):
        imports = parse_js(js_parser, "import './polyfill';\n")
        assert imports[0].imported_name == "./polyfill"
        assert imports[0].import_type == ImportType.LOCAL

    def test_node_protocol_system(self, js_parser):
        imports = parse_js(js_parser, "import path from 'node:path';\n")
        assert imports[0].import_type == ImportType.SYSTEM

    def test_require_local(self, js_parser):
        imports = parse_js(js_parser, "const x = require('./local');\n")
        assert imports[0].imported_name == "./local"
        assert imports[0].import_type == ImportType.LOCAL

    def test_require_external(self, js_parser):
        imports = parse_js(js_parser, "const express = require('express');\n")
        assert imports[0].imported_name == "express"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_dynamic_import(self, js_parser):
        imports = parse_js(js_parser, "const m = await import('some-module');\n")
        assert imports[0].imported_name == "some-module"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_parent_relative(self, js_parser):
        imports = parse_js(js_parser, "import util from '../util';\n")
        assert imports[0].imported_name == "../util"
        assert imports[0].import_type == ImportType.LOCAL

    def test_scoped_package_external(self, js_parser):
        imports = parse_js(js_parser, "import { foo } from '@org/pkg';\n")
        assert imports[0].imported_name == "@org/pkg"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_empty_file(self, js_parser):
        assert parse_js(js_parser, "") == []

    def test_line_number(self, js_parser):
        src = "\nimport foo from './a';\n"
        imports = parse_js(js_parser, src)
        assert imports[0].line_number == 2

    def test_export_star_from(self, js_parser):
        imports = parse_js(js_parser, "export * from './utils';\n")
        assert len(imports) == 1
        assert imports[0].imported_name == "./utils"
        assert imports[0].import_type == ImportType.LOCAL

    def test_export_named_from(self, js_parser):
        imports = parse_js(js_parser, "export { foo } from './helpers';\n")
        assert imports[0].imported_name == "./helpers"
        assert imports[0].import_type == ImportType.LOCAL

    def test_export_from_external(self, js_parser):
        imports = parse_js(js_parser, "export { debounce } from 'lodash';\n")
        assert imports[0].imported_name == "lodash"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_bare_export_not_captured(self, js_parser):
        imports = parse_js(js_parser, "export { foo };\n")
        assert imports == []

    def test_supported_extensions(self, js_parser):
        exts = js_parser.get_supported_extensions()
        for ext in (".js", ".jsx", ".mjs"):
            assert ext in exts


# ===========================================================================
# TypeScript
# ===========================================================================

@pytest.fixture(scope="module")
def ts_parser():
    return TypeScriptImportParserTS()


def parse_ts(ts_parser, src: str, filename="test.ts"):
    return ts_parser.parse_file(filename, src)


class TestTypeScriptImportParserTS:
    def test_ts_import(self, ts_parser):
        imports = parse_ts(ts_parser, "import { Component } from '@angular/core';\n")
        assert imports[0].imported_name == "@angular/core"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_ts_local(self, ts_parser):
        imports = parse_ts(ts_parser, "import type { Foo } from './types';\n")
        assert imports[0].imported_name == "./types"
        assert imports[0].import_type == ImportType.LOCAL

    def test_tsx_file_parsed(self, ts_parser):
        src = "import React from 'react';\n"
        imports = parse_ts(ts_parser, src, filename="App.tsx")
        assert imports[0].imported_name == "react"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_tsx_local_import(self, ts_parser):
        imports = parse_ts(ts_parser, "import MyComp from './MyComp';\n", filename="App.tsx")
        assert imports[0].import_type == ImportType.LOCAL

    def test_multiple_imports(self, ts_parser):
        src = "import fs from 'fs';\nimport { readFile } from 'fs/promises';\n"
        imports = parse_ts(ts_parser, src)
        assert len(imports) == 2
        assert all(i.import_type == ImportType.SYSTEM for i in imports)

    def test_export_star_from(self, ts_parser):
        imports = parse_ts(ts_parser, "export * from './utils';\n")
        assert len(imports) == 1
        assert imports[0].imported_name == "./utils"
        assert imports[0].import_type == ImportType.LOCAL

    def test_export_named_from(self, ts_parser):
        imports = parse_ts(ts_parser, "export { Foo, Bar } from './models';\n")
        assert len(imports) == 1
        assert imports[0].imported_name == "./models"
        assert imports[0].import_type == ImportType.LOCAL

    def test_export_default_as_from(self, ts_parser):
        imports = parse_ts(ts_parser, "export { default as MyComp } from './MyComp';\n")
        assert imports[0].imported_name == "./MyComp"
        assert imports[0].import_type == ImportType.LOCAL

    def test_export_namespace_from(self, ts_parser):
        imports = parse_ts(ts_parser, "export * as ns from './ns';\n")
        assert imports[0].imported_name == "./ns"
        assert imports[0].import_type == ImportType.LOCAL

    def test_export_from_external(self, ts_parser):
        imports = parse_ts(ts_parser, "export { foo } from 'some-lib';\n")
        assert imports[0].imported_name == "some-lib"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_bare_export_not_captured(self, ts_parser):
        """export { Foo } with no 'from' clause creates no import dependency."""
        imports = parse_ts(ts_parser, "export { Foo };\n")
        assert imports == []

    def test_supported_extensions(self, ts_parser):
        exts = ts_parser.get_supported_extensions()
        assert ".ts" in exts
        assert ".tsx" in exts


# ===========================================================================
# Java
# ===========================================================================

@pytest.fixture(scope="module")
def java_parser():
    return JavaImportParserTS()


def parse_java(java_parser, src: str):
    return java_parser.parse_file("Test.java", src)


class TestJavaImportParserTS:
    def test_system_import(self, java_parser):
        imports = parse_java(java_parser, "import java.util.List;\npublic class Foo {}\n")
        assert len(imports) == 1
        imp = imports[0]
        assert imp.imported_name == "java.util.List"
        assert imp.import_type == ImportType.SYSTEM
        assert imp.line_number == 1

    def test_javax_system(self, java_parser):
        imports = parse_java(java_parser, "import javax.servlet.http.HttpServlet;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.SYSTEM

    def test_wildcard_import(self, java_parser):
        imports = parse_java(java_parser, "import java.util.*;\npublic class Foo {}\n")
        assert imports[0].imported_name == "java.util"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_static_import(self, java_parser):
        imports = parse_java(java_parser, "import static org.junit.Assert.assertEquals;\npublic class Foo {}\n")
        assert imports[0].imported_name == "org.junit.Assert.assertEquals"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_spring_external(self, java_parser):
        imports = parse_java(
            java_parser,
            "import org.springframework.stereotype.Service;\npublic class Foo {}\n"
        )
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_google_external(self, java_parser):
        imports = parse_java(java_parser, "import com.google.gson.Gson;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_local_import(self, java_parser):
        imports = parse_java(java_parser, "import com.example.MyClass;\npublic class Foo {}\n")
        assert imports[0].imported_name == "com.example.MyClass"
        assert imports[0].import_type == ImportType.LOCAL

    def test_no_import_after_class(self, java_parser):
        # Imports after class declaration should not be parsed (invalid Java anyway)
        src = "public class Foo {\n    void m() {}\n}\nimport java.util.List;\n"
        imports = parse_java(java_parser, src)
        assert len(imports) == 0

    def test_multiple_imports(self, java_parser):
        src = (
            "import java.util.List;\n"
            "import java.util.Map;\n"
            "import com.example.Foo;\n"
            "public class Bar {}\n"
        )
        imports = parse_java(java_parser, src)
        assert len(imports) == 3
        assert imports[0].import_type == ImportType.SYSTEM
        assert imports[1].import_type == ImportType.SYSTEM
        assert imports[2].import_type == ImportType.LOCAL

    def test_empty_file(self, java_parser):
        assert parse_java(java_parser, "") == []

    def test_supported_extensions(self, java_parser):
        assert ".java" in java_parser.get_supported_extensions()

    # -- expanded external prefix sets --------------------------------------

    def test_io_micrometer_external(self, java_parser):
        imports = parse_java(java_parser, "import io.micrometer.core.instrument.MeterRegistry;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_io_grpc_external(self, java_parser):
        imports = parse_java(java_parser, "import io.grpc.Channel;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_io_netty_external(self, java_parser):
        imports = parse_java(java_parser, "import io.netty.channel.ChannelHandler;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_io_opentelemetry_external(self, java_parser):
        imports = parse_java(java_parser, "import io.opentelemetry.api.trace.Tracer;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_com_squareup_external(self, java_parser):
        imports = parse_java(java_parser, "import com.squareup.okhttp3.OkHttpClient;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_net_bytebuddy_external(self, java_parser):
        imports = parse_java(java_parser, "import net.bytebuddy.ByteBuddy;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_org_bouncycastle_external(self, java_parser):
        imports = parse_java(java_parser, "import org.bouncycastle.crypto.Digest;\npublic class Foo {}\n")
        assert imports[0].import_type == ImportType.EXTERNAL


# ===========================================================================
# Symbol extraction tests
# ===========================================================================

# ---------------------------------------------------------------------------
# PythonSymbolExtractor
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def py_sym():
    return PythonSymbolExtractor()


def py_extract(extractor, src: str):
    return extractor.extract("f0", src)


class TestPythonSymbolExtractor:
    def test_top_level_function(self, py_sym):
        syms = py_extract(py_sym, "def foo():\n    pass\n")
        assert len(syms) == 1
        s = syms[0]
        assert s.kind == "function"
        assert s.name == "foo"
        assert s.start_line == 1
        assert s.is_exported is True

    def test_private_function_not_exported(self, py_sym):
        syms = py_extract(py_sym, "def _helper():\n    pass\n")
        assert syms[0].is_exported is False

    def test_class_and_method(self, py_sym):
        src = "class Foo:\n    def __init__(self):\n        pass\n"
        syms = py_extract(py_sym, src)
        kinds = {s.kind for s in syms}
        assert "class" in kinds
        assert "method" in kinds
        cls = next(s for s in syms if s.kind == "class")
        method = next(s for s in syms if s.kind == "method")
        assert cls.name == "Foo"
        assert cls.is_exported is True
        assert method.name == "__init__"
        assert method.is_exported is False

    def test_private_class_not_exported(self, py_sym):
        syms = py_extract(py_sym, "class _Internal:\n    pass\n")
        assert syms[0].is_exported is False

    def test_multiple_functions(self, py_sym):
        src = "def a():\n    pass\n\ndef b():\n    pass\n"
        syms = py_extract(py_sym, src)
        names = [s.name for s in syms]
        assert "a" in names
        assert "b" in names

    def test_end_line_correct(self, py_sym):
        src = "def foo():\n    x = 1\n    return x\n"
        syms = py_extract(py_sym, src)
        assert syms[0].start_line == 1
        assert syms[0].end_line == 3

    def test_file_id_propagated(self, py_sym):
        syms = PythonSymbolExtractor().extract("f42", "def f():\n    pass\n")
        assert syms[0].file_id == "f42"

    def test_id_placeholder_empty(self, py_sym):
        syms = py_extract(py_sym, "def f():\n    pass\n")
        assert syms[0].id == ""

    def test_fixture_py_simple_main(self):
        """Verify extraction against the actual py_simple fixture."""
        src = open("tests/fixtures/repos/py_simple/src/main.py").read()
        syms = PythonSymbolExtractor().extract("f0", src)
        names = [s.name for s in syms]
        assert "run" in names
        run = next(s for s in syms if s.name == "run")
        assert run.kind == "function"
        assert run.is_exported is True

    def test_fixture_py_simple_models(self):
        """User class + __init__ from models.py."""
        src = open("tests/fixtures/repos/py_simple/src/models.py").read()
        syms = PythonSymbolExtractor().extract("f0", src)
        kinds = {s.kind for s in syms}
        assert "class" in kinds
        assert "method" in kinds
        user = next(s for s in syms if s.kind == "class")
        assert user.name == "User"
        assert user.is_exported is True


# ---------------------------------------------------------------------------
# JavaScriptSymbolExtractor
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def js_sym():
    return JavaScriptSymbolExtractor()


def js_extract(extractor, src: str):
    return extractor.extract("f0", src)


class TestJavaScriptSymbolExtractor:
    def test_function_declaration(self, js_sym):
        syms = js_extract(js_sym, "function greet(name) { return name; }\n")
        assert len(syms) == 1
        s = syms[0]
        assert s.kind == "function"
        assert s.name == "greet"
        assert s.is_exported is False

    def test_export_function_declaration(self, js_sym):
        syms = js_extract(js_sym, "export function foo() {}\n")
        assert syms[0].is_exported is True
        assert syms[0].name == "foo"

    def test_class_declaration(self, js_sym):
        syms = js_extract(js_sym, "class Animal {}\n")
        assert len(syms) == 1
        assert syms[0].kind == "class"
        assert syms[0].name == "Animal"

    def test_cjs_export_marks_exported(self, js_sym):
        src = "function greet(name) { return name; }\nmodule.exports = { greet };\n"
        syms = js_extract(js_sym, src)
        greet = next(s for s in syms if s.name == "greet")
        assert greet.is_exported is True

    def test_arrow_function_const(self, js_sym):
        src = "const add = (a, b) => a + b;\n"
        syms = js_extract(js_sym, src)
        assert len(syms) == 1
        assert syms[0].name == "add"
        assert syms[0].kind == "function"

    def test_fixture_flat_js_utils(self):
        """greet function in utils.js is exported via module.exports."""
        src = open("tests/fixtures/repos/flat_js/utils.js").read()
        syms = JavaScriptSymbolExtractor().extract("f0", src)
        assert len(syms) == 1
        assert syms[0].name == "greet"
        assert syms[0].is_exported is True

    def test_fixture_flat_js_config_no_symbols(self):
        """config.js only has module.exports = { name: 'world' } — no function symbols."""
        src = open("tests/fixtures/repos/flat_js/config.js").read()
        syms = JavaScriptSymbolExtractor().extract("f0", src)
        assert syms == []


# ---------------------------------------------------------------------------
# SymbolExtractorRegistry
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# JavaSymbolExtractor
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def java_sym():
    return JavaSymbolExtractor()


def java_extract(extractor, src: str):
    return extractor.extract("f0", src)


class TestJavaSymbolExtractor:
    def test_public_class(self, java_sym):
        syms = java_extract(java_sym, "public class Foo {}")
        assert len(syms) == 1
        assert syms[0].name == "Foo"
        assert syms[0].kind == "class"
        assert syms[0].is_exported is True

    def test_package_private_class_not_exported(self, java_sym):
        syms = java_extract(java_sym, "class Foo {}")
        assert syms[0].is_exported is False

    def test_interface(self, java_sym):
        syms = java_extract(java_sym, "public interface Runnable {}")
        assert syms[0].kind == "interface"
        assert syms[0].name == "Runnable"
        assert syms[0].is_exported is True

    def test_enum(self, java_sym):
        syms = java_extract(java_sym, "public enum Color { RED, GREEN, BLUE }")
        assert syms[0].kind == "class"
        assert syms[0].name == "Color"

    def test_public_method_exported(self, java_sym):
        src = "public class Foo {\n    public void run() {}\n}"
        syms = java_extract(java_sym, src)
        methods = [s for s in syms if s.kind == "method"]
        assert len(methods) == 1
        assert methods[0].name == "run"
        assert methods[0].is_exported is True

    def test_private_method_not_exported(self, java_sym):
        src = "public class Foo {\n    private void helper() {}\n}"
        syms = java_extract(java_sym, src)
        methods = [s for s in syms if s.kind == "method"]
        assert methods[0].is_exported is False

    def test_constructor_extracted(self, java_sym):
        src = "public class Foo {\n    public Foo() {}\n}"
        syms = java_extract(java_sym, src)
        methods = [s for s in syms if s.kind == "method"]
        assert any(s.name == "Foo" for s in methods)

    def test_multiple_methods(self, java_sym):
        src = (
            "public class Service {\n"
            "    public void start() {}\n"
            "    public void stop() {}\n"
            "    private void init() {}\n"
            "}"
        )
        syms = java_extract(java_sym, src)
        method_names = [s.name for s in syms if s.kind == "method"]
        assert "start" in method_names
        assert "stop" in method_names
        assert "init" in method_names

    def test_line_numbers(self, java_sym):
        src = "public class Foo {\n    public void bar() {\n        int x = 1;\n    }\n}"
        syms = java_extract(java_sym, src)
        cls = next(s for s in syms if s.kind == "class")
        assert cls.start_line == 1
        assert cls.end_line == 5
        method = next(s for s in syms if s.kind == "method")
        assert method.start_line == 2

    def test_file_id_propagated(self, java_sym):
        syms = java_sym.extract("f99", "public class Foo {}")
        assert syms[0].file_id == "f99"

    def test_id_placeholder_empty(self, java_sym):
        syms = java_extract(java_sym, "public class Foo {}")
        assert syms[0].id == ""

    def test_fixture_app_java(self):
        src = open("tests/fixtures/repos/mixed_java_py/src/main/java/App.java").read()
        syms = JavaSymbolExtractor().extract("f0", src)
        names = [s.name for s in syms]
        assert "App" in names
        assert "main" in names

    def test_annotation_type(self, java_sym):
        syms = java_extract(java_sym, "public @interface MyAnnotation {}")
        assert syms[0].kind == "interface"
        assert syms[0].name == "MyAnnotation"

    def test_supported_extensions(self, java_sym):
        assert ".java" in java_sym.get_supported_extensions()


class TestSymbolExtractorRegistry:
    def test_default_registry_has_py(self):
        reg = SymbolExtractorRegistry.default()
        assert reg.get(".py") is not None

    def test_default_registry_has_js(self):
        reg = SymbolExtractorRegistry.default()
        assert reg.get(".js") is not None

    def test_default_registry_has_java(self):
        reg = SymbolExtractorRegistry.default()
        assert reg.get(".java") is not None

    def test_unknown_ext_returns_none(self):
        reg = SymbolExtractorRegistry.default()
        assert reg.get(".xyz") is None

    def test_case_insensitive(self):
        reg = SymbolExtractorRegistry.default()
        assert reg.get(".PY") is not None

    def test_default_registry_has_rust(self):
        reg = SymbolExtractorRegistry.default()
        assert reg.get(".rs") is not None


# ===========================================================================
# Rust
# ===========================================================================

@pytest.fixture(scope="module")
def rust_parser():
    return RustImportParser()


def parse_rust(rust_parser, src: str):
    return rust_parser.parse_file("test.rs", src)


class TestRustImportParser:
    def test_std_system(self, rust_parser):
        imports = parse_rust(rust_parser, "use std::collections::HashMap;")
        assert len(imports) == 1
        assert imports[0].imported_name == "std"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_core_system(self, rust_parser):
        imports = parse_rust(rust_parser, "use core::fmt::Display;")
        assert imports[0].imported_name == "core"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_alloc_system(self, rust_parser):
        imports = parse_rust(rust_parser, "use alloc::vec::Vec;")
        assert imports[0].import_type == ImportType.SYSTEM

    def test_crate_local(self, rust_parser):
        imports = parse_rust(rust_parser, "use crate::config::Settings;")
        assert imports[0].imported_name == "crate"
        assert imports[0].import_type == ImportType.LOCAL

    def test_super_local(self, rust_parser):
        imports = parse_rust(rust_parser, "use super::utils::helper;")
        assert imports[0].imported_name == "super"
        assert imports[0].import_type == ImportType.LOCAL

    def test_self_local(self, rust_parser):
        imports = parse_rust(rust_parser, "use self::foo;")
        assert imports[0].imported_name == "self"
        assert imports[0].import_type == ImportType.LOCAL

    def test_external_crate(self, rust_parser):
        imports = parse_rust(rust_parser, "use serde::Deserialize;")
        assert imports[0].imported_name == "serde"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_brace_list(self, rust_parser):
        imports = parse_rust(rust_parser, "use serde::{Deserialize, Serialize};")
        # At least one import for serde
        names = [i.imported_name for i in imports]
        assert "serde" in names
        for imp in imports:
            assert imp.import_type == ImportType.EXTERNAL

    def test_mixed_brace_list(self, rust_parser):
        imports = parse_rust(rust_parser, "use std::io::{self, Read};")
        names = [i.imported_name for i in imports]
        assert "std" in names
        for imp in imports:
            assert imp.import_type == ImportType.SYSTEM

    def test_wildcard(self, rust_parser):
        imports = parse_rust(rust_parser, "use log::*;")
        assert imports[0].imported_name == "log"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_as_alias(self, rust_parser):
        imports = parse_rust(rust_parser, "use std::io as stdio;")
        assert imports[0].imported_name == "std"
        assert imports[0].import_type == ImportType.SYSTEM

    def test_extern_crate_external(self, rust_parser):
        imports = parse_rust(rust_parser, "extern crate serde;")
        assert imports[0].imported_name == "serde"
        assert imports[0].import_type == ImportType.EXTERNAL

    def test_extern_crate_std(self, rust_parser):
        imports = parse_rust(rust_parser, "extern crate std;")
        assert imports[0].import_type == ImportType.SYSTEM

    def test_line_number(self, rust_parser):
        src = "\nuse serde::Deserialize;\n"
        imports = parse_rust(rust_parser, src)
        assert imports[0].line_number == 2

    def test_empty_file(self, rust_parser):
        assert parse_rust(rust_parser, "") == []

    def test_no_use_statements(self, rust_parser):
        assert parse_rust(rust_parser, "fn main() {}") == []

    def test_multiple_use_statements(self, rust_parser):
        src = (
            "use std::collections::HashMap;\n"
            "use crate::config::Settings;\n"
            "use serde::Deserialize;\n"
        )
        imports = parse_rust(rust_parser, src)
        assert len(imports) == 3
        types = [i.import_type for i in imports]
        assert ImportType.SYSTEM in types
        assert ImportType.LOCAL in types
        assert ImportType.EXTERNAL in types

    def test_supported_extensions(self, rust_parser):
        assert ".rs" in rust_parser.get_supported_extensions()

    def test_fixture_sample_rs(self):
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "lang" / "sample.rs"
        content = fixture.read_text()
        parser = RustImportParser()
        imports = parser.parse_file("sample.rs", content)
        names = [i.imported_name for i in imports]
        assert "std" in names
        assert "core" in names
        assert "crate" in names
        assert "super" in names
        assert "serde" in names
        assert "tokio" in names
        assert "log" in names


@pytest.fixture(scope="module")
def rust_sym():
    return RustSymbolExtractor()


def rust_extract(extractor, src: str):
    return extractor.extract("test.rs", src)


class TestRustSymbolExtractor:
    def test_pub_struct(self, rust_sym):
        symbols = rust_extract(rust_sym, "pub struct Foo { x: i32 }")
        assert len(symbols) == 1
        assert symbols[0].name == "Foo"
        assert symbols[0].kind == "class"
        assert symbols[0].is_exported is True

    def test_private_struct_not_exported(self, rust_sym):
        symbols = rust_extract(rust_sym, "struct Bar { x: i32 }")
        assert symbols[0].name == "Bar"
        assert symbols[0].is_exported is False

    def test_pub_enum(self, rust_sym):
        symbols = rust_extract(rust_sym, "pub enum Status { Active, Inactive }")
        assert symbols[0].name == "Status"
        assert symbols[0].kind == "class"
        assert symbols[0].is_exported is True

    def test_pub_trait(self, rust_sym):
        symbols = rust_extract(rust_sym, "pub trait Runnable { fn run(&self); }")
        assert symbols[0].name == "Runnable"
        assert symbols[0].kind == "interface"
        assert symbols[0].is_exported is True

    def test_pub_fn(self, rust_sym):
        symbols = rust_extract(rust_sym, "pub fn run() {}")
        assert symbols[0].name == "run"
        assert symbols[0].kind == "function"
        assert symbols[0].is_exported is True

    def test_private_fn_not_exported(self, rust_sym):
        symbols = rust_extract(rust_sym, "fn helper() {}")
        assert symbols[0].name == "helper"
        assert symbols[0].is_exported is False

    def test_impl_methods(self, rust_sym):
        src = (
            "pub struct Foo {}\n"
            "impl Foo {\n"
            "    pub fn new() -> Self { Foo {} }\n"
            "    fn private_method(&self) {}\n"
            "}\n"
        )
        symbols = rust_extract(rust_sym, src)
        names = {s.name: s for s in symbols}
        assert "Foo" in names
        assert "new" in names
        assert "private_method" in names
        assert names["new"].kind == "method"
        assert names["new"].is_exported is True
        assert names["private_method"].is_exported is False

    def test_line_numbers(self, rust_sym):
        src = "pub fn foo() {}\n\npub fn bar() {}\n"
        symbols = rust_extract(rust_sym, src)
        assert symbols[0].start_line == 1
        assert symbols[1].start_line == 3

    def test_file_id_propagated(self, rust_sym):
        symbols = rust_extract(rust_sym, "pub fn foo() {}")
        assert symbols[0].file_id == "test.rs"

    def test_id_placeholder_empty(self, rust_sym):
        symbols = rust_extract(rust_sym, "pub fn foo() {}")
        assert symbols[0].id == ""

    def test_empty_file(self, rust_sym):
        assert rust_extract(rust_sym, "") == []

    def test_supported_extensions(self, rust_sym):
        assert ".rs" in rust_sym.get_supported_extensions()

    def test_fixture_sample_rs(self):
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "lang" / "sample.rs"
        content = fixture.read_text()
        extractor = RustSymbolExtractor()
        symbols = extractor.extract("sample.rs", content)
        names = {s.name for s in symbols}
        assert "Parser" in names
        assert "Status" in names
        assert "Processable" in names
        assert "run" in names
        # impl methods
        assert "new" in names
        assert "parse" in names
        # pub items are exported
        exported = {s.name for s in symbols if s.is_exported}
        assert "Parser" in exported
        assert "run" in exported
        # private items not exported
        not_exported = {s.name for s in symbols if not s.is_exported}
        assert "Internal" in not_exported
        assert "private_helper" in not_exported


@pytest.fixture(scope="module")
def c_sym():
    return CSymbolExtractor()


def c_extract(extractor, src: str, filename: str = "test.c"):
    return extractor.extract(filename, src)


class TestCSymbolExtractor:
    def test_c_function(self, c_sym):
        symbols = c_extract(c_sym, "int add(int a, int b) { return a + b; }")
        assert len(symbols) == 1
        assert symbols[0].name == "add"
        assert symbols[0].kind == "function"
        assert symbols[0].is_exported is True

    def test_c_static_function_not_exported(self, c_sym):
        symbols = c_extract(c_sym, "static int helper(int x) { return x; }")
        assert len(symbols) == 1
        assert symbols[0].name == "helper"
        assert symbols[0].is_exported is False

    def test_c_named_struct(self, c_sym):
        symbols = c_extract(c_sym, "struct Node { int value; struct Node *next; };")
        assert any(s.name == "Node" and s.kind == "class" for s in symbols)

    def test_c_named_enum(self, c_sym):
        symbols = c_extract(c_sym, "enum Color { RED, GREEN, BLUE };")
        assert any(s.name == "Color" and s.kind == "class" for s in symbols)

    def test_c_anonymous_struct_skipped(self, c_sym):
        symbols = c_extract(c_sym, "typedef struct { int x; } Point;")
        names = {s.name for s in symbols}
        assert "Point" not in names  # anonymous struct has no name field

    def test_cpp_class(self, c_sym):
        src = "class Greeter { public: void greet() {} };"
        symbols = c_extract(c_sym, src, filename="test.cpp")
        names = {s.name for s in symbols}
        assert "Greeter" in names
        assert any(s.name == "Greeter" and s.kind == "class" for s in symbols)

    def test_cpp_class_methods_extracted(self, c_sym):
        src = "class Foo { public: void run() {} void stop() {} };"
        symbols = c_extract(c_sym, src, filename="test.cpp")
        names = {s.name for s in symbols}
        assert "run" in names
        assert "stop" in names
        assert any(s.name == "run" and s.kind == "method" for s in symbols)

    def test_cpp_namespace_recurse(self, c_sym):
        src = "namespace demo { void helper() {} }"
        symbols = c_extract(c_sym, src, filename="test.cpp")
        assert any(s.name == "helper" for s in symbols)

    def test_line_numbers(self, c_sym):
        src = "int foo() {}\n\nint bar() {}\n"
        symbols = c_extract(c_sym, src)
        by_name = {s.name: s for s in symbols}
        assert by_name["foo"].start_line == 1
        assert by_name["bar"].start_line == 3

    def test_file_id_propagated(self, c_sym):
        symbols = c_extract(c_sym, "int foo() {}", filename="myfile.c")
        assert symbols[0].file_id == "myfile.c"

    def test_id_placeholder_empty(self, c_sym):
        symbols = c_extract(c_sym, "int foo() {}")
        assert symbols[0].id == ""

    def test_empty_file(self, c_sym):
        assert c_extract(c_sym, "") == []

    def test_supported_extensions(self, c_sym):
        exts = c_sym.get_supported_extensions()
        for ext in (".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"):
            assert ext in exts

    def test_registry_includes_c(self):
        reg = SymbolExtractorRegistry.default()
        assert reg.get(".c") is not None
        assert reg.get(".cpp") is not None
        assert reg.get(".h") is not None

    def test_fixture_sample_c(self):
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "lang" / "sample.c"
        content = fixture.read_text()
        extractor = CSymbolExtractor()
        symbols = extractor.extract("sample.c", content)
        names = {s.name for s in symbols}
        assert "add" in names
        assert "main" in names
        assert "Node" in names
        assert "Color" in names
        exported = {s.name for s in symbols if s.is_exported}
        assert "add" in exported
        assert "main" in exported
        not_exported = {s.name for s in symbols if not s.is_exported}
        assert "internal_helper" in not_exported

    def test_fixture_sample_cpp(self):
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "lang" / "sample.cpp"
        content = fixture.read_text()
        extractor = CSymbolExtractor()
        symbols = extractor.extract("sample.cpp", content)
        names = {s.name for s in symbols}
        assert "Greeter" in names
        assert "greet" in names
        assert "reset" in names
        assert "Point" in names
        assert "make_greeting" in names
        not_exported = {s.name for s in symbols if not s.is_exported}
        assert "file_local" in not_exported
