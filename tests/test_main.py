import pytest

from src.models import (
    BankAccount,
    SavingsAccount,
    PremiumAccount,
    InvestmentAccount,
    Currency,
)

from src.utils import (
    InsufficientFundsError,
)


@pytest.fixture
def user():
    return {"name": "Oleg", "id": 1}


def test_deposit(user):
    acc = BankAccount(user)

    acc.deposit(1000)

    assert acc.balance == 1000


def test_withdraw(user):
    acc = BankAccount(user)

    acc.deposit(1000)
    acc.withdraw(400)

    assert acc.balance == 600


def test_withdraw_insufficient_funds(user):
    acc = BankAccount(user)

    acc.deposit(100)

    with pytest.raises(InsufficientFundsError):
        acc.withdraw(200)


def test_transfer(user):
    acc1 = BankAccount(user, currency=Currency.RUB)
    acc2 = BankAccount(user, currency=Currency.RUB)

    acc1.deposit(1000)
    acc1.transfer(acc2, 500)

    assert acc1.balance == 500
    assert acc2.balance == 500

# Тесты для SavingsAccount

def test_savings_min_balance(user):
    acc = SavingsAccount(user, min_balance=500)

    acc.deposit(1000)

    with pytest.raises(InsufficientFundsError):
        acc.withdraw(600)


def test_savings_interest(user):
    acc = SavingsAccount(user, interest_rate=0.1)

    acc.deposit(1000)
    acc.apply_interest_for_month()

    assert acc.balance == 1100

# Тесты для PremiumAccount

def test_premium_overdraft(user):
    acc = PremiumAccount(user, overdraft_limit=1000)

    acc.deposit(500)
    acc.withdraw(1200)

    assert acc.available_overdraft < 1000


def test_premium_overdraft_limit(user):
    acc = PremiumAccount(user, overdraft_limit=500)

    acc.deposit(100)

    with pytest.raises(InsufficientFundsError):
        acc.withdraw(1000)


# Тесты для InvestmentAccount

def test_buy_investment(user):
    acc = InvestmentAccount(user)

    acc.deposit(5000)
    acc.buy_investment("stocks", 2000)

    assert acc.investment_portfolio["stocks"] == 2000
    assert acc.balance == 3000


def test_sell_investment(user):
    acc = InvestmentAccount(user)

    acc.deposit(5000)
    acc.buy_investment("stocks", 2000)

    acc.sell_investment("stocks", 1000)

    assert acc.investment_portfolio["stocks"] == 1000
    assert acc.balance == 4000


def test_project_growth(user):
    acc = InvestmentAccount(user)

    acc.deposit(10000)
    acc.buy_investment("stocks", 5000)

    projection = acc.project_yearly_growth(0.1)

    assert projection["stocks"] == 5500