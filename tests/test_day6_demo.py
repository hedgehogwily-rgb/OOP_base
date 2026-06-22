from pathlib import Path

from src.main import run_day6_demo
from src.models import TransactionStatus


def test_run_day6_demo_completes_without_error() -> None:
    result = run_day6_demo()

    assert result["clients"] == 7
    assert result["accounts"] == 12
    assert result["transactions"] >= 30
    assert result["stats"].get("completed", 0) >= 1
    assert result["stats"].get("failed", 0) >= 1
    assert result["suspicious_count"] >= 1
    assert len(result["ranking"]) == 3
    assert result["total_balance"] > 0
    assert result["delayed_tx_status"] == TransactionStatus.COMPLETED
    assert all(
        status == TransactionStatus.FAILED for status in result["night_tx_statuses"]
    )


def test_run_day6_demo_writes_audit_log(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.log"
    result = run_day6_demo(audit_log_path=str(audit_path))

    assert result["transactions"] >= 30
    assert audit_path.exists()
    assert audit_path.read_text(encoding="utf-8").strip()
