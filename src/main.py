import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from src.models import (
    AuditLog,
    Bank,
    BankAccount,
    Client,
    Currency,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
    Transaction,
    TransactionProcessor,
    TransactionQueue,
)
from src.utils import InvalidOperationError

logger = logging.getLogger(__name__)


def _ensure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")


def show_client_accounts(bank: Bank, client_id: int) -> None:
    client = bank.clients[client_id]
    logger.info(
        "--- Счета клиента %s %s (id=%s) ---",
        client.name,
        client.surname,
        client_id,
    )
    for account in bank.search_accounts(client_id=client_id):
        info = account.get_account_info()
        logger.info(
            "  %s | %s | %.2f %s | %s",
            info["unique_index"],
            info.get("account_type", "BankAccount"),
            info["balance"],
            info["currency"],
            info["account_status"],
        )


def show_client_history(
    bank: Bank, transactions: list[Transaction], client_id: int
) -> None:
    client = bank.clients[client_id]
    account_ids = set(client.account_ids)
    related = [
        tx
        for tx in transactions
        if tx.sender_account_id in account_ids or tx.receiver_account_id in account_ids
    ]
    logger.info(
        "--- История транзакций клиента id=%s (%s шт.) ---",
        client_id,
        len(related),
    )
    for tx in related:
        logger.info(
            "  %s | %s | %.2f %s | %s -> %s | reason=%s",
            tx.id,
            tx.status.value,
            tx.amount,
            tx.currency.value,
            tx.sender_account_id,
            tx.receiver_account_id,
            tx.failure_reason,
        )


def show_transaction_statistics(transactions: list[Transaction]) -> dict[str, int]:
    stats = dict(Counter(tx.status.value for tx in transactions))
    logger.info("--- Статистика транзакций ---")
    for status, count in sorted(stats.items()):
        logger.info("  %s: %s", status, count)
    return stats


def show_top_clients(bank: Bank, n: int = 3) -> None:
    logger.info("--- Топ-%s клиентов по балансу ---", n)
    for rank, row in enumerate(bank.get_clients_ranking()[:n], start=1):
        logger.info(
            "  %s. %s %s (id=%s): %.2f %s",
            rank,
            row["name"],
            row["surname"],
            row["client_id"],
            row["total_balance"],
            row["currency"],
        )


def show_suspicious(audit_log: AuditLog, bank: Bank) -> None:
    logger.info("--- Подозрительные операции (аудит) ---")
    for event in audit_log.get_suspicious_operations():
        logger.info(
            "  %s | %s | %s | %s",
            event.timestamp.isoformat(timespec="seconds"),
            event.event_type,
            event.level.value,
            event.message,
        )
        if event.metadata.get("reasons"):
            logger.info("    причины: %s", ", ".join(event.metadata["reasons"]))

    logger.info("--- Подозрительные действия банка ---")
    for action in bank.suspicious_actions:
        logger.info(
            "  %s | client=%s | %s",
            action["timestamp"],
            action["client_id"],
            action["reason"],
        )


def log_wave_summary(wave_name: str, transactions: list[Transaction]) -> None:
    logger.info("=== %s ===", wave_name)
    for tx in transactions:
        logger.info(
            "  %s | priority=%s | status=%s | attempt=%s | fee=%.2f | reason=%s",
            tx.id,
            tx.priority,
            tx.status.value,
            tx.attempt,
            tx.fee,
            tx.failure_reason,
        )


def _add_tx(
    processor: TransactionProcessor,
    bank: Bank,
    all_transactions: list[Transaction],
    sender_id: str,
    receiver_id: str,
    amount: float,
    **kwargs: Any,
) -> Transaction:
    owner = bank.find_account_owner(sender_id)
    if owner is None:
        raise InvalidOperationError("Владелец счета отправителя не найден.")
    tx = processor.create_transfer(owner.id, sender_id, receiver_id, amount, **kwargs)
    all_transactions.append(tx)
    return tx


