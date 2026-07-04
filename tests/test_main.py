from typing import Any

import pytest

from src.models import (
    AccountType,
    BankAccount,
    Currency,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
)
from src.utils import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)


@pytest.fixture
def user() -> dict[str, Any]:
    return {"name": "Oleg", "id": 1}


def test_deposit(user: dict[str, Any]) -> None:
    acc = BankAccount(user)

    acc.deposit(1000)

    assert acc.balance == 1000


def test_withdraw(user: dict[str, Any]) -> None:
    acc = BankAccount(user)

    acc.deposit(1000)
    acc.withdraw(400)

    assert acc.balance == 600


def test_withdraw_insufficient_funds(user: dict[str, Any]) -> None:
    acc = BankAccount(user)

    acc.deposit(100)

    with pytest.raises(InsufficientFundsError):
        acc.withdraw(200)


def test_transfer(user: dict[str, Any]) -> None:
    acc1 = BankAccount(user, currency=Currency.RUB)
    acc2 = BankAccount(user, currency=Currency.RUB)

    acc1.deposit(1000)
    acc1.transfer(acc2, 500)

    assert acc1.balance == 500
    assert acc2.balance == 500


# Тесты для SavingsAccount


def test_savings_min_balance(user: dict[str, Any]) -> None:
    acc = SavingsAccount(user, min_balance=500)

    acc.deposit(1000)

    with pytest.raises(InsufficientFundsError):
        acc.withdraw(600)


def test_savings_interest(user: dict[str, Any]) -> None:
    acc = SavingsAccount(user, interest_rate=0.1)

    acc.deposit(1000)
    acc.apply_monthly_interest()

    assert acc.balance == 1100


# Тесты для PremiumAccount


def test_premium_overdraft(user: dict[str, Any]) -> None:
    acc = PremiumAccount(user, overdraft_limit=1000)

    acc.deposit(500)
    acc.withdraw(1200)

    assert acc.available_overdraft < 1000


def test_premium_overdraft_limit(user: dict[str, Any]) -> None:
    acc = PremiumAccount(user, overdraft_limit=500)

    acc.deposit(100)

    with pytest.raises(InsufficientFundsError):
        acc.withdraw(1000)


def test_premium_rejects_negative_commission(user: dict[str, Any]) -> None:
    with pytest.raises(InvalidOperationError, match="Комиссия"):
        PremiumAccount(user, commission=-100)


def test_premium_rejects_negative_overdraft_limit(user: dict[str, Any]) -> None:
    with pytest.raises(InvalidOperationError, match="овердрафта"):
        PremiumAccount(user, overdraft_limit=-1)


# Тесты для InvestmentAccount


def test_buy_investment(user: dict[str, Any]) -> None:
    acc = InvestmentAccount(user)

    acc.deposit(5000)
    acc.buy_investment("stocks", 2000)

    assert acc.investment_portfolio["stocks"] == 2000
    assert acc.balance == 3000


def test_sell_investment(user: dict[str, Any]) -> None:
    acc = InvestmentAccount(user)

    acc.deposit(5000)
    acc.buy_investment("stocks", 2000)

    acc.sell_investment("stocks", 1000)

    assert acc.investment_portfolio["stocks"] == 1000
    assert acc.balance == 4000


def test_project_growth(user: dict[str, Any]) -> None:
    acc = InvestmentAccount(user)

    acc.deposit(10000)
    acc.buy_investment("stocks", 5000)

    projection = acc.project_yearly_growth(0.1)

    assert projection["stocks"] == 5500


def test_invalid_account_status_type(user: dict[str, Any]) -> None:
    with pytest.raises(InvalidOperationError):
        BankAccount(user, account_status="frozen")  # type: ignore[arg-type]


def test_unique_index_is_short_uuid(user: dict[str, Any]) -> None:
    acc = BankAccount(user)
    assert len(acc.unique_index) == 8


def test_invalid_user_data_empty_dict() -> None:
    with pytest.raises(InvalidOperationError):
        BankAccount({})


def test_invalid_user_data_name_type() -> None:
    with pytest.raises(InvalidOperationError):
        BankAccount({"name": 123, "id": 1})  # type: ignore[typeddict-item]


def test_investment_withdraw_checks_frozen_status_first(user: dict[str, Any]) -> None:
    acc = InvestmentAccount(user, account_status=AccountType.FROZEN)

    with pytest.raises(AccountFrozenError):
        acc.withdraw(100)


def test_investment_withdraw_checks_closed_status_first(user: dict[str, Any]) -> None:
    acc = InvestmentAccount(user, account_status=AccountType.CLOSED)

    with pytest.raises(AccountClosedError):
        acc.withdraw(100)
