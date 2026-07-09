from datetime import datetime

import pytest

from src.models import AccountType, Bank, BankAccount, Client, Currency, PremiumAccount
from src.utils import InvalidOperationError


def _safe_time() -> datetime:
    return datetime(2026, 1, 1, 10, 0, 0)


def _quiet_time() -> datetime:
    return datetime(2026, 1, 1, 1, 0, 0)


def _create_client(client_id: int, name: str) -> Client:
    return Client(
        name=name,
        surname="Test",
        id=client_id,
        age=25,
        contacts=[f"+7-987-654-32-{client_id:02d}"],
    )


def _authenticate(bank: Bank, client_id: int) -> None:
    bank.authenticate_client(client_id, is_credentials_valid=True)


def test_add_client_and_open_account() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)

    account = BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB)
    account_id = bank.open_account(client.id, account)

    assert account_id in bank.accounts
    assert account_id in client.account_ids


def test_open_account_requires_authentication() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    account = BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB)

    with pytest.raises(InvalidOperationError, match="не аутентифицирован"):
        bank.open_account(client.id, account)


def test_close_freeze_and_unfreeze_account() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)
    account = BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB)
    account_id = bank.open_account(client.id, account)

    bank.freeze_account(client.id, account_id)
    assert bank.accounts[account_id].account_status == AccountType.FROZEN

    bank.unfreeze_account(client.id, account_id)
    assert bank.accounts[account_id].account_status == AccountType.ACTIVE

    bank.close_account(client.id, account_id)
    assert bank.accounts[account_id].account_status == AccountType.CLOSED
    assert account_id in client.account_ids
    assert bank.search_accounts(client_id=client.id, status=AccountType.CLOSED) == [
        account
    ]


def test_cannot_freeze_or_reopen_closed_account() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)
    account_id = bank.open_account(
        client.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.close_account(client.id, account_id)

    with pytest.raises(InvalidOperationError, match="нельзя заморозить"):
        bank.freeze_account(client.id, account_id)

    with pytest.raises(InvalidOperationError, match="Закрытый счет нельзя разморозить"):
        bank.unfreeze_account(client.id, account_id)


def test_cannot_close_account_with_balance() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)
    account_id = bank.open_account(
        client.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.deposit(client.id, account_id, 1000)

    with pytest.raises(InvalidOperationError, match="ненулевым балансом"):
        bank.close_account(client.id, account_id)

    assert bank.get_total_balance() == 1000


def test_cannot_close_premium_account_with_debt() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)
    account_id = bank.open_account(
        client.id,
        PremiumAccount(
            {"name": "Oleg", "surname": "Test"},
            currency=Currency.RUB,
            overdraft_limit=500,
        ),
    )
    bank.withdraw(client.id, account_id, 100)

    with pytest.raises(InvalidOperationError, match="ненулевым балансом"):
        bank.close_account(client.id, account_id)

    assert bank.accounts[account_id].balance < 0


def test_authenticate_locks_after_three_attempts() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)

    assert bank.authenticate_client(client.id, is_credentials_valid=False) is False
    assert bank.authenticate_client(client.id, is_credentials_valid=False) is False
    assert bank.authenticate_client(client.id, is_credentials_valid=False) is False
    assert client.status == "locked"

    with pytest.raises(InvalidOperationError):
        bank.authenticate_client(client.id, is_credentials_valid=True)


