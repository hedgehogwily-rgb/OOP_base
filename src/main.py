from datetime import datetime, timedelta

from src.models import (
    Bank,
    BankAccount,
    Client,
    Currency,
    PremiumAccount,
    TransactionProcessor,
    TransactionQueue,
)


def run_day4_demo() -> None:
    bank = Bank(now_provider=lambda: datetime(2026, 1, 1, 10, 0, 0))
    queue = TransactionQueue()
    processor = TransactionProcessor(
        bank=bank,
        queue=queue,
        external_transfer_fee_rate=0.03,
        retry_delay_seconds=0,
    )

    oleg = Client("Oleg", "Ezhikov", 1, 28, contacts=["+7-900-000-00-01"])
    john = Client("John", "Doe", 2, 31, contacts=["+7-900-000-00-02"])
    ivan = Client("Ivan", "Ivanov", 3, 26, contacts=["+7-900-000-00-03"])
    bank.add_client(oleg)
    bank.add_client(john)
    bank.add_client(ivan)

    oleg_account_id = bank.open_account(
        oleg.id,
        BankAccount({"name": "Oleg", "surname": "Ezhikov"}, currency=Currency.RUB),
    )
    john_account_id = bank.open_account(
        john.id,
        BankAccount({"name": "John", "surname": "Doe"}, currency=Currency.USD),
    )
    ivan_account_id = bank.open_account(
        ivan.id,
        PremiumAccount({"name": "Ivan", "surname": "Ivanov"}, currency=Currency.RUB),
    )

    bank.accounts[oleg_account_id].deposit(10_000)
    bank.accounts[john_account_id].deposit(400)
    bank.accounts[ivan_account_id].deposit(200)
    bank.freeze_account(john.id, john_account_id)

    now = datetime(2026, 1, 1, 10, 0, 0)
    transactions = [
        processor.create_transfer(oleg_account_id, ivan_account_id, 1200, priority=5),
        processor.create_transfer(oleg_account_id, john_account_id, 100, priority=9),
        processor.create_transfer(ivan_account_id, oleg_account_id, 700, priority=7),
        processor.create_transfer(john_account_id, oleg_account_id, 50, priority=4),
        processor.create_transfer(
            oleg_account_id,
            ivan_account_id,
            200,
            priority=8,
            scheduled_at=now + timedelta(minutes=15),
        ),
        processor.create_transfer(oleg_account_id, ivan_account_id, 150, priority=3),
        processor.create_transfer(ivan_account_id, john_account_id, 80, priority=6),
        processor.create_transfer(oleg_account_id, john_account_id, 60, priority=2),
        processor.create_transfer(oleg_account_id, ivan_account_id, 90, priority=1),
        processor.create_transfer(ivan_account_id, oleg_account_id, 1800, priority=10),
    ]

    queue.cancel(transactions[8].id, now=now)
    first_wave = processor.process_all(now=now)
    bank.unfreeze_account(john.id, john_account_id)
    second_wave = processor.process_all(now=now + timedelta(minutes=20))

    print(f"Обработано в первой волне: {len(first_wave)}")
    print(f"Обработано во второй волне: {len(second_wave)}")
    print("\nИтоги транзакций:")
    for transaction in transactions:
        print(
            f"{transaction.id} | priority={transaction.priority} | "
            f"status={transaction.status.value} | attempt={transaction.attempt} | "
            f"fee={transaction.fee:.2f} | reason={transaction.failure_reason}"
        )

    print("\nБаланс счетов:")
    print(f"Oleg: {bank.accounts[oleg_account_id].balance:.2f} RUB")
    print(f"John: {bank.accounts[john_account_id].balance:.2f} USD")
    print(f"Ivan: {bank.accounts[ivan_account_id].balance:.2f} RUB")
    print("\nЛог ошибок:")
    for log_row in processor.error_log:
        print(log_row)


if __name__ == "__main__":
    run_day4_demo()
