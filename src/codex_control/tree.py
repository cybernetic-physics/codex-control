"""Fork-based tree search.

Builds on ``thread/fork`` as the branching primitive — each child
inherits the parent's full conversation history at fork time and gets
its own turn(s) from there. This is materially better than ad-hoc
workspace-snapshot search because:

1. The branching is *first-class* — one RPC, no on-disk diffing.
2. Children share in-memory context with the parent, so re-prompting
   from scratch isn't necessary.
3. The same physical app-server process runs every branch concurrently.

The :class:`Node` dataclass is a minimal tree node; :func:`expand` adds
one child to a node; :func:`fork_tree_search` puts the two together for
PUCT-style exploration. For a full RL trainer you'll subclass / replace
the selection and value functions, but the plumbing here is what every
fork-based search needs.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
import uuid
from typing import Any, Awaitable, Callable, Optional, Sequence, TYPE_CHECKING

from .protocol.types import Item, Turn

if TYPE_CHECKING:
    from .thread import Thread

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Node:
    """One node in a fork-based search tree."""

    node_id: str
    thread: "Thread"
    parent_id: Optional[str]
    depth: int
    prompt: str
    turn: Optional[Turn] = None
    value: float = 0.0
    visits: int = 1
    children: list["Node"] = dataclasses.field(default_factory=list)

    @property
    def final_text(self) -> str:
        return self.turn.final_text if self.turn is not None else ""

    @property
    def items(self) -> list[Item]:
        return self.turn.items if self.turn is not None else []


# Value function: turn -> float. Pure, side-effect-free.
ValueFn = Callable[[Turn], float]

# Async expansion function: given a parent node and a payload, run a
# turn on the forked child and return the new Node.
ExpansionFn = Callable[..., Awaitable[Node]]


# -----------------------------------------------------------------------
# Expansion
# -----------------------------------------------------------------------

async def expand(
    parent: Node,
    prompt: str,
    *,
    value_fn: ValueFn,
    cwd: Optional[str] = None,
    approval_policy: str = "never",
    effort: str = "low",
    timeout: float = 120.0,
    ephemeral: bool = True,
) -> Node:
    """Fork ``parent`` and run one turn on the child with ``prompt``."""
    child_thread = await parent.thread.fork(ephemeral=ephemeral)
    turn = await child_thread.run_turn(
        prompt,
        cwd=cwd,
        approval_policy=approval_policy,
        effort=effort,
        timeout=timeout,
    )
    node = Node(
        node_id=f"n-{uuid.uuid4().hex[:6]}",
        thread=child_thread,
        parent_id=parent.node_id,
        depth=parent.depth + 1,
        prompt=prompt,
        turn=turn,
        value=value_fn(turn),
    )
    parent.children.append(node)
    return node


async def expand_all(
    parent: Node,
    prompts: Sequence[str],
    *,
    value_fn: ValueFn,
    cwd: Optional[str] = None,
    approval_policy: str = "never",
    effort: str = "low",
    timeout: float = 120.0,
    ephemeral: bool = True,
) -> list[Node]:
    """Concurrently fork ``parent`` once per prompt and run each child's turn."""
    return await asyncio.gather(
        *(
            expand(
                parent, p,
                value_fn=value_fn,
                cwd=cwd,
                approval_policy=approval_policy,
                effort=effort,
                timeout=timeout,
                ephemeral=ephemeral,
            )
            for p in prompts
        )
    )


# -----------------------------------------------------------------------
# Selection
# -----------------------------------------------------------------------

def select_uct(
    nodes: Sequence[Node],
    *,
    parent_visits: int,
    c: float = 1.4142,
) -> Node:
    """Return the child with the highest UCB score.

    Standard PUCT-style formula:
    ``ucb = value + c * sqrt(ln(parent_visits) / (1 + visits))``.
    Falls back to ``max(value)`` when ``parent_visits == 0``.
    """
    if not nodes:
        raise ValueError("select_uct requires at least one node")
    if parent_visits <= 0:
        return max(nodes, key=lambda n: n.value)
    log_n = math.log(max(1, parent_visits))
    return max(
        nodes,
        key=lambda n: n.value + c * math.sqrt(log_n / (1 + n.visits)),
    )


# -----------------------------------------------------------------------
# Search
# -----------------------------------------------------------------------

async def fork_tree_search(
    root: Node,
    *,
    branch_prompts_fn: Callable[[Node], Sequence[str]],
    value_fn: ValueFn,
    depth: int,
    branch_factor: int,
    cwd: Optional[str] = None,
    approval_policy: str = "never",
    effort: str = "low",
    timeout: float = 120.0,
) -> Node:
    """Run a depth-bounded fork-based search rooted at ``root``.

    At each level we (i) pick the best leaf so far by
    :func:`select_uct`, (ii) ask the user-supplied ``branch_prompts_fn``
    for up to ``branch_factor`` prompts, (iii) expand all children
    concurrently. Returns the root with children attached.

    For real PUCT loops you typically run more sophisticated selection
    (e.g. weight by visits and use a learned value head) — replace this
    function in that case and reuse :func:`expand` directly.
    """
    frontier: list[Node] = [root]
    for _depth_step in range(depth):
        if not frontier:
            break
        best = select_uct(frontier, parent_visits=root.visits)
        prompts = list(branch_prompts_fn(best))[:branch_factor]
        if not prompts:
            continue
        children = await expand_all(
            best, prompts,
            value_fn=value_fn,
            cwd=cwd,
            approval_policy=approval_policy,
            effort=effort,
            timeout=timeout,
        )
        best.visits += 1
        frontier = list({n.node_id: n for n in frontier + children}.values())
    return root


# -----------------------------------------------------------------------
# Default value heuristics
# -----------------------------------------------------------------------

def length_value(turn: Turn, *, peak: int = 250, span: int = 600) -> float:
    """Stub value: prefer answers of moderate length, zero for empties.

    Useful for smoke tests; replace with a real verifier-driven value
    function in production.
    """
    n = len(turn.final_text.strip())
    if n == 0:
        return 0.0
    return max(0.0, 1.0 - abs(n - peak) / span)
