import csv
import importlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.models import Bank, Transaction, TransactionStatus


@dataclass(slots=True)
class Report:
    kind: str
    title: str
    rows: list[dict[str, Any]]

    def to_text(self) -> str:
        lines = [self.title, ""]
        for row in self.rows:
            parts = [f"{key}: {_cell(value)}" for key, value in row.items()]
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "title": self.title, "rows": self.rows}


def _load_pyplot() -> Any:
    matplotlib = importlib.import_module("matplotlib")
    matplotlib.use("Agg", force=True)
    return importlib.import_module("matplotlib.pyplot")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return ", ".join(f"{key}={item}" for key, item in value.items())
    return str(value)


class ReportBuilder:
    def __init__(self, bank: Bank, transactions: list[Transaction]) -> None:
        self.bank = bank
        self.transactions = transactions

    def build_client_report(self, client_id: int) -> Report:
        client = self.bank.clients[client_id]
        account_ids = set(client.account_ids)
        rows: list[dict[str, Any]] = []

        for account in self.bank.search_accounts(client_id=client_id):
            info = account.get_account_info()
            rows.append(
                {
                    "section": "account",
                    "account_id": info["unique_index"],
                    "balance": info["balance"],
                    "currency": info["currency"],
                    "status": info["account_status"],
                }
            )

        for tx in self._client_transactions(account_ids):
            rows.append(
                {
                    "section": "transaction",
                    "transaction_id": tx.id,
                    "status": tx.status.value,
                    "amount": tx.amount,
                    "currency": tx.currency.value,
                    "sender": tx.sender_account_id,
                    "receiver": tx.receiver_account_id,
                }
            )

        profile = self.bank.audit_log.get_client_risk_profile(client_id)
        rows.append(
            {
                "section": "risk_profile",
                "total_events": profile["total_events"],
                "reasons": profile["reasons"],
            }
        )
        return Report("client", f"Клиент {client.name} {client.surname}", rows)

    def build_bank_report(self) -> Report:
        rows: list[dict[str, Any]] = [
            {
                "section": "totals",
                "clients": len(self.bank.clients),
                "accounts": len(self.bank.accounts),
                "total_balance_rub": self.bank.get_total_balance(),
            }
        ]
        for place, client in enumerate(self.bank.get_clients_ranking(), start=1):
            rows.append({"section": "ranking", "place": place, **client})
        for status, count in self._status_counts().items():
            rows.append({"section": "transactions", "status": status, "count": count})
        return Report("bank", "Отчёт по банку", rows)

    def build_risk_report(self) -> Report:
        rows: list[dict[str, Any]] = []
        for event in self.bank.audit_log.get_suspicious_operations():
            rows.append(
                {
                    "section": "suspicious",
                    "timestamp": event.timestamp.isoformat(timespec="seconds"),
                    "level": event.level.value,
                    "event_type": event.event_type,
                    "message": event.message,
                    "client_id": event.client_id,
                }
            )
        for message, count in self.bank.audit_log.get_error_statistics().items():
            rows.append({"section": "errors", "message": message, "count": count})
        return Report("risk", "Отчёт по рискам", rows)

    def export_to_json(self, report: Report, path: str) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(report.to_dict(), file, ensure_ascii=False, indent=2)

    def export_to_csv(self, report: Report, path: str) -> None:
        fieldnames: list[str] = []
        for row in report.rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["section"]

        with open(path, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for row in report.rows:
                writer.writerow({key: _cell(row.get(key)) for key in fieldnames})

    def save_charts(self, directory: str, account_id: str) -> dict[str, str]:
        plt = _load_pyplot()

        os.makedirs(directory, exist_ok=True)
        paths = {
            "pie": os.path.join(directory, "statuses.png"),
            "bar": os.path.join(directory, "ranking.png"),
            "balance": os.path.join(directory, "balance.png"),
        }

        counts = self._status_counts() or {"нет операций": 1}
        figure, axis = plt.subplots()
        axis.pie(list(counts.values()), labels=list(counts.keys()), autopct="%1.0f%%")
        axis.set_title("Статусы транзакций")
        figure.savefig(paths["pie"])
        plt.close(figure)

        ranking = self.bank.get_clients_ranking()
        labels = [f"{row['name']} {row['surname']}" for row in ranking] or [
            "нет данных"
        ]
        values = [row["total_balance"] for row in ranking] or [0]
        figure, axis = plt.subplots()
        axis.bar(labels, values)
        axis.set_title("Балансы клиентов")
        figure.savefig(paths["bar"])
        plt.close(figure)

        series = self.balance_series(account_id)
        figure, axis = plt.subplots()
        axis.plot([point[0] for point in series], [point[1] for point in series])
        axis.set_title("Движение баланса")
        figure.autofmt_xdate()
        figure.savefig(paths["balance"])
        plt.close(figure)
        return paths

    def balance_series(self, account_id: str) -> list[tuple[datetime, float]]:
        account = self.bank.accounts[account_id]
        done = [
            tx
            for tx in self.transactions
            if tx.status == TransactionStatus.COMPLETED
            and account_id in (tx.sender_account_id, tx.receiver_account_id)
            and tx.processed_at is not None
        ]
        done.sort(key=lambda tx: tx.processed_at or datetime.min)

        effects = [self._balance_effect(account_id, tx) for tx in done]
        balance = account.balance - sum(effects)
        if not done:
            return [(self.bank._now_provider(), account.balance)]

        first_at = done[0].processed_at
        assert first_at is not None
        points = [(first_at - timedelta(seconds=1), balance)]
        for tx, effect in zip(done, effects, strict=True):
            balance += effect
            processed_at = tx.processed_at
            assert processed_at is not None
            points.append((processed_at, balance))
        return points

    def _client_transactions(self, account_ids: set[str]) -> list[Transaction]:
        return [
            tx
            for tx in self.transactions
            if tx.sender_account_id in account_ids
            or tx.receiver_account_id in account_ids
        ]

    def _status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tx in self.transactions:
            status = tx.status.value
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _balance_effect(self, account_id: str, tx: Transaction) -> float:
        account = self.bank.accounts[account_id]
        if tx.sender_account_id == account_id:
            return -(tx.amount + tx.fee)
        sender = self.bank.accounts[tx.sender_account_id]
        return sender.currency_conversion(account.currency, tx.amount)