def run_day6_demo(audit_log_path: str | None = None) -> dict[str, Any]:
    _ensure_logging()
    day_time = datetime(2026, 1, 1, 10, 0, 0)
    wave1_time = day_time + timedelta(hours=1)
    night_time = datetime(2026, 1, 2, 2, 0, 0)
    wave3_time = datetime(2026, 1, 2, 10, 0, 0)
    current_time = day_time

    def fixed_now() -> datetime:
        return current_time

    audit_log = AuditLog(file_path=audit_log_path)
    bank = Bank(
        now_provider=fixed_now,
        audit_log=audit_log,
        external_transfer_fee_rate=0.03,
    )
    queue = TransactionQueue()
    processor = TransactionProcessor(
        bank=bank,
        queue=queue,
        external_transfer_fee_rate=0.03,
        retry_delay_seconds=0,
        now_provider=fixed_now,
        audit_log=bank.audit_log,
        risk_analyzer=bank.risk_analyzer,
    )
    all_transactions: list[Transaction] = []

    # --- Фаза 2: 7 клиентов, 12 счетов ---
    clients = [
        Client("Oleg", "Ezhikov", 1, 28, contacts=["+7-900-000-00-01"]),
        Client("John", "Doe", 2, 31, contacts=["+7-900-000-00-02"]),
        Client("Ivan", "Ivanov", 3, 26, contacts=["+7-900-000-00-03"]),
        Client("Anna", "Smirnova", 4, 24, contacts=["+7-900-000-00-04"]),
        Client("Mike", "Brown", 5, 35, contacts=["+7-900-000-00-05"]),
        Client("Kate", "Lee", 6, 29, contacts=["+7-900-000-00-06"]),
        Client("Alex", "Kim", 7, 22, contacts=["+7-900-000-00-07"]),
    ]
    for client in clients:
        bank.add_client(client)

    for client_id in range(1, 8):
        bank.authenticate_client(client_id, is_credentials_valid=True)

    acc: dict[str, str] = {}
    acc["oleg_rub"] = bank.open_account(
        1, BankAccount({"name": "Oleg", "surname": "Ezhikov"}, currency=Currency.RUB)
    )
    acc["oleg_sav"] = bank.open_account(
        1, SavingsAccount({"name": "Oleg", "surname": "Ezhikov"}, currency=Currency.RUB)
    )
    acc["john_usd"] = bank.open_account(
        2, BankAccount({"name": "John", "surname": "Doe"}, currency=Currency.USD)
    )
    acc["john_rub"] = bank.open_account(
        2, BankAccount({"name": "John", "surname": "Doe"}, currency=Currency.RUB)
    )
    acc["ivan_prem"] = bank.open_account(
        3, PremiumAccount({"name": "Ivan", "surname": "Ivanov"}, currency=Currency.RUB)
    )
    acc["anna_sav"] = bank.open_account(
        4,
        SavingsAccount({"name": "Anna", "surname": "Smirnova"}, currency=Currency.RUB),
    )
    acc["mike_prem"] = bank.open_account(
        5, PremiumAccount({"name": "Mike", "surname": "Brown"}, currency=Currency.RUB)
    )
    acc["mike_usd"] = bank.open_account(
        5, BankAccount({"name": "Mike", "surname": "Brown"}, currency=Currency.USD)
    )
    acc["kate_inv"] = bank.open_account(
        6,
        InvestmentAccount({"name": "Kate", "surname": "Lee"}, currency=Currency.RUB),
    )
    acc["kate_eur"] = bank.open_account(
        6, BankAccount({"name": "Kate", "surname": "Lee"}, currency=Currency.EUR)
    )
    acc["alex_inv"] = bank.open_account(
        7, InvestmentAccount({"name": "Alex", "surname": "Kim"}, currency=Currency.RUB)
    )
    acc["alex_rub"] = bank.open_account(
        7, BankAccount({"name": "Alex", "surname": "Kim"}, currency=Currency.RUB)
    )

    bank.deposit(1, acc["oleg_rub"], 500_000)
    bank.deposit(1, acc["oleg_sav"], 50_000)
    bank.deposit(2, acc["john_usd"], 2_000)
    bank.deposit(2, acc["john_rub"], 30_000)
    bank.deposit(3, acc["ivan_prem"], 15_000)
    bank.deposit(4, acc["anna_sav"], 80_000)
    bank.deposit(5, acc["mike_prem"], 25_000)
    bank.deposit(5, acc["mike_usd"], 500)
    bank.deposit(6, acc["kate_inv"], 100_000)
    bank.deposit(6, acc["kate_eur"], 1_000)
    bank.deposit(7, acc["alex_inv"], 60_000)
    bank.deposit(7, acc["alex_rub"], 10_000)

    bank.freeze_account(2, acc["john_usd"])

    # --- Фаза 3: ~40 транзакций по категориям ---

    # Успешные (~15)
    for _, (sender, receiver, amount, prio) in enumerate(
        [
            (acc["oleg_rub"], acc["ivan_prem"], 5_000, 5),
            (acc["oleg_rub"], acc["anna_sav"], 3_000, 3),
            (acc["ivan_prem"], acc["oleg_rub"], 1_200, 7),
            (acc["anna_sav"], acc["mike_prem"], 2_500, 4),
            (acc["mike_prem"], acc["kate_inv"], 4_000, 6),
            (acc["kate_inv"], acc["alex_inv"], 2_000, 2),
            (acc["alex_inv"], acc["oleg_sav"], 1_500, 8),
            (acc["oleg_rub"], acc["john_rub"], 1_000, 1),
            (acc["john_rub"], acc["oleg_rub"], 500, 9),
            (acc["mike_prem"], acc["anna_sav"], 800, 10),
            (acc["kate_inv"], acc["ivan_prem"], 600, 2),
            (acc["alex_rub"], acc["mike_prem"], 400, 3),
            (acc["oleg_sav"], acc["kate_inv"], 700, 4),
            (acc["ivan_prem"], acc["alex_rub"], 300, 5),
            (acc["anna_sav"], acc["oleg_rub"], 1_100, 6),
        ],
        start=1,
    ):
        _add_tx(
            processor, bank, all_transactions, sender, receiver, amount, priority=prio
        )

    # Очередь: отложенные и приоритеты
    delayed_tx = _add_tx(
        processor,
        bank,
        all_transactions,
        acc["kate_inv"],
        acc["alex_rub"],
        500,
        priority=10,
        scheduled_at=datetime(2026, 1, 2, 8, 0, 0),
    )
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["oleg_rub"],
        acc["mike_prem"],
        200,
        priority=1,
        scheduled_at=day_time + timedelta(minutes=30),
    )

    # Ошибочные (~10)
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["oleg_rub"],
        acc["ivan_prem"],
        999_999,
        max_attempts=1,
        priority=5,
    )
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["alex_rub"],
        acc["oleg_rub"],
        50_000,
        max_attempts=1,
        priority=3,
    )
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["john_usd"],
        acc["oleg_rub"],
        100,
        max_attempts=1,
        priority=8,
    )
    cancel_tx = _add_tx(
        processor,
        bank,
        all_transactions,
        acc["oleg_rub"],
        acc["anna_sav"],
        500,
        priority=2,
    )
    queue.cancel(cancel_tx.id, now=day_time)

    # Подозрительные: крупная сумма
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["oleg_rub"],
        acc["kate_inv"],
        150_000_000,
        max_attempts=1,
        priority=10,
    )

    # Подозрительные: частые операции (6 неудачных подряд)
    for _ in range(6):
        _add_tx(
            processor,
            bank,
            all_transactions,
            acc["alex_rub"],
            acc["ivan_prem"],
            500,
            max_attempts=1,
            priority=1,
        )

    # LOCKED-клиент
    for _ in range(3):
        bank.authenticate_client(7, is_credentials_valid=False)
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["alex_rub"],
        acc["oleg_rub"],
        100,
        max_attempts=1,
        priority=7,
    )

    # Подозрительные: новые получатели (автоматически через первые переводы)
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["oleg_rub"],
        acc["kate_eur"],
        300,
        priority=4,
    )
    _add_tx(
        processor,
        bank,
        all_transactions,
        acc["mike_usd"],
        acc["john_rub"],
        50,
        priority=3,
    )

    # Дополнительные успешные переводы
    for sender, receiver, amount in [
        (acc["ivan_prem"], acc["anna_sav"], 450),
        (acc["anna_sav"], acc["alex_inv"], 600),
        (acc["mike_prem"], acc["oleg_sav"], 350),
        (acc["kate_inv"], acc["mike_prem"], 500),
    ]:
        _add_tx(processor, bank, all_transactions, sender, receiver, amount, priority=2)

    logger.info("=== День 6: демонстрация банковской системы ===")
    logger.info(
        "Создано клиентов: %s, счетов: %s", len(bank.clients), len(bank.accounts)
    )
    logger.info("Создано транзакций (до ночных): %s", len(all_transactions))

    # --- Фаза 4: обработка волнами ---
    bank.unfreeze_account(2, acc["john_usd"])

    current_time = wave1_time
    wave1 = processor.process_all(now=wave1_time)
    log_wave_summary("Волна 1: дневные транзакции (11:00)", wave1)

    # Ночные — создаём после волны 1, обрабатываем ночью
    night_txs = [
        _add_tx(
            processor,
            bank,
            all_transactions,
            acc["oleg_rub"],
            acc["ivan_prem"],
            200,
            priority=5,
        ),
        _add_tx(
            processor,
            bank,
            all_transactions,
            acc["anna_sav"],
            acc["mike_prem"],
            150,
            priority=3,
        ),
        _add_tx(
            processor,
            bank,
            all_transactions,
            acc["ivan_prem"],
            acc["oleg_rub"],
            100,
            priority=7,
        ),
        _add_tx(
            processor,
            bank,
            all_transactions,
            acc["mike_prem"],
            acc["kate_inv"],
            250,
            priority=2,
        ),
        _add_tx(
            processor,
            bank,
            all_transactions,
            acc["kate_inv"],
            acc["alex_rub"],
            180,
            priority=6,
        ),
    ]
    logger.info(
        "Добавлено ночных транзакций: %s, всего: %s",
        len(night_txs),
        len(all_transactions),
    )

    current_time = night_time
    wave2 = processor.process_all(now=night_time)
    log_wave_summary("Волна 2: ночные транзакции (02:00)", wave2)

    current_time = wave3_time
    wave3 = processor.process_all(now=wave3_time)
    log_wave_summary("Волна 3: отложенные и оставшиеся (10:00)", wave3)

    logger.info("--- Лог ошибок процессора ---")
    for row in processor.error_log:
        logger.info("  %s", row)

    # --- Фаза 5: пользовательские сценарии и отчёты ---
    show_client_accounts(bank, client_id=1)
    show_client_history(bank, queue.all_transactions(), client_id=1)

    show_suspicious(audit_log, bank)
    show_top_clients(bank, n=3)

    logger.info("--- Общий баланс банка: %.2f RUB ---", bank.get_total_balance())

    stats = show_transaction_statistics(queue.all_transactions())

    logger.info("--- Статистика ошибок аудита ---")
    for message, count in audit_log.get_error_statistics().items():
        logger.info("  %s: %s", message, count)

    if audit_log_path is not None:
        audit_log.save_to_file()
        logger.info("Аудит сохранён в %s", audit_log_path)

    return {
        "clients": len(bank.clients),
        "accounts": len(bank.accounts),
        "transactions": len(all_transactions),
        "stats": stats,
        "suspicious_count": len(audit_log.get_suspicious_operations()),
        "ranking": bank.get_clients_ranking()[:3],
        "total_balance": bank.get_total_balance(),
        "delayed_tx_status": delayed_tx.status,
        "night_tx_statuses": [tx.status for tx in night_txs],
    }


