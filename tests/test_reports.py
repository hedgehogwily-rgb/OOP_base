import csv
import json
from datetime import datetime
from pathlib import Path

from src.models import (
    Bank,
    BankAccount,
    Client,
    Currency,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from src.reports import ReportBuilder


def _moment() -> datetime:
    return datetime(2026, 1, 1, 10, 0, 0)


def _ready_case() -> tuple[Bank, ReportBuilder, str]:
    moment = _moment()
    bank = Bank(now_provider=lambda: moment)
    sender = Client("Oleg", "Test", 1, 25, contacts=["+7-900-000-00-01"])
    receiver = Client("Anna", "Test", 2, 25, contacts=["+7-900-000-00-02"])
    bank.add_client(sender)
    bank.add_client(receiver)
    bank.authenticate_client(sender.id, is_credentials_valid=True)
    bank.authenticate_client(receiver.id, is_credentials_valid=True)
    sender_id = bank.open_account(
        sender.id,
        BankAccount({"name": "Oleg", "surname": "Test"}, currency=Currency.RUB),
    )
    receiver_id = bank.open_account(
        receiver.id,
        BankAccount({"name": "Anna", "surname": "Test"}, currency=Currency.RUB),
    )
    bank.deposit(sender.id, sender_id, 1000)
    bank.transfer(sender.id, sender_id, receiver_id, 200, now=moment)
    transaction = Transaction(
        type=TransactionType.TRANSFER,
        amount=200,
        currency=Currency.RUB,
        sender_account_id=sender_id,
        receiver_account_id=receiver_id,
        fee=0.0,
        status=TransactionStatus.COMPLETED,
        processed_at=moment,
        client_id=sender.id,
    )
    return bank, ReportBuilder(bank, [transaction]), sender_id


def test_reports_text_json_and_csv(tmp_path: Path) -> None:
    _, builder, _ = _ready_case()

    client_report = builder.build_client_report(1)
    bank_report = builder.build_bank_report()
    risk_report = builder.build_risk_report()

    assert client_report.kind == "client"
    assert "Клиент Oleg Test" in client_report.to_text()
    assert any(row["section"] == "account" for row in client_report.rows)
    assert any(row["section"] == "transaction" for row in client_report.rows)

    assert bank_report.kind == "bank"
    assert bank_report.rows[0]["clients"] == 2
    assert bank_report.rows[0]["total_balance_rub"] == 1000
    assert any(row["section"] == "ranking" for row in bank_report.rows)

    assert risk_report.kind == "risk"
    assert any(row["section"] == "suspicious" for row in risk_report.rows)

    json_path = tmp_path / "bank.json"
    csv_path = tmp_path / "client.csv"
    builder.export_to_json(bank_report, str(json_path))
    builder.export_to_csv(client_report, str(csv_path))

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "bank"
    assert payload["rows"][0]["accounts"] == 2

    with csv_path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["section"] == "account"
    assert any(row["section"] == "risk_profile" for row in rows)


def test_save_charts_and_balance_series(tmp_path: Path) -> None:
    bank, builder, sender_id = _ready_case()

    series = builder.balance_series(sender_id)
    assert series[0][1] == 1000
    assert series[-1][1] == bank.accounts[sender_id].balance == 800

    charts = builder.save_charts(str(tmp_path), sender_id)
    assert set(charts) == {"pie", "bar", "balance"}
    assert all(Path(path).stat().st_size > 0 for path in charts.values())


def test_empty_risk_report_exports_csv(tmp_path: Path) -> None:
    moment = _moment()
    bank = Bank(now_provider=lambda: moment)
    builder = ReportBuilder(bank, [])
    csv_path = tmp_path / "empty.csv"
    builder.export_to_csv(builder.build_risk_report(), str(csv_path))
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "section"
