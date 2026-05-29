from __future__ import annotations

import heapq
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, TypedDict

from src.utils import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
    QuietHoursError,
)


class AccountType(Enum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class ClientStatus(str, Enum):
    ACTIVE = "active"
    LOCKED = "locked"


class Currency(Enum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"


class TransactionType(Enum):
    TRANSFER = "transfer"


class TransactionStatus(Enum):
    PENDING = "pending"
    DELAYED = "delayed"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Transaction:
    type: TransactionType
    amount: float
    currency: Currency
    sender_account_id: str
    receiver_account_id: str
    priority: int = 0
    max_attempts: int = 3
    scheduled_at: datetime | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    fee: float = 0.0
    status: TransactionStatus = TransactionStatus.PENDING
    failure_reason: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    processed_at: datetime | None = None
    updated_at: datetime = field(default_factory=datetime.now)
    attempt: int = 0

    def mark_processing(self, now: datetime | None = None) -> None:
        self.status = TransactionStatus.PROCESSING
        self.updated_at = now or datetime.now()

    def mark_completed(self, now: datetime | None = None) -> None:
        completed_at = now or datetime.now()
        self.status = TransactionStatus.COMPLETED
        self.processed_at = completed_at
        self.updated_at = completed_at
        self.failure_reason = None

    def mark_failed(self, reason: str, now: datetime | None = None) -> None:
        failed_at = now or datetime.now()
        self.status = TransactionStatus.FAILED
        self.failure_reason = reason
        self.processed_at = failed_at
        self.updated_at = failed_at

    def mark_cancelled(self, reason: str = "Cancelled by user", now: datetime | None = None) -> None:
        cancelled_at = now or datetime.now()
        self.status = TransactionStatus.CANCELLED
        self.failure_reason = reason
        self.processed_at = cancelled_at
        self.updated_at = cancelled_at

    def mark_delayed(self, scheduled_at: datetime, now: datetime | None = None) -> None:
        self.status = TransactionStatus.DELAYED
        self.scheduled_at = scheduled_at
        self.updated_at = now or datetime.now()

    def mark_pending(self, now: datetime | None = None) -> None:
        self.status = TransactionStatus.PENDING
        self.updated_at = now or datetime.now()


class TransactionQueue:
    def __init__(self) -> None:
        self._sequence = 0
        self._ready_heap: list[tuple[int, datetime, int, str]] = []
        self._delayed: dict[str, Transaction] = {}
        self._all: dict[str, Transaction] = {}

    def _push_ready(self, transaction: Transaction) -> None:
        self._sequence += 1
        heapq.heappush(
            self._ready_heap,
            (-transaction.priority, transaction.created_at, self._sequence, transaction.id),
        )

    def add(self, transaction: Transaction, now: datetime | None = None) -> None:
        current_time = now or datetime.now()
        self._all[transaction.id] = transaction

        if transaction.scheduled_at and transaction.scheduled_at > current_time:
            transaction.mark_delayed(transaction.scheduled_at, current_time)
            self._delayed[transaction.id] = transaction
            return

        transaction.mark_pending(current_time)
        self._push_ready(transaction)

    def cancel(self, transaction_id: str, now: datetime | None = None) -> bool:
        transaction = self._all.get(transaction_id)
        if transaction is None:
            return False
        if transaction.status in (TransactionStatus.COMPLETED, TransactionStatus.FAILED):
            return False

        self._delayed.pop(transaction_id, None)
        transaction.mark_cancelled(now=now)
        return True

    def get_ready(self, now: datetime | None = None) -> list[Transaction]:
        current_time = now or datetime.now()
        moved: list[Transaction] = []

        ready_ids = [
            transaction_id
            for transaction_id, transaction in self._delayed.items()
            if transaction.scheduled_at is not None and transaction.scheduled_at <= current_time
        ]
        for transaction_id in ready_ids:
            transaction = self._delayed.pop(transaction_id)
            transaction.mark_pending(current_time)
            self._push_ready(transaction)
            moved.append(transaction)
        return moved

    def pop_next(self, now: datetime | None = None) -> Transaction | None:
        self.get_ready(now=now)
        while self._ready_heap:
            _, _, _, transaction_id = heapq.heappop(self._ready_heap)
            transaction = self._all.get(transaction_id)
            if transaction is None:
                continue
            if transaction.status != TransactionStatus.PENDING:
                continue
            return transaction
        return None

    def requeue(self, transaction: Transaction, delay_seconds: int = 0, now: datetime | None = None) -> None:
        current_time = now or datetime.now()
        if delay_seconds > 0:
            transaction.mark_delayed(
                scheduled_at=current_time + timedelta(seconds=delay_seconds),
                now=current_time,
            )
            self._delayed[transaction.id] = transaction
            return

        transaction.mark_pending(current_time)
        self._push_ready(transaction)

    def get(self, transaction_id: str) -> Transaction | None:
        return self._all.get(transaction_id)


class TransactionProcessor:
    def __init__(
        self,
        bank: Bank,
        queue: TransactionQueue,
        external_transfer_fee_rate: float = 0.02,
        retry_delay_seconds: int = 0,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.bank = bank
        self.queue = queue
        self.external_transfer_fee_rate = external_transfer_fee_rate
        self.retry_delay_seconds = retry_delay_seconds
        self.error_log: list[dict[str, Any]] = []
        self._now_provider = now_provider or datetime.now

    def _now(self) -> datetime:
        return self._now_provider()

    def create_transfer(
        self,
        sender_account_id: str,
        receiver_account_id: str,
        amount: float,
        priority: int = 0,
        max_attempts: int = 3,
        scheduled_at: datetime | None = None,
    ) -> Transaction:
        sender = self.bank.accounts.get(sender_account_id)
        if sender is None:
            raise InvalidOperationError("Счет отправителя не найден.")
        receiver = self.bank.accounts.get(receiver_account_id)
        if receiver is None:
            raise InvalidOperationError("Счет получателя не найден.")
        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        transaction = Transaction(
            type=TransactionType.TRANSFER,
            amount=amount,
            currency=sender.currency,
            sender_account_id=sender_account_id,
            receiver_account_id=receiver_account_id,
            priority=priority,
            max_attempts=max_attempts,
            scheduled_at=scheduled_at,
        )
        self.queue.add(transaction, now=self._now())
        return transaction

    def _is_external_transfer(self, sender: BankAccount, receiver: BankAccount) -> bool:
        return sender.currency != receiver.currency

    def _calculate_fee(self, sender: BankAccount, receiver: BankAccount, amount: float) -> float:
        if self._is_external_transfer(sender, receiver):
            return amount * self.external_transfer_fee_rate
        return 0.0

    def _validate_business_rules(
        self,
        transaction: Transaction,
        sender: BankAccount,
        receiver: BankAccount,
        now: datetime,
    ) -> None:
        sender.check_account_availability()
        receiver.check_account_availability()

        if transaction.amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        if self.bank.is_quiet_hours(now):
            raise QuietHoursError()

    def _execute_transfer(self, transaction: Transaction, sender: BankAccount, receiver: BankAccount) -> None:
        converted_amount = sender.currency_conversion(receiver.currency, transaction.amount)
        sender.withdraw(transaction.amount + transaction.fee)
        receiver.deposit(converted_amount)

    def _handle_failure(
        self,
        transaction: Transaction,
        error: Exception,
        now: datetime,
        retryable: bool,
    ) -> None:
        transaction.attempt += 1
        reason = str(error)
        transaction.failure_reason = reason
        transaction.updated_at = now
        self.error_log.append(
            {
                "transaction_id": transaction.id,
                "attempt": transaction.attempt,
                "error": reason,
                "timestamp": now.isoformat(timespec="seconds"),
            }
        )
        if retryable and transaction.attempt < transaction.max_attempts:
            self.queue.requeue(transaction, delay_seconds=self.retry_delay_seconds, now=now)
            return

        transaction.mark_failed(reason, now=now)

    def process_next(self, now: datetime | None = None) -> Transaction | None:
        current_time = now or self._now()
        transaction = self.queue.pop_next(now=current_time)
        if transaction is None:
            return None

        transaction.mark_processing(current_time)
        try:
            sender = self.bank.accounts.get(transaction.sender_account_id)
            if sender is None:
                raise InvalidOperationError("Счет отправителя не найден.")
            receiver = self.bank.accounts.get(transaction.receiver_account_id)
            if receiver is None:
                raise InvalidOperationError("Счет получателя не найден.")

            transaction.fee = self._calculate_fee(sender, receiver, transaction.amount)
            self._validate_business_rules(transaction, sender, receiver, current_time)
            self._execute_transfer(transaction, sender, receiver)
            transaction.mark_completed(current_time)
        except QuietHoursError:
            delay = self.bank.seconds_until_open_hours(current_time)
            self.queue.requeue(transaction, delay_seconds=delay, now=current_time)
            return transaction
        except InvalidOperationError as error:
            self._handle_failure(transaction, error, current_time, retryable=False)
        except Exception as error:
            self._handle_failure(
                transaction=transaction,
                error=error,
                now=current_time,
                retryable=isinstance(error, InsufficientFundsError),
            )
        return transaction

    def process_all(self, now: datetime | None = None, limit: int | None = None) -> list[Transaction]:
        processed: list[Transaction] = []
        current_time = now or self._now()
        while True:
            if limit is not None and len(processed) >= limit:
                break
            transaction = self.process_next(now=current_time)
            if transaction is None:
                break
            processed.append(transaction)
        return processed


class UserData(TypedDict, total=False):
    name: str
    surname: str
    id: int


InvestmentPortfolio = dict[str, float]


class AbstractAccount(ABC):
    unique_index: str
    user_data: UserData | dict[str, Any]
    account_status: AccountType  # e.g., 'active', 'frozen', 'closed'

    @property
    @abstractmethod
    def balance(self) -> float:
        pass

    @abstractmethod
    def deposit(self, amount: float) -> None:
        pass

    @abstractmethod
    def withdraw(self, amount: float) -> None:
        pass

    @abstractmethod
    def get_account_info(self) -> dict[str, Any]:
        pass


class BankAccount(AbstractAccount):
    def __init__(
        self,
        user_data: UserData | dict[str, Any],
        unique_index: str | None = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
    ) -> None:
        self.unique_index = unique_index if unique_index else uuid.uuid4().hex[:8]
        self.user_data = self._validate_user_data(user_data)
        self._balance = 0.0
        if isinstance(account_status, AccountType):
            self.account_status = account_status
        else:
            raise InvalidOperationError(
                "Неверный тип статуса. Ожидается экземпляр класса AccountType."
            )
        if isinstance(currency, Currency):
            self.currency = currency
        else:
            raise InvalidOperationError(
                "Неверный тип валюты. Ожидается экземпляр класса Currency."
            )

    @staticmethod
    def _validate_user_data(user_data: UserData | dict[str, Any]) -> UserData | dict[str, Any]:
        if not isinstance(user_data, dict):
            raise InvalidOperationError(
                "Неверный формат user_data. Ожидается словарь с данными пользователя."
            )

        if not user_data:
            raise InvalidOperationError("Данные пользователя не могут быть пустыми.")

        for field_name in ("name", "surname"):
            if field_name in user_data:
                field_value = user_data[field_name]
                if not isinstance(field_value, str) or not field_value.strip():
                    raise InvalidOperationError(
                        f"Поле '{field_name}' должно быть непустой строкой."
                    )

        if "id" in user_data and not isinstance(user_data["id"], int):
            raise InvalidOperationError("Поле 'id' должно быть целым числом.")

        return user_data

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

    def transfer(self, counterparty: BankAccount, amount: float) -> None:
        self.check_account_availability()
        counterparty.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        converted_amount = self.currency_conversion(counterparty.currency, amount)

        self.withdraw(amount)
        counterparty.deposit(converted_amount)

    def get_account_info(self) -> dict[str, Any]:
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
        elif self.account_status != AccountType.ACTIVE:
            raise InvalidOperationError("Недопустимое значение статуса счета.")
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
        user_data: UserData | dict[str, Any],
        unique_index: str | None = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
        interest_rate: float = 0.02,
        min_balance: float = 100.0,
    ) -> None:
        super().__init__(user_data, unique_index, currency, account_status)
        self.interest_rate = interest_rate
        self.min_balance = min_balance

    def withdraw(self, amount: float) -> None:
        self.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        if self._balance - amount < self.min_balance:
            raise InsufficientFundsError(
                "Недостаточно средств для поддержания минимального баланса."
            )

        super().withdraw(amount)

    def apply_monthly_interest(self) -> None:
        self.check_account_availability()
        interest = self._balance * self.interest_rate
        self._balance += interest

    def get_account_info(self) -> dict[str, Any]:
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
        user_data: UserData | dict[str, Any],
        unique_index: str | None = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
        overdraft_limit: float = 1000.0,
        commission: float = 10.0,
    ) -> None:
        super().__init__(user_data, unique_index, currency, account_status)
        self.overdraft_limit = overdraft_limit
        self.available_overdraft = overdraft_limit
        self.commission = commission

    def withdraw(self, amount: float) -> None:
        self.check_account_availability()

        if amount <= 0:
            raise InvalidOperationError("Сумма должна быть больше нуля.")

        total_amount = amount + self.commission

        if total_amount <= self._balance:
            self._balance -= total_amount
            return

        needed_overdraft = total_amount - self._balance

        if needed_overdraft > self.available_overdraft:
            raise InsufficientFundsError("Недостаточно средств, включая овердрафт.")

        self._balance = 0.0
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

    def get_account_info(self) -> dict[str, Any]:
        base_info = super().get_account_info()
        base_info.update(
            {
                "account_type": "PremiumAccount",
                "overdraft_limit": self.overdraft_limit,
                "available_overdraft": self.available_overdraft,
                "commission": self.commission,
            }
        )
        return base_info

    def __str__(self) -> str:
        str_info = super().__str__()
        str_info += (
            f"\nОвердрафт лимит: {self.overdraft_limit} {self.currency.value}\n"
            f"Доступный овердрафт: {self.available_overdraft} {self.currency.value}\n"
            f"Комиссия: {self.commission} {self.currency.value}"
        )
        return str_info


class InvestmentAccount(BankAccount):
    def __init__(
        self,
        user_data: UserData | dict[str, Any],
        unique_index: str | None = None,
        currency: Currency = Currency.RUB,
        account_status: AccountType = AccountType.ACTIVE,
    ) -> None:
        super().__init__(user_data, unique_index, currency, account_status)
        self.investment_portfolio: InvestmentPortfolio = {
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

    def project_yearly_growth(self, growth_rate: float = 0.25) -> dict[str, float]:
        if growth_rate < 0:
            raise InvalidOperationError("Темп роста должен быть неотрицательным.")

        projected_portfolio: dict[str, float] = {}
        for investment_type, amount in self.investment_portfolio.items():
            projected_amount = amount * (1 + growth_rate)
            projected_portfolio[investment_type] = projected_amount
        return projected_portfolio

    def withdraw(self, amount: float) -> None:
        self.check_account_availability()
        # Прямые снятия запрещены, вывод средств должен происходить через продажу активов.
        raise InvalidOperationError("Прямые снятия с инвестиционного счета запрещены.")

    def get_account_info(self) -> dict[str, Any]:
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


class Client:
    def __init__(
        self,
        name: str,
        surname: str,
        id: int,
        age: int,
        contacts: list[str] | None = None,
        status: ClientStatus = ClientStatus.ACTIVE,
    ) -> None:
        self.name = self._validate_non_empty_str(name, "name")
        self.surname = self._validate_non_empty_str(surname, "surname")
        if not isinstance(id, int):
            raise InvalidOperationError("ID клиента должен быть целым числом.")
        self.id = id
        self.age = age
        self.check_age()
        self.status = status
        self.contacts = self._validate_contacts(contacts or [])
        self.account_ids: list[str] = []

    @staticmethod
    def _validate_non_empty_str(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidOperationError(f"Поле '{field_name}' должно быть непустой строкой.")
        return value.strip()

    @staticmethod
    def _validate_contacts(contacts: list[str]) -> list[str]:
        validated: list[str] = []
        for contact in contacts:
            if not isinstance(contact, str) or not contact.strip():
                raise InvalidOperationError(
                    "Каждый контакт должен быть непустой строкой."
                )
            validated.append(contact.strip())
        return validated

    def add_account(self, account_id: str) -> None:
        if account_id not in self.account_ids:
            self.account_ids.append(account_id)

    def remove_account(self, account_id: str) -> None:
        if account_id in self.account_ids:
            self.account_ids.remove(account_id)

    def lock(self) -> None:
        self.status = ClientStatus.LOCKED

    def unlock(self) -> None:
        self.status = ClientStatus.ACTIVE

    def check_age(self) -> bool:
        if self.age < 18:
            raise InvalidOperationError("Возраст клиента должен быть не меньше 18 лет.")
        return True

    def get_client_info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "surname": self.surname,
            "id": self.id,
            "age": self.age,
            "status": self.status,
            "account_ids": self.account_ids,
            "contacts": self.contacts,
        }

    def __str__(self) -> str:
        return (
            f"Клиент: {self.name} {self.surname}, ID: {self.id}, "
            f"Возраст: {self.age}, Статус: {self.status}"
        )


class Bank:
    def __init__(
        self,
        clients: list[Client] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.clients: dict[int, Client] = {}
        self.accounts: dict[str, BankAccount] = {}
        self.failed_auth_attempts: dict[int, int] = {}
        self.suspicious_actions: list[dict[str, Any]] = []
        self._now_provider = now_provider or datetime.now

        for client in clients or []:
            self.add_client(client)

    def _mark_suspicious_action(self, client_id: int, reason: str) -> None:
        self.suspicious_actions.append(
            {
                "client_id": client_id,
                "reason": reason,
                "timestamp": self._now_provider().isoformat(timespec="seconds"),
            }
        )

    def is_quiet_hours(self, now: datetime | None = None) -> bool:
        current_hour = (now or self._now_provider()).hour
        return 0 <= current_hour < 5

    def _ensure_allowed_operation_time(self, client_id: int) -> None:
        if self.is_quiet_hours():
            self._mark_suspicious_action(client_id, "operation_during_quiet_hours")
            raise QuietHoursError()

    def _get_client(self, client_id: int) -> Client:
        client = self.clients.get(client_id)
        if client is None:
            raise InvalidOperationError("Клиент не найден.")
        return client

    def _get_account(self, account_id: str) -> BankAccount:
        account = self.accounts.get(account_id)
        if account is None:
            raise InvalidOperationError("Счет не найден.")
        return account

    def add_client(self, client: Client) -> None:
        if client.id in self.clients:
            raise InvalidOperationError("Клиент с таким ID уже существует.")
        self.clients[client.id] = client
        self.failed_auth_attempts[client.id] = 0

    def authenticate_client(self, client_id: int, is_credentials_valid: bool) -> bool:
        client = self._get_client(client_id)
        if client.status == ClientStatus.LOCKED:
            self._mark_suspicious_action(client_id, "auth_attempt_for_locked_client")
            raise InvalidOperationError("Клиент заблокирован.")

        if is_credentials_valid:
            self.failed_auth_attempts[client_id] = 0
            return True

        attempts = self.failed_auth_attempts.get(client_id, 0) + 1
        self.failed_auth_attempts[client_id] = attempts
        self._mark_suspicious_action(client_id, "failed_auth")

        if attempts >= 3:
            client.lock()
            self._mark_suspicious_action(client_id, "client_locked_after_failed_auth")
        return False

    def open_account(self, client_id: int, account: BankAccount) -> str:
        self._ensure_allowed_operation_time(client_id)
        client = self._get_client(client_id)

        if client.status != ClientStatus.ACTIVE:
            raise InvalidOperationError("Открытие счета доступно только активному клиенту.")

        account_id = account.unique_index
        if account_id in self.accounts:
            raise InvalidOperationError("Счет с таким идентификатором уже существует.")

        self.accounts[account_id] = account
        client.add_account(account_id)
        return account_id

    def close_account(self, client_id: int, account_id: str) -> None:
        self._ensure_allowed_operation_time(client_id)
        client = self._get_client(client_id)
        account = self._get_account(account_id)

        if account_id not in client.account_ids:
            self._mark_suspicious_action(client_id, "close_foreign_account_attempt")
            raise InvalidOperationError("Счет не принадлежит клиенту.")

        account.close_account()

    def freeze_account(self, client_id: int, account_id: str) -> None:
        self._ensure_allowed_operation_time(client_id)
        client = self._get_client(client_id)
        account = self._get_account(account_id)
        if account_id not in client.account_ids:
            self._mark_suspicious_action(client_id, "freeze_foreign_account_attempt")
            raise InvalidOperationError("Счет не принадлежит клиенту.")
        account.freeze_account()

    def unfreeze_account(self, client_id: int, account_id: str) -> None:
        self._ensure_allowed_operation_time(client_id)
        client = self._get_client(client_id)
        account = self._get_account(account_id)
        if account_id not in client.account_ids:
            self._mark_suspicious_action(client_id, "unfreeze_foreign_account_attempt")
            raise InvalidOperationError("Счет не принадлежит клиенту.")
        if account.account_status == AccountType.CLOSED:
            raise InvalidOperationError("Закрытый счет нельзя разморозить.")
        if account.account_status != AccountType.FROZEN:
            raise InvalidOperationError("Разморозить можно только замороженный счет.")
        account.account_status = AccountType.ACTIVE

    def search_accounts(
        self,
        client_id: int | None = None,
        status: AccountType | None = None,
        currency: Currency | None = None,
    ) -> list[BankAccount]:
        if client_id is not None:
            client = self._get_client(client_id)
            accounts = [self.accounts[acc_id] for acc_id in client.account_ids]
        else:
            accounts = list(self.accounts.values())

        result: list[BankAccount] = []
        for account in accounts:
            if status is not None and account.account_status != status:
                continue
            if currency is not None and account.currency != currency:
                continue
            result.append(account)
        return result

    def get_total_balance(self) -> float:
        total = 0.0
        for account in self.accounts.values():
            if account.account_status == AccountType.ACTIVE:
                total += account.balance
        return total

    def get_clients_ranking(self) -> list[dict[str, Any]]:
        ranking: list[dict[str, Any]] = []
        for client in self.clients.values():
            balance = sum(
                self.accounts[acc_id].balance
                for acc_id in client.account_ids
                if acc_id in self.accounts
                and self.accounts[acc_id].account_status == AccountType.ACTIVE
            )
            ranking.append(
                {
                    "client_id": client.id,
                    "name": client.name,
                    "surname": client.surname,
                    "total_balance": balance,
                }
            )
        ranking.sort(key=lambda item: (-item["total_balance"], item["client_id"]))
        return ranking

    def deposit(self, client_id: int, account_id: str, amount: float) -> None:
        self._ensure_allowed_operation_time(client_id)
        client = self._get_client(client_id)
        account = self._get_account(account_id)
        self._ensure_owned(client, account_id, "deposit_to_foreign_account_attempt")
        account.deposit(amount)

    def withdraw(self, client_id: int, account_id: str, amount: float) -> None:
        self._ensure_allowed_operation_time(client_id)
        client = self._get_client(client_id)
        account = self._get_account(account_id)
        self._ensure_owned(client, account_id, "withdraw_from_foreign_account_attempt")
        account.withdraw(amount)

    def transfer(
        self,
        client_id: int,
        sender_account_id: str,
        receiver_account_id: str,
        amount: float,
    ) -> None:
        self._ensure_allowed_operation_time(client_id)
        client = self._get_client(client_id)
        sender = self._get_account(sender_account_id)
        receiver = self._get_account(receiver_account_id)
        self._ensure_owned(client, sender_account_id, "transfer_from_foreign_account_attempt")
        sender.transfer(receiver, amount)

    def _ensure_owned(self, client: Client, account_id: str, reason: str) -> None:
        if account_id not in client.account_ids:
            self._mark_suspicious_action(client.id, reason)
            raise InvalidOperationError("Счет не принадлежит клиенту.")

    def seconds_until_open_hours(self, now: datetime | None = None) -> int:
        current = now or self._now_provider()
        if not self.is_quiet_hours(current):
            return 0
        open_at = current.replace(hour=5, minute=0, second=0, microsecond=0)
        return max(int((open_at - current).total_seconds()), 1)