def run_day4_demo(audit_log_path: str | None = None) -> None:
    _ensure_logging()

    def fixed_now() -> datetime:
        return datetime(2026, 1, 1, 10, 0, 0)

    audit_log = AuditLog(file_path=audit_log_path)
    bank = Bank(
        now_provider=fixed_now,
        audit_log=audit_log,
        external_transfer_fee_rate=0.03,
    )
    queue = TransactionQueue()
    processor = TransactionProcessor(
        bank=bank,
        queue=queue,
        external_transfer_fee_rate=0.03,
        retry_delay_seconds=0,
        now_provider=fixed_now,
        audit_log=bank.audit_log,
        risk_analyzer=bank.risk_analyzer,
    )

    oleg = Client("Oleg", "Ezhikov", 1, 28, contacts=["+7-900-000-00-01"])
    john = Client("John", "Doe", 2, 31, contacts=["+7-900-000-00-02"])
    ivan = Client("Ivan", "Ivanov", 3, 26, contacts=["+7-900-000-00-03"])
    bank.add_client(oleg)
    bank.add_client(john)
    bank.add_client(ivan)

    for client_id in (oleg.id, john.id, ivan.id):
        bank.authenticate_client(client_id, is_credentials_valid=True)

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

    bank.deposit(oleg.id, oleg_account_id, 10_000)
    bank.deposit(john.id, john_account_id, 400)
    bank.deposit(ivan.id, ivan_account_id, 200)
    bank.freeze_account(john.id, john_account_id)

    now = datetime(2026, 1, 1, 10, 0, 0)
    transactions = [
        processor.create_transfer(
            oleg.id, oleg_account_id, ivan_account_id, 1200, priority=5
        ),
        processor.create_transfer(
            oleg.id, oleg_account_id, john_account_id, 100, priority=9
        ),
        processor.create_transfer(
            ivan.id, ivan_account_id, oleg_account_id, 700, priority=7
        ),
        processor.create_transfer(
            john.id, john_account_id, oleg_account_id, 50, priority=4
        ),
        processor.create_transfer(
            oleg.id,
            oleg_account_id,
            ivan_account_id,
            200,
            priority=8,
            scheduled_at=now + timedelta(minutes=15),
        ),
        processor.create_transfer(
            oleg.id, oleg_account_id, ivan_account_id, 150, priority=3
        ),
        processor.create_transfer(
            ivan.id, ivan_account_id, john_account_id, 80, priority=6
        ),
        processor.create_transfer(
            oleg.id, oleg_account_id, john_account_id, 60, priority=2
        ),
        processor.create_transfer(
            oleg.id, oleg_account_id, ivan_account_id, 90, priority=1
        ),
        processor.create_transfer(
            ivan.id, ivan_account_id, oleg_account_id, 1800, priority=10
        ),
    ]

    queue.cancel(transactions[8].id, now=now)
    first_wave = processor.process_all(now=now)
    bank.unfreeze_account(john.id, john_account_id)
    second_wave = processor.process_all(now=now + timedelta(minutes=20))

    logger.info("Обработано в первой волне: %s", len(first_wave))
    logger.info("Обработано во второй волне: %s", len(second_wave))
    logger.info("Итоги транзакций:")
    for transaction in transactions:
        logger.info(
            "%s | priority=%s | status=%s | attempt=%s | fee=%.2f | reason=%s",
            transaction.id,
            transaction.priority,
            transaction.status.value,
            transaction.attempt,
            transaction.fee,
            transaction.failure_reason,
        )

    logger.info("Баланс счетов:")
    logger.info("Oleg: %.2f RUB", bank.accounts[oleg_account_id].balance)
    logger.info("John: %.2f USD", bank.accounts[john_account_id].balance)
    logger.info("Ivan: %.2f RUB", bank.accounts[ivan_account_id].balance)
    logger.info("Лог ошибок:")
    for log_row in processor.error_log:
        logger.info("%s", log_row)

    logger.info("Подозрительные операции:")
    for event in audit_log.get_suspicious_operations():
        logger.info(
            "%s | %s | %s | %s",
            event.timestamp.isoformat(timespec="seconds"),
            event.event_type,
            event.level.value,
            event.message,
        )

    logger.info("Статистика ошибок аудита:")
    for message, count in audit_log.get_error_statistics().items():
        logger.info("%s: %s", message, count)


if __name__ == "__main__":
    run_day6_demo()
