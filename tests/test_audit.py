import json
from datetime import datetime
from pathlib import Path

from src.models import (
    AuditEvent,
    AuditLevel,
    AuditLog,
    Bank,
    BankAccount,
    Client,
    Currency,
    PremiumAccount,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
)


def _safe_time() -> datetime:
    return datetime(2026, 1, 1, 10, 0, 0)


def _quiet_time() -> datetime:
    return datetime(2026, 1, 1, 2, 0, 0)


def _client(client_id: int, name: str) -> Client:
    return Client(
        name=name,
        surname="Test",
        id=client_id,
        age=25,
        contacts=[f"+7-987-654-32-{client_id:02d}"],
    )


def _setup_bank_and_processor() -> tuple[Bank, TransactionProcessor, str, str]:
    bank = Bank(now_provider=_safe_time)
    queue = TransactionQueue()
    processor = TransactionProcessor(
        bank,
        queue,
        external_transfer_fee_rate=0.03,
        retry_delay_seconds=0,
        now_provider=_safe_time,
    )

    oleg = _client(1, "Oleg")
    ivan = _client(2, "Ivan")
    bank.add_client(oleg)
    bank.add_client(ivan)

    oleg_id = bank.open_account(
        oleg.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    ivan_id = bank.open_account(
        ivan.id,
        PremiumAccount({"name": "Ivan", "surname": "Test"}, currency=Currency.RUB),
    )
    return bank, processor, oleg_id, ivan_id


def _event(
    event_id: str,
    level: AuditLevel,
    event_type: str,
    message: str,
    client_id: int | None = None,
    reasons: list[str] | None = None,
) -> AuditEvent:
    return AuditEvent(
        id=event_id,
        timestamp=_safe_time(),
        level=level,
        event_type=event_type,
        message=message,
        client_id=client_id,
        metadata={"reasons": reasons} if reasons is not None else {},
    )


# --- Юнит-тесты отчётов AuditLog ---


def test_filter_by_level_client_and_event_type() -> None:
    log = AuditLog()
    log.record_event(_event("a", AuditLevel.LOW, "risk_detected", "low", client_id=1))
    log.record_event(
        _event("b", AuditLevel.HIGH, "transaction_blocked", "blocked", client_id=1)
    )
    log.record_event(
        _event("c", AuditLevel.HIGH, "transaction_failed", "failed", client_id=2)
    )

    assert [e.id for e in log.filter(level=AuditLevel.HIGH)] == ["b", "c"]
    assert [e.id for e in log.filter(client_id=1)] == ["a", "b"]
    assert [e.id for e in log.filter(event_type="transaction_failed")] == ["c"]


def test_get_suspicious_operations_returns_only_medium_and_high() -> None:
    log = AuditLog()
    log.record_event(_event("a", AuditLevel.LOW, "risk_detected", "low"))
    log.record_event(_event("b", AuditLevel.MEDIUM, "risk_detected", "medium"))
    log.record_event(_event("c", AuditLevel.HIGH, "transaction_blocked", "high"))

    suspicious = log.get_suspicious_operations()
    assert [e.id for e in suspicious] == ["b", "c"]


def test_get_client_risk_profile_aggregates_counts_and_reasons() -> None:
    log = AuditLog()
    log.record_event(
        _event(
            "a",
            AuditLevel.MEDIUM,
            "risk_detected",
            "m",
            client_id=1,
            reasons=["Большая сумма транзакции"],
        )
    )
    log.record_event(
        _event(
            "b",
            AuditLevel.HIGH,
            "transaction_blocked",
            "h",
            client_id=1,
            reasons=["Большая сумма транзакции"],
        )
    )
    log.record_event(_event("c", AuditLevel.LOW, "risk_detected", "l", client_id=2))

    profile = log.get_client_risk_profile(1)
    assert profile["client_id"] == 1
    assert profile["total_events"] == 2
    assert profile["level_counts"] == {"low": 0, "medium": 1, "high": 1}
    assert profile["event_type_counts"] == {
        "risk_detected": 1,
        "transaction_blocked": 1,
    }
    assert profile["reasons"] == {"Большая сумма транзакции": 2}


def test_get_error_statistics_counts_failures_and_blocks_by_message() -> None:
    log = AuditLog()
    log.record_event(
        _event("a", AuditLevel.MEDIUM, "risk_detected", "Риск-анализ транзакции")
    )
    log.record_event(
        _event("b", AuditLevel.HIGH, "transaction_failed", "Недостаточно средств.")
    )
    log.record_event(
        _event("c", AuditLevel.HIGH, "transaction_failed", "Недостаточно средств.")
    )
    log.record_event(
        _event(
            "d",
            AuditLevel.HIGH,
            "transaction_blocked",
            "Операция заблокирована риск-анализом",
        )
    )

    stats = log.get_error_statistics()
    assert stats == {
        "Недостаточно средств.": 2,
        "Операция заблокирована риск-анализом": 1,
    }


def test_save_to_file_writes_jsonl(tmp_path: Path) -> None:
    file_path = tmp_path / "audit.log"
    log = AuditLog(file_path=str(file_path))
    log.record_event(
        _event("a", AuditLevel.HIGH, "transaction_blocked", "blocked", client_id=1)
    )

    log.save_to_file()

    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["id"] == "a"
    assert payload["level"] == "high"
    assert payload["client_id"] == 1


# --- Интеграционные тесты через TransactionProcessor ---


def test_normal_transfer_succeeds_without_errors() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()
    bank.accounts[oleg_id].deposit(1000)

    transaction = processor.create_transfer(oleg_id, ivan_id, 200)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.COMPLETED
    assert processor.audit_log.get_error_statistics() == {}


def test_new_receiver_logged_as_suspicious_with_client_id() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()
    bank.accounts[oleg_id].deposit(1000)

    processor.create_transfer(oleg_id, ivan_id, 200)
    processor.process_next(now=_safe_time())

    suspicious = processor.audit_log.get_suspicious_operations()
    assert len(suspicious) == 1
    event = suspicious[0]
    assert event.event_type == "risk_detected"
    assert event.level == AuditLevel.MEDIUM
    assert event.client_id == 1
    assert "Транзакция на новый счет" in event.metadata["reasons"]


def test_large_amount_blocked_and_recorded() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()
    bank.accounts[oleg_id].deposit(200_000_000)

    transaction = processor.create_transfer(oleg_id, ivan_id, 150_000_000)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.FAILED
    assert bank.accounts[ivan_id].balance == 0

    blocked = processor.audit_log.filter(event_type="transaction_blocked")
    assert len(blocked) == 1
    assert blocked[0].level == AuditLevel.HIGH
    assert "Большая сумма транзакции" in blocked[0].metadata["reasons"]

    stats = processor.audit_log.get_error_statistics()
    assert stats["Операция заблокирована риск-анализом"] == 1


def test_failed_transaction_recorded_in_audit() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()

    transaction = processor.create_transfer(oleg_id, ivan_id, 500, max_attempts=1)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.FAILED

    failed = processor.audit_log.filter(event_type="transaction_failed")
    assert len(failed) == 1
    assert failed[0].client_id == 1

    stats = processor.audit_log.get_error_statistics()
    assert sum(stats.values()) == 1


def test_client_risk_profile_via_processor() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()
    bank.accounts[oleg_id].deposit(200_000_000)

    processor.create_transfer(oleg_id, ivan_id, 150_000_000)
    processor.process_next(now=_safe_time())

    profile = processor.audit_log.get_client_risk_profile(1)
    assert profile["total_events"] >= 2
    assert profile["level_counts"]["high"] >= 2
    assert profile["reasons"]["Большая сумма транзакции"] >= 1


def test_record_event_appends_to_file_when_path_set(tmp_path: Path) -> None:
    file_path = tmp_path / "audit.log"
    log = AuditLog(file_path=str(file_path))
    log.record_event(
        _event("a", AuditLevel.HIGH, "transaction_blocked", "blocked", client_id=1)
    )
    log.record_event(
        _event("b", AuditLevel.MEDIUM, "risk_detected", "risk", client_id=1)
    )

    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "a"
    assert json.loads(lines[1])["id"] == "b"


def test_night_dangerous_transaction_blocked() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()
    bank.accounts[oleg_id].deposit(200_000_000)

    transaction = processor.create_transfer(oleg_id, ivan_id, 150_000_000)
    processor.process_next(now=_quiet_time())

    assert transaction.status == TransactionStatus.FAILED
    assert bank.accounts[ivan_id].balance == 0

    blocked = processor.audit_log.filter(event_type="transaction_blocked")
    assert len(blocked) == 1
    assert "Большая сумма транзакции" in blocked[0].metadata["reasons"]
    assert "Операция в тихие часы" not in blocked[0].metadata["reasons"]

    risk_events = processor.audit_log.filter(event_type="risk_detected")
    assert len(risk_events) == 1
    assert "Большая сумма транзакции" in risk_events[0].metadata["reasons"]
    assert "Операция в тихие часы" in risk_events[0].metadata["reasons"]


def test_night_normal_transaction_deferred_with_risk_detected() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()
    bank.accounts[oleg_id].deposit(1000)

    transaction = processor.create_transfer(oleg_id, ivan_id, 100)
    result = processor.process_next(now=_quiet_time())

    assert result is transaction
    assert transaction.status == TransactionStatus.DELAYED
    assert transaction.attempt == 0
    assert bank.accounts[ivan_id].balance == 0

    risk_events = processor.audit_log.filter(event_type="risk_detected")
    assert len(risk_events) == 1
    assert "Операция в тихие часы" in risk_events[0].metadata["reasons"]
    assert processor.audit_log.filter(event_type="transaction_blocked") == []
    assert len(processor.error_log) == 1
    assert "тихие часы" in processor.error_log[0]["error"].lower()


def test_blocked_transaction_does_not_consume_new_receiver() -> None:
    bank, processor, oleg_id, ivan_id = _setup_bank_and_processor()
    bank.accounts[oleg_id].deposit(200_000_000)

    blocked_tx = processor.create_transfer(oleg_id, ivan_id, 150_000_000)
    processor.process_next(now=_safe_time())
    assert blocked_tx.status == TransactionStatus.FAILED

    normal_tx = processor.create_transfer(oleg_id, ivan_id, 200)
    processor.process_next(now=_safe_time())
    assert normal_tx.status == TransactionStatus.COMPLETED

    risk_events = processor.audit_log.filter(event_type="risk_detected")
    assert len(risk_events) == 2
    assert "Транзакция на новый счет" in risk_events[0].metadata["reasons"]
    assert "Транзакция на новый счет" in risk_events[1].metadata["reasons"]
