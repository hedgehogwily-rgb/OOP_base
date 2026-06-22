from datetime import datetime

import pytest

from src.models import AccountType, Bank, BankAccount, Client, Currency
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


def test_add_client_and_open_account() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)

    account = BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB)
    account_id = bank.open_account(client.id, account)

    assert account_id in bank.accounts
    assert account_id in client.account_ids


def test_close_freeze_and_unfreeze_account() -> None:
    bank = Bank(now_provider=_safe_time)
    client = _create_client(1, "Oleg")
    bank.add_client(client)
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

    sender_account_id = bank.open_account(
        sender.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    receiver_account_id = bank.open_account(
        receiver.id,
        BankAccount({"name": "John", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.authenticate_client(sender.id, is_credentials_valid=True)
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
    oleg_id = bank.open_account(oleg.id, oleg_account)
    john_id = bank.open_account(john.id, john_account)

    bank.authenticate_client(oleg.id, is_credentials_valid=True)
    bank.authenticate_client(john.id, is_credentials_valid=True)
    bank.deposit(oleg.id, oleg_id, 1000)
    bank.deposit(john.id, john_id, 500)

    assert bank.get_total_balance() == 1500
    ranking = bank.get_clients_ranking()
    assert ranking[0]["client_id"] == oleg.id
    assert ranking[0]["total_balance"] == 1000
    assert ranking[1]["client_id"] == john.id
