from __future__ import annotations

import argparse
import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .config import RetryConfig
from .errors import ErrorClass
from .policy import AsyncRetryPolicy, RetryPolicy
from .strategies import StrategyFn


@dataclass
class _ConfigView:
    source: str
    deadline_s: float
    max_attempts: int
    max_unknown_attempts: int | None
    per_class_max_attempts: Mapping[Any, int] | None
    default_strategy: StrategyFn | None
    class_strategies: Mapping[Any, StrategyFn] | None


def _config_view_from_obj(obj: object, *, source: str) -> _ConfigView:
    if isinstance(obj, RetryConfig):
        return _ConfigView(
            source=source,
            deadline_s=obj.deadline_s,
            max_attempts=obj.max_attempts,
            max_unknown_attempts=obj.max_unknown_attempts,
            per_class_max_attempts=obj.per_class_max_attempts,
            default_strategy=obj.default_strategy,
            class_strategies=obj.class_strategies,
        )

    if isinstance(obj, RetryPolicy | AsyncRetryPolicy):
        return _ConfigView(
            source=source,
            deadline_s=obj.deadline.total_seconds(),
            max_attempts=obj.max_attempts,
            max_unknown_attempts=obj.max_unknown_attempts,
            per_class_max_attempts=obj.per_class_max_attempts,
            default_strategy=obj._default_strategy,
            class_strategies=obj._strategies,
        )

    raise TypeError(
        f"Expected RetryConfig, RetryPolicy, or AsyncRetryPolicy, got {type(obj).__name__}"
    )


def _lint_config_view(cfg: _ConfigView) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if cfg.deadline_s <= 0:
        errors.append(f"[{cfg.source}] deadline_s must be > 0 (got {cfg.deadline_s!r})")

    if cfg.max_attempts < 1:
        errors.append(f"[{cfg.source}] max_attempts must be >= 1 (got {cfg.max_attempts!r})")

    if cfg.max_unknown_attempts is not None and cfg.max_unknown_attempts < 0:
        errors.append(
            f"[{cfg.source}] max_unknown_attempts must be >= 0 or None "
            f"(got {cfg.max_unknown_attempts!r})"
        )

    if cfg.max_unknown_attempts is not None and cfg.max_unknown_attempts > cfg.max_attempts:
        warnings.append(
            f"[{cfg.source}] max_unknown_attempts ({cfg.max_unknown_attempts}) exceeds "
            f"max_attempts ({cfg.max_attempts}) so it will never trigger."
        )

    if cfg.default_strategy is not None and not callable(cfg.default_strategy):
        errors.append(f"[{cfg.source}] default_strategy must be callable.")

    if cfg.class_strategies:
        for klass, strategy in cfg.class_strategies.items():
            if not isinstance(klass, ErrorClass):
                errors.append(
                    f"[{cfg.source}] class_strategies keys must be ErrorClass values "
                    f"(got {klass!r})"
                )
            if not callable(strategy):
                errors.append(
                    f"[{cfg.source}] strategy for {getattr(klass, 'name', klass)!r} "
                    f"is not callable."
                )

    if cfg.per_class_max_attempts:
        for klass, limit in cfg.per_class_max_attempts.items():
            if not isinstance(klass, ErrorClass):
                errors.append(
                    f"[{cfg.source}] per_class_max_attempts keys must be ErrorClass values "
                    f"(got {klass!r})"
                )
            if limit < 1:
                errors.append(
                    f"[{cfg.source}] per_class_max_attempts for "
                    f"{getattr(klass, 'name', klass)!r} must be >= 1 (got {limit!r})"
                )

    has_default = cfg.default_strategy is not None
    has_class_strategies = bool(cfg.class_strategies)
    if not (has_default or has_class_strategies):
        errors.append(
            f"[{cfg.source}] configure at least one backoff strategy "
            f"(default_strategy or class_strategies)."
        )

    return errors, warnings


def _format_strategy(strategy: StrategyFn | None) -> str:
    if strategy is None:
        return "None"
    name = getattr(strategy, "__qualname__", None) or getattr(strategy, "__name__", None)
    module = getattr(strategy, "__module__", None)
    if module and name:
        return f"{module}.{name}"
    return repr(strategy)


def _format_class(klass: object) -> str:
    if isinstance(klass, ErrorClass):
        return klass.name
    return repr(klass)


def _print_snapshot(view: _ConfigView) -> None:
    print("Config snapshot:")
    print(f"  source: {view.source}")
    print(f"  deadline_s: {view.deadline_s}")
    print(f"  max_attempts: {view.max_attempts}")
    print(f"  max_unknown_attempts: {view.max_unknown_attempts}")
    print(f"  default_strategy: {_format_strategy(view.default_strategy)}")

    print("  class_strategies:")
    if view.class_strategies:
        for klass, strategy in sorted(
            view.class_strategies.items(), key=lambda kv: _format_class(kv[0])
        ):
            print(f"    {_format_class(klass)}: {_format_strategy(strategy)}")
    else:
        print("    (none)")

    print("  per_class_max_attempts:")
    if view.per_class_max_attempts:
        for klass, limit in sorted(
            view.per_class_max_attempts.items(), key=lambda kv: _format_class(kv[0])
        ):
            print(f"    {_format_class(klass)}: {limit}")
    else:
        print("    (none)")


def lint_retry_config(config: RetryConfig) -> tuple[list[str], list[str]]:
    """
    Lint a RetryConfig instance and return (errors, warnings).
    """
    view = _config_view_from_obj(config, source="config")
    return _lint_config_view(view)


def lint_retry_policy(policy: RetryPolicy | AsyncRetryPolicy) -> tuple[list[str], list[str]]:
    """
    Lint a RetryPolicy or AsyncRetryPolicy instance and return (errors, warnings).
    """
    view = _config_view_from_obj(policy, source="policy")
    return _lint_config_view(view)


def _load_target(target: str) -> object:
    module_path, _, attr = target.partition(":")
    if not module_path:
        raise ValueError("doctor target must be in the form module:attribute (e.g. app.config:cfg)")

    module = importlib.import_module(module_path)
    attr_name = attr or "config"
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        raise AttributeError(
            f"Could not find attribute {attr_name!r} on module {module_path!r}"
        ) from exc


def _run_doctor(target: str, *, show: bool) -> int:
    try:
        obj = _load_target(target)
        view = _config_view_from_obj(obj, source=target)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: {exc}")
        return 1

    errors, warnings = _lint_config_view(view)

    if show:
        _print_snapshot(view)

    for msg in warnings:
        print(f"warning: {msg}")

    if errors:
        for msg in errors:
            print(f"error: {msg}")
        return 1

    print(f"OK: {target!r} passed config checks.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="redress",
        description="Utility CLI for redress. Use 'redress doctor module:attr' to lint configs.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Lint a RetryConfig/RetryPolicy object.")
    doctor.add_argument(
        "target",
        help="Python import path in the form module:attribute pointing to a RetryConfig, "
        "RetryPolicy, or AsyncRetryPolicy instance.",
    )
    doctor.add_argument(
        "--show",
        action="store_true",
        help="Print a normalized snapshot of the config/policy values.",
    )

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _run_doctor(args.target, show=args.show)

    parser.error("Unrecognized command")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
