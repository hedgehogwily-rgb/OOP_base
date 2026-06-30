from datetime import datetime, timedelta

from src.models import (
    AccountType,
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


def _authenticate_clients(bank: Bank, client_ids: list[int]) -> None:
    for client_id in client_ids:
        bank.authenticate_client(client_id, is_credentials_valid=True)


def _fund(bank: Bank, client_id: int, account_id: str, amount: float) -> None:
    if client_id not in bank.authenticated_clients:
        bank.authenticate_client(client_id, is_credentials_valid=True)
    bank.deposit(client_id, account_id, amount)


def _setup_bank_and_processor() -> tuple[
    Bank, TransactionQueue, TransactionProcessor, str, str, str
]:
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
    john = _client(2, "John")
    ivan = _client(3, "Ivan")
    bank.add_client(oleg)
    bank.add_client(john)
    bank.add_client(ivan)

    oleg_account_id = bank.open_account(
        oleg.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    john_account_id = bank.open_account(
        john.id,
        BankAccount({"name": "John", "surname": "Test"}, currency=Currency.USD),
    )
    ivan_account_id = bank.open_account(
        ivan.id,
        PremiumAccount({"name": "Ivan", "surname": "Test"}, currency=Currency.RUB),
    )
    _authenticate_clients(bank, [oleg.id, john.id, ivan.id])
    return bank, queue, processor, oleg_account_id, john_account_id, ivan_account_id


def test_successful_transfer_changes_balances() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)

    transaction = processor.create_transfer(1, oleg_id, ivan_id, 200)
    result = processor.process_next(now=_safe_time())

    assert result is transaction
    assert transaction.status == TransactionStatus.COMPLETED
    assert bank.accounts[oleg_id].balance == 800
    assert bank.accounts[ivan_id].balance == 200


def test_priority_processing_order() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)

    low = processor.create_transfer(1, oleg_id, ivan_id, 100, priority=1)
    high = processor.create_transfer(1, oleg_id, ivan_id, 120, priority=10)

    first = processor.process_next(now=_safe_time())
    second = processor.process_next(now=_safe_time())

    assert first is high
    assert second is low


def test_delayed_transaction_processed_only_after_scheduled_time() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 500)
    base = _safe_time()
    delayed = processor.create_transfer(
        1,
        oleg_id,
        ivan_id,
        150,
        scheduled_at=base + timedelta(minutes=10),
    )

    no_result = processor.process_next(now=base + timedelta(minutes=5))
    assert no_result is None
    assert delayed.status == TransactionStatus.DELAYED

    yes_result = processor.process_next(now=base + timedelta(minutes=11))
    assert yes_result is delayed
    assert delayed.status == TransactionStatus.COMPLETED


def test_cancel_transaction_before_processing() -> None:
    bank, queue, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 500)
    transaction = processor.create_transfer(1, oleg_id, ivan_id, 150, priority=2)

    assert queue.cancel(transaction.id, now=_safe_time()) is True
    assert processor.process_next(now=_safe_time()) is None
    assert transaction.status == TransactionStatus.CANCELLED


def test_quiet_hours_transaction_blocked() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)
    quiet_now = _quiet_time()
    transaction = processor.create_transfer(1, oleg_id, ivan_id, 100)

    result = processor.process_next(now=quiet_now)

    assert result is transaction
    assert transaction.status == TransactionStatus.FAILED
    assert bank.accounts[ivan_id].balance == 0
    assert "Операции запрещены" in (transaction.failure_reason or "")

    failed = processor.audit_log.filter(event_type="transaction_failed")
    assert len(failed) == 1


def test_quiet_hours_uses_process_time_not_bank_clock() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)
    transaction = processor.create_transfer(1, oleg_id, ivan_id, 100)

    result = processor.process_next(now=_quiet_time())

    assert result is transaction
    assert transaction.status == TransactionStatus.FAILED
    assert bank.is_quiet_hours(_safe_time()) is False
    assert "Операции запрещены" in (transaction.failure_reason or "")


def test_frozen_account_rejected() -> None:
    bank, _, processor, oleg_id, john_id, _ = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)
    bank.accounts[john_id].account_status = AccountType.FROZEN
    transaction = processor.create_transfer(1, oleg_id, john_id, 50, max_attempts=1)

    processor.process_next(now=_safe_time())
    assert transaction.status == TransactionStatus.FAILED
    assert "заморожен" in (transaction.failure_reason or "").lower()


def test_insufficient_funds_non_premium_and_premium_overdraft() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    non_premium = processor.create_transfer(1, oleg_id, ivan_id, 100, max_attempts=1)
    processor.process_next(now=_safe_time())
    assert non_premium.status == TransactionStatus.FAILED

    premium_success = processor.create_transfer(
        3, ivan_id, oleg_id, 700, max_attempts=1
    )
    processor.process_next(now=_safe_time())
    assert premium_success.status == TransactionStatus.COMPLETED
    premium_account = bank.accounts[ivan_id]
    assert isinstance(premium_account, PremiumAccount)
    assert premium_account.available_overdraft < premium_account.overdraft_limit


