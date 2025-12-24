from redress.classify import default_classifier
from redress.cli import lint_retry_config, lint_retry_policy, main
from redress.config import RetryConfig
from redress.policy import RetryPolicy
from redress.strategies import decorrelated_jitter


def test_lint_retry_config_surfaces_errors() -> None:
    cfg = RetryConfig(deadline_s=0, max_attempts=0, max_unknown_attempts=-1)

    errors, warnings = lint_retry_config(cfg)

    assert any("deadline_s" in msg for msg in errors)
    assert any("max_attempts" in msg for msg in errors)
    assert any("max_unknown_attempts" in msg for msg in errors)
    assert any("strategy" in msg for msg in errors)
    assert warnings == []


def test_lint_retry_policy_ok() -> None:
    policy = RetryPolicy(
        classifier=default_classifier,
        strategy=decorrelated_jitter(max_s=1.0),
        max_attempts=3,
        deadline_s=5.0,
    )

    errors, warnings = lint_retry_policy(policy)

    assert errors == []
    assert warnings == []


def test_doctor_main_lints_importable_config(tmp_path, monkeypatch, capsys) -> None:
    module_path = tmp_path / "app_cfg.py"
    module_path.write_text(
        "from redress import RetryConfig\n"
        "from redress.strategies import decorrelated_jitter\n"
        "config = RetryConfig(default_strategy=decorrelated_jitter(max_s=1.0))\n"
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    exit_code = main(["doctor", "app_cfg:config", "--show"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "passed config checks" in out
    assert "Config snapshot" in out
    assert "max_attempts" in out


def test_lint_retry_config_warns_when_unknown_exceeds_max_attempts() -> None:
    cfg = RetryConfig(
        max_attempts=1,
        max_unknown_attempts=5,
        default_strategy=decorrelated_jitter(),
    )

    errors, warnings = lint_retry_config(cfg)

    assert errors == []
    assert any("exceeds max_attempts" in msg for msg in warnings)


def test_lint_retry_config_validates_class_keys_and_limits() -> None:
    cfg = RetryConfig(
        default_strategy=decorrelated_jitter(),
        class_strategies={"not-an-error-class": lambda *_: 0.0},
        per_class_max_attempts={"wrong-key": 0},
    )

    errors, _ = lint_retry_config(cfg)

    # Both the wrong key type and the limit < 1 should be reported.
    assert any("class_strategies keys must be ErrorClass" in msg for msg in errors)
    assert any("per_class_max_attempts" in msg for msg in errors)


def test_doctor_handles_missing_attribute(tmp_path, monkeypatch, capsys) -> None:
    module_path = tmp_path / "app_cfg.py"
    module_path.write_text("x = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    exit_code = main(["doctor", "app_cfg:missing"])

    assert exit_code == 1
    assert "Could not find attribute" in capsys.readouterr().out


def test_doctor_handles_wrong_object_type(tmp_path, monkeypatch, capsys) -> None:
    module_path = tmp_path / "bad_cfg.py"
    module_path.write_text("config = 123\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    exit_code = main(["doctor", "bad_cfg:config"])

    assert exit_code == 1
    assert "Expected RetryConfig" in capsys.readouterr().out


def test_doctor_show_covers_class_strategies_and_limits(tmp_path, monkeypatch, capsys) -> None:
    module_path = tmp_path / "detailed_cfg.py"
    module_path.write_text(
        "from redress import RetryConfig, ErrorClass\n"
        "from redress.strategies import decorrelated_jitter\n"
        "config = RetryConfig(\n"
        "    default_strategy=decorrelated_jitter(max_s=1.0),\n"
        "    class_strategies={ErrorClass.RATE_LIMIT: decorrelated_jitter(max_s=2.0)},\n"
        "    per_class_max_attempts={ErrorClass.RATE_LIMIT: 2},\n"
        ")\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    exit_code = main(["doctor", "detailed_cfg:config", "--show"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "RATE_LIMIT" in out
    assert "2" in out
