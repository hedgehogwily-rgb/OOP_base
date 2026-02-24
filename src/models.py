import uuid

from abc import ABC, abstractmethod
from enum import Enum

from utils import (
    InsufficientFundsError,
    AccountFrozenError,
    AccountClosedError,
    InvalidOperationError,
)


class AccountType(Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"

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
    def __init__(self, user_data: dict, unique_index: str = None, currency: str = "RUB"):
        self.unique_index = unique_index if unique_index else uuid.uuid4().hex
        self.user_data = user_data
        self._balance = 0.0
        self.account_status = AccountType.ACTIVE
        self.currency = currency # RUB, USD, EUR, KZT, CNY
            
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
            raise InsufficientFundsError()
    
        self._balance -= amount

    def transfer(self, counterparty: "BankAccount", amount: float) -> bool:
        self.check_account_availability()
        counterparty.check_account_availability()
        
        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")
        
        if amount > self._balance:
            raise InsufficientFundsError("Insufficient funds.")
        
        converted_amount = self.currency_conversion(counterparty.currency, amount)
        
        counterparty._balance += converted_amount
        self._balance -= amount

    def get_account_info(self) -> dict:
        return {
            "unique_index": str(self.unique_index),
            "user_data": self.user_data,
            "balance": self._balance,
            "account_status": self.account_status.value,
            "currency": self.currency,
        }
        
    def check_account_availability(self) -> bool:
        if self.account_status == AccountType.FROZEN:
            raise AccountFrozenError
        elif self.account_status == AccountType.CLOSED:
            raise AccountClosedError
        else:
            return True
        
    def currency_conversion(self, target_currency: str, amount: float) -> float:
        exchange_rates = {
            "RUB": 1.0,
            "USD": 0.013,
            "EUR": 0.011,
            "KZT": 5.5,
            "CNY": 0.085,
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
            f"Баланс: {self._balance} {self.currency}"
        )