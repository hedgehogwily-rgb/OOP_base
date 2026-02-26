from src.models import BankAccount, AccountType, Currency


#Не уверен что конкретно нужно в тестах. Или нужен pytest?


def tests():
    #➕ создание активного и замороженного счёта
    
    active_account = BankAccount(user_data={"name": "Alice", "surname": "Smith"}, currency=Currency.USD)
    frozen_account = BankAccount(user_data={"name": "Bob", "surname": "Johnson"}, currency=Currency.EUR, account_status=AccountType.FROZEN)
    
    print("Активный счет:", active_account)
    print("Замороженный счет:", frozen_account)
    
    try:
        incorrect_currency_account = BankAccount(user_data={"name": "Eve", "surname": "Davis"}, currency="GBP")
        print("Счет с некорректной валютой:", incorrect_currency_account)
    except Exception as e:
        print("Ошибка при создании счета с некорректной валютой:", e)
    
    
    #🚫 попытка операций над замороженным счётом
    
    try:
        frozen_account.deposit(100)
    except Exception as e:
        print("Ошибка пополнения замороженного счета:", e)
        
    try:
        active_account.withdraw(50)
        active_account.transfer(counterparty=frozen_account, amount=50)
    except Exception as e:
        print("Ошибка перевода на замороженный счет:", e)
        
        
    #✅ валидное пополнение и снятие
    
    second_active_account = BankAccount(user_data={"name": "Charlie", "surname": "Brown"}, currency=Currency.RUB)
    second_active_account.deposit(200)
    print("Баланс второго активного счета после пополнения:", second_active_account.balance)
    
    try:
        second_active_account.transfer(counterparty=active_account, amount=50)
        print("Баланс второго активного счета после перевода:", second_active_account.balance)
        print("Баланс первого активного счета после получения перевода:", active_account.balance)
    except Exception as e:
        print("Ошибка перевода между активными счетами:", e)
        
        
    try:
        second_active_account.withdraw(300)
        print("Баланс второго активного счета после снятия:", second_active_account.balance)
    except Exception as e:
        print("Ошибка при попытке снятия:", e)
        
    try:
        second_active_account.withdraw(150)
        print("Баланс второго активного счета после снятия:", second_active_account.balance)
    except Exception as e:
        print("Ошибка при попытке снятия:", e)
    
    
if __name__ == "__main__":
    tests()