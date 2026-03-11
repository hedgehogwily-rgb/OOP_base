import uuid

from abc import ABC, abstractmethod
from enum import Enum

from src.utils import (
    InsufficientFundsError,
    AccountFrozenError,
    AccountClosedError,
    InvalidOperationError,
)


class AccountType(Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class Currency(Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"


class AbstractAccount(ABC):
    unique_index: str
    user_data: dict
    balance: float
    account_status: AccountType  # e.g., 'active', 'frozen', 'closed'

    @abstractmethod
    def deposit(self, amount: float) -> None:
        pass

    @abstractmethod
    def withdraw(self, amount: float) -> None:
        pass

    @abstractmethod
    def get_account_info(self) -> dict:
        pass


class BankAccount(AbstractAccount):
    def __init__(
        self,
        user_data: dict,
        unique_index: str = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
    ):
        self.unique_index = unique_index if unique_index else uuid.uuid4().hex
        self.user_data = user_data
        self._balance = 0.0
        self.account_status = account_status
        if isinstance(currency, Currency):
            self.currency = currency
        else:
            raise InvalidOperationError(
                "Неверный тип валюты. Ожидается экземпляр класса Currency."
            )

    @property
    def balance(self) -> float:
        return self._balance

    def deposit(self, amount: float) -> None:
        self.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        self._balance += amount

    def withdraw(self, amount: float) -> None:
        self.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        if amount > self._balance:
            raise InsufficientFundsError("Недостаточно средств.")

        self._balance -= amount

    def transfer(self, counterparty: "BankAccount", amount: float) -> None:
        self.check_account_availability()
        counterparty.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        if amount > self._balance:
            raise InsufficientFundsError("Недостаточно средств.")

        converted_amount = self.currency_conversion(counterparty.currency, amount)

        counterparty._balance += converted_amount
        self._balance -= amount

    def get_account_info(self) -> dict:
        return {
            "unique_index": str(self.unique_index),
            "user_data": self.user_data,
            "balance": self._balance,
            "account_status": self.account_status.value,
            "currency": self.currency.value,
        }

    def check_account_availability(self) -> bool:
        if self.account_status == AccountType.FROZEN:
            raise AccountFrozenError()
        elif self.account_status == AccountType.CLOSED:
            raise AccountClosedError()
        else:
            return True

    def currency_conversion(self, target_currency: Currency, amount: float) -> float:
        exchange_rates = {
            Currency.RUB: 1.0,
            Currency.USD: 0.013,
            Currency.EUR: 0.011,
            Currency.KZT: 5.5,
            Currency.CNY: 0.085,
        }

        if self.currency not in exchange_rates:
            raise InvalidOperationError("Unsupported source currency.")

        if target_currency not in exchange_rates:
            raise InvalidOperationError("Unsupported target currency.")

        amount_in_rub = amount / exchange_rates[self.currency]

        return amount_in_rub * exchange_rates[target_currency]

    def freeze_account(self) -> None:
        self.account_status = AccountType.FROZEN

    def close_account(self) -> None:
        self.account_status = AccountType.CLOSED

    def __str__(self) -> str:
        return (
            f"Тип счета: {self.__class__.__name__}\n"
            f"Данные пользователя: {self.user_data}\n"
            f"Индекс: {self.unique_index[-4:]}\n"
            f"Статус: {self.account_status.value}\n"
            f"Баланс: {self._balance} {self.currency.value}"
        )


class SavingsAccount(BankAccount):
    def __init__(
        self,
        user_data: dict,
        unique_index: str = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
        interest_rate: float = 0.02,
        min_balance: float = 100.0,
    ):
        super().__init__(user_data, unique_index, currency, account_status)
        self.interest_rate = interest_rate
        self.min_balance = min_balance

    def withdraw(self, amount) -> None:
        self.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        if self._balance - amount < self.min_balance:
            raise InsufficientFundsError(
                "Недостаточно средств для поддержания минимального баланса."
            )

        super().withdraw(amount)

    def apply_interest_for_month(self) -> None:
        self.check_account_availability()
        interest = self._balance * self.interest_rate
        self._balance += interest

    def get_account_info(self) -> dict:
        base_info = super().get_account_info()
        base_info.update(
            {
                "account_type": "SavingsAccount",
                "interest_rate": self.interest_rate,
                "min_balance": self.min_balance,
            }
        )
        return base_info

    def __str__(self) -> str:
        str_info = super().__str__()
        str_info += (
            f"\nПроцентная ставка: {self.interest_rate * 100}%\n"
            f"Минимальный баланс: {self.min_balance} {self.currency.value}"
        )
        return str_info


class PremiumAccount(BankAccount):
    def __init__(
        self,
        user_data: dict,
        unique_index: str = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
        overdraft_limit: float = 1000.0,
        commission_rate: float = 0.1,
    ):
        super().__init__(user_data, unique_index, currency, account_status)
        self.overdraft_limit = overdraft_limit
        self.available_overdraft = overdraft_limit
        self.commission_rate = commission_rate

    def withdraw(self, amount) -> None:
        self.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        total_amount = amount + (amount * self.commission_rate)

        if total_amount <= self._balance:
            self._balance -= total_amount
            return

        needed_overdraft = total_amount - self._balance

        if needed_overdraft > self.available_overdraft:
            raise InsufficientFundsError("Недостаточно средств, включая овердрафт.")

        self._balance = 0
        self.available_overdraft -= needed_overdraft

    def deposit(self, amount: float) -> None:
        self.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        debt = self.overdraft_limit - self.available_overdraft

        if debt > 0:
            if amount >= debt:
                amount -= debt
                self.available_overdraft = self.overdraft_limit
                self._balance += amount
            else:
                self.available_overdraft += amount
        else:
            self._balance += amount

    def get_account_info(self) -> dict:
        base_info = super().get_account_info()
        base_info.update(
            {
                "account_type": "PremiumAccount",
                "overdraft_limit": self.overdraft_limit,
                "available_overdraft": self.available_overdraft,
                "commission_rate": self.commission_rate,
            }
        )
        return base_info

    def __str__(self) -> str:
        str_info = super().__str__()
        str_info += (
            f"\nОвердрафт лимит: {self.overdraft_limit} {self.currency.value}\n"
            f"Доступный овердрафт: {self.available_overdraft} {self.currency.value}\n"
            f"Комиссия: {self.commission_rate * 100}%"
        )
        return str_info


class InvestmentAccount(BankAccount):
    def __init__(
        self,
        user_data: dict,
        unique_index: str = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
    ):
        super().__init__(user_data, unique_index, currency, account_status)
        self.investment_portfolio = {
            "stocks": 0.0,
            "bonds": 0.0,
            "etf": 0.0,
        }

    def buy_investment(self, investment_type: str, amount: float) -> None:
        self.check_account_availability()

        if investment_type not in self.investment_portfolio:
            raise InvalidOperationError("Неверный тип инвестиции.")

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        if amount > self._balance:
            raise InsufficientFundsError("Недостаточно средств для покупки инвестиций.")

        self._balance -= amount
        self.investment_portfolio[investment_type] += amount

    def sell_investment(self, investment_type: str, amount: float) -> None:
        self.check_account_availability()

        if investment_type not in self.investment_portfolio:
            raise InvalidOperationError("Неверный тип инвестиции.")

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        if amount > self.investment_portfolio[investment_type]:
            raise InsufficientFundsError("Недостаточно инвестиций для продажи.")

        self.investment_portfolio[investment_type] -= amount
        self._balance += amount

    def project_yearly_growth(self, growth_rate: float = 0.25) -> dict:
        if growth_rate < 0:
            raise InvalidOperationError("Темп роста должен быть неотрицательным.")
        
        projected_portfolio = {}
        for investment_type, amount in self.investment_portfolio.items():
            projected_amount = amount * (1 + growth_rate)
            projected_portfolio[investment_type] = projected_amount
        return projected_portfolio

    def withdraw(self, amount: float) -> None:
        # Переопределяем метод таким образом, чтобы запретить прямые снятия со счета, так как деньги должны быть в инвестициях
        raise InvalidOperationError("Прямые снятия с инвестиционного счета запрещены.")

    def get_account_info(self) -> dict:
        base_info = super().get_account_info()
        base_info.update(
            {
                "account_type": "InvestmentAccount",
                "investment_portfolio": self.investment_portfolio,
            }
        )
        return base_info

    def __str__(self) -> str:
        str_info = super().__str__()
        str_info += "\nИнвестиционный портфель:"
        for investment_type, amount in self.investment_portfolio.items():
            str_info += (
                f"\n  {investment_type.capitalize()}: {amount} {self.currency.value}"
            )
        return str_info