def test_locked_client_cannot_operate() -> None:
    bank = Bank(now_provider=_safe_time)
    sender = _create_client(1, "Oleg")
    receiver = _create_client(2, "John")
    bank.add_client(sender)
    bank.add_client(receiver)

    _authenticate(bank, sender.id)
    _authenticate(bank, receiver.id)

    sender_account_id = bank.open_account(
        sender.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    receiver_account_id = bank.open_account(
        receiver.id,
        BankAccount({"name": "John", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.deposit(sender.id, sender_account_id, 1000)

    for _ in range(3):
        bank.authenticate_client(sender.id, is_credentials_valid=False)
    assert sender.status == "locked"

    with pytest.raises(InvalidOperationError, match="заблокирован"):
        bank.deposit(sender.id, sender_account_id, 100)
    with pytest.raises(InvalidOperationError, match="заблокирован"):
        bank.withdraw(sender.id, sender_account_id, 100)
    with pytest.raises(InvalidOperationError, match="заблокирован"):
        bank.transfer(sender.id, sender_account_id, receiver_account_id, 100)
    with pytest.raises(InvalidOperationError, match="заблокирован"):
        bank.freeze_account(sender.id, sender_account_id)
    with pytest.raises(InvalidOperationError, match="заблокирован"):
        bank.unfreeze_account(sender.id, sender_account_id)
    with pytest.raises(InvalidOperationError, match="заблокирован"):
        bank.close_account(sender.id, sender_account_id)

    assert any(
        action["reason"] == "operation_for_locked_client"
        and action["client_id"] == sender.id
        for action in bank.suspicious_actions
    )


def test_open_account_forbidden_during_quiet_hours() -> None:
    bank = Bank(now_provider=_quiet_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)
    account = BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB)

    with pytest.raises(InvalidOperationError, match="Операции запрещены"):
        bank.open_account(client.id, account)

    assert bank.suspicious_actions[-1]["reason"] == "operation_during_quiet_hours"


def test_total_balance_and_clients_ranking() -> None:
    bank = Bank(now_provider=_safe_time)
    oleg = _create_client(1, "Oleg")
    john = _create_client(2, "John")
    bank.add_client(oleg)
    bank.add_client(john)

    oleg_account = BankAccount(
        {"name": "Oleg", "surname": "Test"}, currency=Currency.RUB
    )
    john_account = BankAccount(
        {"name": "John", "surname": "Test"}, currency=Currency.RUB
    )
    _authenticate(bank, oleg.id)
    _authenticate(bank, john.id)
    oleg_id = bank.open_account(oleg.id, oleg_account)
    john_id = bank.open_account(john.id, john_account)

    bank.deposit(oleg.id, oleg_id, 1000)
    bank.deposit(john.id, john_id, 500)

    assert bank.get_total_balance() == 1500
    ranking = bank.get_clients_ranking()
    assert ranking[0]["client_id"] == oleg.id
    assert ranking[0]["total_balance"] == 1000
    assert ranking[1]["client_id"] == john.id


def test_frozen_account_included_in_balance_reports() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)
    account_id = bank.open_account(
        client.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.deposit(client.id, account_id, 1000)
    bank.freeze_account(client.id, account_id)

    assert bank.get_total_balance() == 1000
    ranking = bank.get_clients_ranking()
    assert ranking[0]["total_balance"] == 1000


def test_closed_account_excluded_after_zero_balance_close() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
    _authenticate(bank, client.id)
    account_id = bank.open_account(
        client.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.deposit(client.id, account_id, 1000)
    bank.withdraw(client.id, account_id, 1000)
    bank.close_account(client.id, account_id)

    assert bank.get_total_balance() == 0
    assert bank.get_clients_ranking()[0]["total_balance"] == 0


def test_bank_transfer_large_amount_blocked() -> None:
    bank = Bank(now_provider=_safe_time)
    sender = _create_client(1, "Oleg")
    receiver = _create_client(2, "John")
    bank.add_client(sender)
    bank.add_client(receiver)
    _authenticate(bank, sender.id)
    _authenticate(bank, receiver.id)
    sender_account_id = bank.open_account(
        sender.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    receiver_account_id = bank.open_account(
        receiver.id,
        BankAccount({"name": "John", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.deposit(sender.id, sender_account_id, 200_000_000)

    with pytest.raises(InvalidOperationError, match="риск-анализом"):
        bank.transfer(sender.id, sender_account_id, receiver_account_id, 150_000_000)

    assert bank.accounts[receiver_account_id].balance == 0
    blocked = bank.audit_log.filter(event_type="transaction_blocked")
    assert len(blocked) == 1
    assert "Большая сумма транзакции" in blocked[0].metadata["reasons"]


def test_failed_auth_recorded_in_audit_log() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)

    for _ in range(3):
        bank.authenticate_client(client.id, is_credentials_valid=False)

    profile = bank.audit_log.get_client_risk_profile(client.id)
    assert profile["total_events"] == 4
    assert profile["reasons"]["failed_auth"] == 3
    assert profile["reasons"]["client_locked_after_failed_auth"] == 1


def test_foreign_account_attempt_in_audit() -> None:
    bank = Bank(now_provider=_safe_time)
    sender = _create_client(1, "Oleg")
    receiver = _create_client(2, "John")
    bank.add_client(sender)
    bank.add_client(receiver)
    _authenticate(bank, sender.id)
    _authenticate(bank, receiver.id)
    sender_account_id = bank.open_account(
        sender.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    receiver_account_id = bank.open_account(
        receiver.id,
        BankAccount({"name": "John", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.deposit(sender.id, sender_account_id, 1000)

    with pytest.raises(InvalidOperationError, match="не принадлежит"):
        bank.transfer(sender.id, receiver_account_id, sender_account_id, 100)

    security_events = bank.audit_log.filter(event_type="security_event")
    assert len(security_events) == 1
    assert security_events[0].level.value == "high"
    assert "transfer_from_foreign_account_attempt" in security_events[0].metadata[
        "reasons"
    ]
