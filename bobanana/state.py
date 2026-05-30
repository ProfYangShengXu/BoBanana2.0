"""Shared data models and the LangGraph state definition."""

from __future__ import annotations

from typing import Annotated, List, Optional, TypedDict

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """A single actionable step in the plan."""

    id: int
    description: str
    done: bool = False
    result: Optional[str] = None


class Plan(BaseModel):
    """Structured plan produced/revised by the planner agent."""

    summary: str = Field(description="One-line statement of the overall approach.")
    steps: List[PlanStep] = Field(default_factory=list)
    key_directives: List[str] = Field(
        default_factory=list,
        description="Task-level hard requirements that MUST all be satisfied before the "
                    "task can finish (verifiable acceptance criteria, e.g. 'files actually "
                    "written', 'build succeeds with output'). Completing individual steps "
                    "does NOT end the task until every directive here is met.",
    )


class DirectiveCheck(BaseModel):
    """Verdict on whether the plan's key_directives are all satisfied."""

    all_satisfied: bool = Field(description="True only if every key directive is met.")
    unmet: List[str] = Field(
        default_factory=list,
        description="Directives not yet satisfied, each phrased as a concrete remaining action.",
    )
    notes: str = Field(default="", description="Short reasoning for the verdict.")


class ReviewResult(BaseModel):
    """A reviewer agent's structured verdict on a plan or a written artifact."""

    approved: bool = Field(description="True if the artifact is good enough to proceed.")
    score: int = Field(default=0, description="Quality score 0-10.")
    suggestions: List[str] = Field(
        default_factory=list,
        description="Concrete, actionable improvement suggestions.",
    )
    rationale: str = Field(default="", description="Short reasoning for the verdict.")


class TaskTriage(BaseModel):
    """Meta-prompting verdict on an incoming user task."""

    needs_clarification: bool = Field(
        description="True if the request is too unclear/ambiguous to start safely."
    )
    questions: List[str] = Field(
        default_factory=list,
        description="Clarifying questions to ask the user (only if needs_clarification).",
    )
    refined_request: str = Field(
        default="",
        description="A clearer, more complete restatement of the task to execute.",
    )
    assessment: str = Field(
        default="",
        description="Short note on scope/complexity and why clarification is or isn't needed.",
    )


class Intent(BaseModel):
    """Intent-layer classification of an incoming user message."""

    task_size: float = Field(
        description="Estimated scope on a 0.0-1.0 scale: 0.0 = greeting/chit-chat, "
                    "0.1 = trivial Q&A, 0.5 = normal feature/bugfix, 0.62 = multi-step "
                    "research/search+report, 1.0 = large multi-module refactor."
    )
    is_code_task: bool = Field(
        default=True,
        description="True if it requires tools: files, shell, web search/fetch, or deliverables.",
    )
    needs_metaprompt: bool = Field(
        default=False,
        description="True if the request is ambiguous/large enough that clarifying or "
                    "refining it first would materially help.",
    )
    reason: str = Field(default="", description="One-line justification.")


def _append(old: list, new):
    """Reducer: append item(s) to a list channel."""
    old = old or []
    if isinstance(new, list):
        return old + new
    return old + [new]


class AgentState(TypedDict, total=False):
    """The state threaded through the LangGraph workflow."""

    user_request: str
    plan: dict  # serialized Plan
    plan_review: dict  # serialized ReviewResult
    plan_revisions: int
    plan_validation: dict  # serialized PlanValidation.report fields
    plan_validation_errors: list  # str messages for planner revision
    prior_plan_step_count: int  # detect plan bloat on revision

    current_step: int
    step_output: str
    exec_review: dict  # serialized ReviewResult
    exec_revisions: int
    directive_revisions: int  # times we've looped back to satisfy unmet key_directives
    directive_check: dict  # serialized DirectiveCheck (last gate verdict)
    directive_loop: bool  # gate decision: loop back to execute vs proceed to finalize

    # Steps that were advanced WITHOUT passing review (budget exhausted) — never
    # silently treated as success; surfaced honestly in the final result.
    failed_steps: List[dict]

    # Adaptive difficulty: starts from the intent's task_size and ratchets up on
    # review rejections / replans, which raises the per-step tool/step budget.
    difficulty: float
    tool_iter_bonus: int  # extra per-step ReAct iterations granted as difficulty rises
    step_bonus: int       # extra plan steps allowed (e.g. after a replan)

    # Interruption (task timeout or user Ctrl-C). When set, the run paused and is
    # awaiting the user; the checkpoint remains resumable.
    interrupted: bool
    interrupt_reason: str  # "timeout" | "user" | ""

    # Running log of human-readable events for the TUI
    events: Annotated[List[dict], _append]

    final_answer: str
    status: str  # "completed" | "partial"
    done: bool


def new_state(user_request: str, difficulty: float = 0.5) -> AgentState:
    return {
        "user_request": user_request,
        "plan": {},
        "plan_review": {},
        "plan_revisions": 0,
        "plan_validation": {},
        "plan_validation_errors": [],
        "prior_plan_step_count": 0,
        "current_step": 0,
        "step_output": "",
        "exec_review": {},
        "exec_revisions": 0,
        "directive_revisions": 0,
        "failed_steps": [],
        "difficulty": max(0.0, min(1.0, float(difficulty))),
        "tool_iter_bonus": 0,
        "step_bonus": 0,
        "interrupted": False,
        "interrupt_reason": "",
        "events": [],
        "final_answer": "",
        "status": "completed",
        "done": False,
    }
