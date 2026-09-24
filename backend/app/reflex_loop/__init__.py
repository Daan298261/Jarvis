"""RFC-0172 Reflex-first browser/computer-use fast loop.

Produces atomic ActionFrames, asks the RFC-0171 Reflex Lane for one typed
operation+target decision, executes only by frame-local target id, and verifies
postconditions. Does not own System One providers (see app.decision / RFC-0171).
"""

from .benchmark import LoopMetrics, compare_loops, run_benchmark_suite
from .executor import ReflexLoopExecutor, ReflexLoopResult
from .reflex_client import (
    DecisionClass,
    DecisionQuestion,
    DecisionResult,
    ReflexDecideClient,
    get_reflex_decide_client,
)
from .schema import (
    ActionFrame,
    ActionNode,
    Geometry,
    NodeState,
    Operation,
    ReflexDecision,
    SurfaceKind,
)

__all__ = [
    "ActionFrame",
    "ActionNode",
    "DecisionClass",
    "DecisionQuestion",
    "DecisionResult",
    "Geometry",
    "LoopMetrics",
    "NodeState",
    "Operation",
    "ReflexDecideClient",
    "ReflexDecision",
    "ReflexLoopExecutor",
    "ReflexLoopResult",
    "SurfaceKind",
    "compare_loops",
    "get_reflex_decide_client",
    "run_benchmark_suite",
]
