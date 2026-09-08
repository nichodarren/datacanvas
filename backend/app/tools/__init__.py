"""The tool catalogue (§11.4).

Importing this package is what registers every tool. The decorator in
``contract`` runs at import time, so a tool in a module nobody imports is a tool
that does not exist — which is why the imports below are eager and explicit
rather than a directory scan. A scan would register whatever happened to be on
disk; this registers what somebody decided to ship.
"""

from __future__ import annotations

from app.tools.aggregate import Aggregate
from app.tools.bin_column import BinColumn
from app.tools.cardinality import CardinalityReport
from app.tools.contract import (
    REGISTRY,
    Registration,
    Tool,
    ToolError,
    ToolRegistry,
    UnknownTool,
)
from app.tools.crosstab import Crosstab
from app.tools.derive_column import DeriveColumn
from app.tools.describe import DescribeDataset
from app.tools.duplicates import DuplicateReport
from app.tools.filter_rows import FilterRows
from app.tools.limit_rows import LimitRows
from app.tools.missingness import MissingnessReport
from app.tools.outliers import OutlierScan
from app.tools.plot import Plot
from app.tools.profile_column import ProfileColumn
from app.tools.runner import ToolRunner
from app.tools.sample_rows import SampleRows
from app.tools.select_columns import SelectColumns
from app.tools.sort_rows import SortRows
from app.tools.type_consistency import TypeConsistencyReport

__all__ = [
    "REGISTRY",
    "Aggregate",
    "BinColumn",
    "CardinalityReport",
    "Crosstab",
    "DeriveColumn",
    "DescribeDataset",
    "DuplicateReport",
    "FilterRows",
    "LimitRows",
    "MissingnessReport",
    "OutlierScan",
    "Plot",
    "ProfileColumn",
    "Registration",
    "SampleRows",
    "SelectColumns",
    "SortRows",
    "Tool",
    "ToolError",
    "ToolRegistry",
    "ToolRunner",
    "TypeConsistencyReport",
    "UnknownTool",
]
