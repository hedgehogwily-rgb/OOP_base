from models import BankAccount, Currency

oleg_rub_account = BankAccount(user_data={"name": "Oleg", "surname": "Ezhikov"}, currency=Currency.RUB)
john_usd_account = BankAccount(user_data={"name": "John", "surname": "Doe"}, currency=Currency.USD)

oleg_rub_account_info = "1"
john_usd_account_info = "2"
transfer_oleg_to_john = "3"
transfer_john_to_oleg = "4"
oleg_deposit = "5"
oleg_withdraw = "6"
freeze_john_account = "7"
close_john_account = "8"
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
    f"{exit_program} - выйти из программы\n"    
)



def cli_app():
    while True:
        print(text)
        user_input = input("Введите номер операции: ")
        
        if user_input == oleg_rub_account_info:
            print(oleg_rub_account)
        elif user_input == john_usd_account_info:
            print(john_usd_account)
        elif user_input == transfer_oleg_to_john:
            try:
                amount = float(input("Введите сумму для перевода с Олега на Джона: "))
            except ValueError:
                print("Неверный ввод. Пожалуйста, введите числовое значение.")
                continue
            try:
                oleg_rub_account.transfer(john_usd_account, amount)
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
                john_usd_account.transfer(oleg_rub_account, amount)
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
                oleg_rub_account.deposit(amount)
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
                oleg_rub_account.withdraw(amount)
                print(f"Успешно снято {amount} RUB со счета Олега.")
            except Exception as e:
                print(e)
        elif user_input == freeze_john_account:
            john_usd_account.freeze_account()
            print("Счет Джона заморожен.")
        elif user_input == close_john_account:
            john_usd_account.close_account()
            print("Счет Джона закрыт.")
        elif user_input == exit_program:
            print("Выход из программы.")
            break
        else:
            print("Неверный ввод. Пожалуйста, попробуйте снова.")
            
            
if __name__ == "__main__":
    cli_app()