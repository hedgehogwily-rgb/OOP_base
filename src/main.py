from src.models import Bank, BankAccount, Client, Currency

bank = Bank()
oleg_client = Client(
    name="Oleg",
    surname="Ezhikov",
    id=1,
    age=28,
    contacts=["+7-900-000-00-01"],
)
john_client = Client(
    name="John",
    surname="Doe",
    id=2,
    age=31,
    contacts=["+7-900-000-00-02"],
)
bank.add_client(oleg_client)
bank.add_client(john_client)

oleg_account_id = bank.open_account(
    client_id=oleg_client.id,
    account=BankAccount(
        user_data={"name": oleg_client.name, "surname": oleg_client.surname},
        currency=Currency.RUB,
    ),
)
john_account_id = bank.open_account(
    client_id=john_client.id,
    account=BankAccount(
        user_data={"name": john_client.name, "surname": john_client.surname},
        currency=Currency.USD,
    ),
)

oleg_rub_account_info = "1"
john_usd_account_info = "2"
transfer_oleg_to_john = "3"
transfer_john_to_oleg = "4"
oleg_deposit = "5"
oleg_withdraw = "6"
freeze_john_account = "7"
close_john_account = "8"
auth_john_fail = "9"
auth_john_success = "10"
exit_program = "0"


text = (
    f"{oleg_rub_account_info} - получить информацию о счете Олега\n"
    f"{john_usd_account_info} - получить информацию о счете Джона\n"
    f"{transfer_oleg_to_john} - перевести деньги с счета Олега на счет Джона\n"
    f"{transfer_john_to_oleg} - перевести деньги с счета Джона на счет Олега\n"
    f"{oleg_deposit} - пополнить счет Олега\n"
    f"{oleg_withdraw} - снять деньги со счета Олега\n"
    f"{freeze_john_account} - заморозить счет Джона\n"
    f"{close_john_account} - закрыть счет Джона\n"
    f"{auth_john_fail} - неудачная авторизация Джона\n"
    f"{auth_john_success} - успешная авторизация Джона\n"
    f"{exit_program} - выйти из программы\n"
)


def cli_app() -> None:
    oleg_account = bank.accounts[oleg_account_id]
    john_account = bank.accounts[john_account_id]

    while True:
        print(text)
        user_input = input("Введите номер операции: ")

        if user_input == oleg_rub_account_info:
            print(oleg_account)
        elif user_input == john_usd_account_info:
            print(john_account)
        elif user_input == transfer_oleg_to_john:
            try:
                amount = float(input("Введите сумму для перевода с Олега на Джона: "))
            except ValueError:
                print("Неверный ввод. Пожалуйста, введите числовое значение.")
                continue
            try:
                oleg_account.transfer(john_account, amount)
                print(f"Успешно переведено {amount} RUB с Олега на Джона.")
            except Exception as e:
                print(e)
        elif user_input == transfer_john_to_oleg:
            try:
                amount = float(input("Введите сумму для перевода с Джона на Олега: "))
            except ValueError:
                print("Неверный ввод. Пожалуйста, введите числовое значение.")
                continue
            try:
                john_account.transfer(oleg_account, amount)
                print(f"Успешно переведено {amount} USD с Джона на Олега.")
            except Exception as e:
                print(e)
        elif user_input == oleg_deposit:
            try:
                amount = float(input("Введите сумму для пополнения счета Олега: "))
            except ValueError:
                print("Неверный ввод. Пожалуйста, введите числовое значение.")
                continue
            try:
                oleg_account.deposit(amount)
                print(f"Успешно пополнено {amount} RUB на счет Олега.")
            except Exception as e:
                print(e)
        elif user_input == oleg_withdraw:
            try:
                amount = float(input("Введите сумму для снятия со счета Олега: "))
            except ValueError:
                print("Неверный ввод. Пожалуйста, введите числовое значение.")
                continue
            try:
                oleg_account.withdraw(amount)
                print(f"Успешно снято {amount} RUB со счета Олега.")
            except Exception as e:
                print(e)
        elif user_input == freeze_john_account:
            try:
                bank.freeze_account(john_client.id, john_account_id)
                print("Счет Джона заморожен.")
            except Exception as e:
                print(e)
        elif user_input == close_john_account:
            try:
                bank.close_account(john_client.id, john_account_id)
                print("Счет Джона закрыт.")
            except Exception as e:
                print(e)
        elif user_input == auth_john_fail:
            auth_result = bank.authenticate_client(john_client.id, is_credentials_valid=False)
            print(f"Авторизация Джона: {auth_result}")
        elif user_input == auth_john_success:
            try:
                auth_result = bank.authenticate_client(
                    john_client.id, is_credentials_valid=True
                )
                print(f"Авторизация Джона: {auth_result}")
            except Exception as e:
                print(e)
        elif user_input == exit_program:
            print("Выход из программы.")
            break
        else:
            print("Неверный ввод. Пожалуйста, попробуйте снова.")


if __name__ == "__main__":
    cli_app()
