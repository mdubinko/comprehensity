"""Sample Python module used as a parser test fixture.

Covers: import, import-as, from-import, from-import-multi, relative imports,
        multi-line parenthesised imports, __future__, stdlib, and external deps.
"""
from __future__ import annotations

import os
import sys
import os.path
import collections as col

from pathlib import Path, PurePath
from collections import (
    OrderedDict,
    defaultdict,
)

import numpy
import numpy as np
from numpy import array

from . import utils
from .. import sibling
from ..sibling import helper


def main() -> None:
    print(Path.cwd())
