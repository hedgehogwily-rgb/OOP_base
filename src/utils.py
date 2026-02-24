class DomainError(Exception):
    default_message = "Произошла ошибка."

    def __init__(self, message: str | None = None):
        message = message or self.default_message
        super().__init__(message)


class InsufficientFundsError(DomainError):
    default_message = "Недостаточно средств на счете."


class AccountFrozenError(DomainError):
    default_message = "Счет заморожен."


class AccountClosedError(DomainError):
    default_message = "Счет закрыт."


class InvalidOperationError(DomainError):
    default_message = "Недопустимая операция."