def test_premium_transfer_fee_in_transaction() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 3, ivan_id, 5000)

    transaction = processor.create_transfer(3, ivan_id, oleg_id, 700, max_attempts=1)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.COMPLETED
    assert transaction.fee == 10.0
    assert bank.accounts[ivan_id].balance == 5000 - 700 - 10


def test_external_transfer_fee_applied() -> None:
    bank, _, processor, oleg_id, john_id, _ = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)
    bank.accounts[john_id].is_external = True

    transaction = processor.create_transfer(1, oleg_id, john_id, 100, max_attempts=1)

    processor.process_next(now=_safe_time())
    assert transaction.status == TransactionStatus.COMPLETED
    assert transaction.fee == 3
    assert bank.accounts[oleg_id].balance == 897


def test_cross_currency_internal_transfer_no_external_fee() -> None:
    bank, _, processor, oleg_id, john_id, _ = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)

    transaction = processor.create_transfer(1, oleg_id, john_id, 100, max_attempts=1)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.COMPLETED
    assert transaction.fee == 0
    assert bank.accounts[oleg_id].balance == 900


def test_retry_until_max_attempts_then_fail() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    transaction = processor.create_transfer(1, oleg_id, ivan_id, 200, max_attempts=2)

    first = processor.process_next(now=_safe_time())
    second = processor.process_next(now=_safe_time())

    assert first is transaction
    assert second is transaction
    assert transaction.status == TransactionStatus.FAILED
    assert transaction.attempt == 2
    assert len(processor.error_log) == 2


def test_process_ten_transactions_flow() -> None:
    bank, queue, processor, oleg_id, john_id, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 5_000)
    _fund(bank, 2, john_id, 100)
    _fund(bank, 3, ivan_id, 50)
    bank.accounts[john_id].account_status = AccountType.FROZEN

    base = _safe_time()
    txs = [
        processor.create_transfer(1, oleg_id, ivan_id, 200, priority=8),
        processor.create_transfer(1, oleg_id, john_id, 80, priority=10),
        processor.create_transfer(3, ivan_id, oleg_id, 500, priority=7),
        processor.create_transfer(1, oleg_id, ivan_id, 180, priority=6),
        processor.create_transfer(
            1,
            oleg_id,
            ivan_id,
            40,
            priority=5,
            scheduled_at=base + timedelta(minutes=10),
        ),
        processor.create_transfer(2, john_id, oleg_id, 30, priority=4),
        processor.create_transfer(1, oleg_id, john_id, 60, priority=3),
        processor.create_transfer(3, ivan_id, john_id, 20, priority=2),
        processor.create_transfer(1, oleg_id, ivan_id, 70, priority=1),
        processor.create_transfer(3, ivan_id, oleg_id, 1200, priority=9),
    ]

    queue.cancel(txs[8].id, now=base)
    processor.process_all(now=base)
    bank.accounts[john_id].account_status = AccountType.ACTIVE
    processor.process_all(now=base + timedelta(minutes=11))

    assert len(txs) == 10
    assert any(tx.status == TransactionStatus.COMPLETED for tx in txs)
    assert any(tx.status == TransactionStatus.FAILED for tx in txs)
    assert any(tx.status == TransactionStatus.CANCELLED for tx in txs)


def test_create_transfer_foreign_account_rejected() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)

    transaction = processor.create_transfer(2, oleg_id, ivan_id, 100)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.FAILED
    assert "не принадлежит" in (transaction.failure_reason or "")


def test_create_transfer_without_auth_rejected() -> None:
    bank = Bank(now_provider=_safe_time)
    queue = TransactionQueue()
    processor = TransactionProcessor(bank, queue, now_provider=_safe_time)
    client = _client(1, "Oleg")
    bank.add_client(client)
    account_id = bank.open_account(
        client.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )

    transaction = processor.create_transfer(1, account_id, account_id, 100)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.FAILED
    assert "не аутентифицирован" in (transaction.failure_reason or "")


def test_create_transfer_locked_client_rejected() -> None:
    bank, _, processor, oleg_id, _, ivan_id = _setup_bank_and_processor()
    _fund(bank, 1, oleg_id, 1000)

    for _ in range(3):
        bank.authenticate_client(1, is_credentials_valid=False)

    transaction = processor.create_transfer(1, oleg_id, ivan_id, 100)
    processor.process_next(now=_safe_time())

    assert transaction.status == TransactionStatus.FAILED
    assert "заблокирован" in (transaction.failure_reason or "")
