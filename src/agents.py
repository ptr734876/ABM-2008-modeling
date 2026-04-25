import mesa
import numpy as np
import sqlite3
from config import ModelConfig
from db_manipulator import *

class Household(mesa.Agent):
    # конструктор агента домохозяйства
    def __init__(self, model, unique_id, income, family_size):
        super().__init__(model=model)
        self.unique_id = unique_id 
        self.income = income
        self.original_income = income # сохранить оригинальный доход
        self.family_size = family_size 
        self.has_mortgage = False # есть ли ипотека  
        self.mortgage_amount = 0 # сколько еще надо выплатить 
        self.interest_rate = 0 # процентная ставка
        self.delinquency_months = 0 # просрочка в месяцах
        self.defaulted = False # в дефолте ли
        self.monthly_payment = 0 # расчет месячного платежа
        self.is_unemployed = False
        self.savings = income * 0.5
    
    # расчет необходимых средств на жизнь
    def calculate_essential_expenses(self):
        return ModelConfig.MONTHLY_EXPENSES_PER_PERSON * self.family_size
    
    # расчет ежемесячного платежа
    def calculate_monthly_payment(self):
        # если нет ипотеки или она уже оплачена не надо платить
        if not self.has_mortgage or self.mortgage_amount <= 0:
            return 0 
        
        return ModelConfig.calculate_monthly_payment(
            self.mortgage_amount,
            self.interest_rate,
            ModelConfig.MORTGAGE_CONFIG['term_months']
        )  

    # наложение кризиса в зависимости от его прогресса
    def apply_crisis_effects(self):
        crisis = ModelConfig.CRISIS_CONFIG
        if not crisis['enabled'] or self.model.steps < crisis['start_step']:
            return

        progress = ModelConfig.get_crisis_progress(self)
        current_unemployment_rate = crisis['unemployment_rate'] * progress

        # 1. Эффект безработицы нарастает постепенно
        current_unemployment_rate = crisis['unemployment_rate'] * progress
        if np.random.random() < current_unemployment_rate and not self.is_unemployed:
            # 2. Снижение дохода также нарастает постепенно
            self.is_unemployed = True
            self.income = self.original_income * (1 - crisis['income_reduction'] * progress)
        elif self.is_unemployed:
            pass

    # логика выплат платежей
    def pay_mortgage(self): 
        # если нет ипотеки то не надо платить
        if not self.has_mortgage or self.defaulted:
            return
        
        self.apply_crisis_effects()

        # расчет аннуитетного платежа и расходов на каждого члена домохозяйства в месяц 
        monthly_payment = self.calculate_monthly_payment()
        essential_expenses = self.calculate_essential_expenses()
        monthly_income = self.income / 12
        
        total_needed = essential_expenses + monthly_payment
        available = monthly_income = self.savings


        # если денег хватает и на платеж и на расходы домохозяйства
        if available >= total_needed:
            # совершаем платеж
            self.mortgage_amount -= monthly_payment
            # вычисление того что будет откладываться
            self.savings -= max(0, total_needed - monthly_income)
            # просрочка 0 месяцев
            self.delinquency_months = 0

            # если ипотека полностью выплачена
            if self.mortgage_amount <= 0:
                self.has_mortgage = False
                self.mortgage_amount = 0

        # если не хватает на полный платеж, то есть возможность выплатить меньше (половину)
        elif available >= essential_expenses + monthly_payment * 0.5:

            partial_payment = monthly_payment * 0.5
            self.mortgage_amount -= partial_payment
            self.savings -= max(0, essential_expenses + partial_payment - monthly_income)
            # тогда и просрочка вырастает на половирну
            self.delinquency_months += 0.5
        else:
            # если не получается платить тогда увелисивается просрочка
            self.delinquency_months += 1
            self.savings -= max(0, essential_expenses - monthly_income)
            # проверка на соответствие дефолту и просвоение его
            if self.delinquency_months >= ModelConfig.MORTGAGE_CONFIG['delinquency_limit']:
                self.defaulted = True

                # регистрируем дефолт для агента, если это основной банк
                for agent in self.model.all_agents:
                    if isinstance(agent, Bank) and agent.unique_id == self.model.primary_bank_id:
                        agent.register_default(self)

        self.savings = max(0, self.savings)

        if not self.defaulted and monthly_income > total_needed:
            self.savings += monthly_income - total_needed
    
    # логика каждого шага моделирования
    def step(self):
        self.pay_mortgage()

# конструктор агента банка
class Bank(mesa.Agent):
    def __init__(self, model, unique_id, capital):
        super().__init__(model=model)
        self.unique_id = unique_id
        self.capital = capital # сумма капитала банка
        self.initial_capital = capital
        self.mortgages = [] # все ипотеки в банке (список картежей)
        self.defaults_count = 0 # количество дефолтов среди клиентов банка
        self.base_interest_rate = ModelConfig.INTEREST_RATES['base_rate'] # процентная ставка банка
        self.total_lent = 0 # сумма выданных ипотек

    # расчет процентной ставки от риска
    def calculate_risk_adjusted_rate(self, household):
        rate = self.base_interest_rate
        if household.income < 50000:
            rate += ModelConfig.INTEREST_RATES['adjustment']['risk_premium']

        rate = np.clip(
            rate,
            ModelConfig.INTEREST_RATES['min_rate'],
            ModelConfig.INTEREST_RATES['max_rate']
        )

        return rate
    
    # можно ли выдать ипотеку доиохозяйству
    def can_issue_mortgage(self, household):
        # если ипотека есть или есть дефолт выдать ипотеку никак нельзя
        if household.has_mortgage or household.defaulted:
            return False
        
        # есть ли у банка средства на то чтобы выдать их
        total_exposure = self.total_lent
        if total_exposure >= self.capital * ModelConfig.BANK_CONFIG['lending_capacity_ratio']:
            return False
        
        # считаем риски и то сколько максимум можно выдать домохозяйству
        risk_adjusted_rate = self.calculate_risk_adjusted_rate(household)
        max_loan = ModelConfig.calculate_max_loan(
            household.income,
            ModelConfig.MORTGAGE_CONFIG['max_payment_to_income_ratio'],
            risk_adjusted_rate,
            ModelConfig.MORTGAGE_CONFIG['term_months']
        )
        # возвращаем да или нет в зависимости от того можно ли выдать средства домохозяйству
        return max_loan >= ModelConfig.MORTGAGE_CONFIG['min_loan_amount']
    
    # выдача ипотеки
    def issue_mortgage(self, household):
        # проверяем возможность выдачи
        if not self.can_issue_mortgage(household):
            return False
        
        # счиатем может ли банк выдать средства домохозяйству
        risk_adjusted_rate = self.calculate_risk_adjusted_rate(household)

        # расчитываем максимум который может выдать банк на основе дохода и рисков домохозяйства
        max_loan = ModelConfig.calculate_max_loan(
            household.income,
            ModelConfig.MORTGAGE_CONFIG['max_payment_to_income_ratio'],
            risk_adjusted_rate,
            ModelConfig.MORTGAGE_CONFIG['term_months']
        )

        # расчитываем сколько НУЖНО выдать домохозяйству 
        loan_amount = min(
            max_loan,
            ModelConfig.MORTGAGE_CONFIG['max_loan_amount']
        )

        # если то сколько выдадут больше или равно нужному имнимуму тогда выдаем ипотеку
        if loan_amount >= ModelConfig.MORTGAGE_CONFIG['min_loan_amount']:
            # заполнение полей ипотеки домохозяйства
            household.has_mortgage = True
            household.mortgage_amount = loan_amount
            household.interest_rate = risk_adjusted_rate
            
            # в список ипотек банка добавляем нового ипотечника
            self.mortgages.append({
                'household_id': household.unique_id,
                'amount': loan_amount,
                'rate': risk_adjusted_rate,
                'date_issued': self.model.steps
            })
            
            # к сумме выданных ипотек добавляем новую
            self.total_lent += loan_amount
            return True
        
        return False
    
    # регистрируем дефолт для банка
    def register_default(self, household):
        self.defaults_count += 1
        
        # Находим и удаляем ипотеку из портфеля
        self.mortgages = [m for m in self.mortgages if m['household_id'] != household.unique_id]
        
        # Списание убытков из капитала
        loss = household.mortgage_amount * 0.6  # возвращаем 40% через залог
        self.capital -= loss

    # наложение кризиса на банки
    def apply_crisis_effects(self):
        crisis = ModelConfig.CRISIS_CONFIG
        if not crisis['enabled'] or self.model.steps < crisis['start_step']:
            return

        progress = ModelConfig.get_crisis_progress(self)
        
        # 1. Снижение базовой ставки вслед за ФРС
        rate_reduction = crisis['fed_funds_rate_reduction'] * progress
        self.base_interest_rate = max(
            self.base_interest_rate - rate_reduction,
            ModelConfig.INTEREST_RATES['min_rate']
        )
        
        # 2. Постепенное ужесточение стандартов кредитования
        # Максимальный LTV снижается с докризисного уровня до tightened_ltv
        if hasattr(self, 'max_ltv_ratio'):
            pre_crisis_ltv = 0.95  # докризисный стандарт
            target_ltv = crisis['tightened_ltv']
            self.max_ltv_ratio = pre_crisis_ltv - (pre_crisis_ltv - target_ltv) * progress
        
        # 3. Повышение минимального кредитного рейтинга
        if hasattr(self, 'min_credit_score'):
            pre_crisis_score = 620
            target_score = crisis['min_credit_score']
            self.min_credit_score = int(pre_crisis_score + (target_score - pre_crisis_score) * progress)
        
        # 4. Корректировка ставок по существующим ARM-ипотекам (если есть)
        for mortgage in self.mortgages:
            if mortgage.get('is_adjustable', False):
                # ARM пересматриваются вниз вслед за индексами
                arm_reduction = crisis['arm_rate_reduction'] * progress
                mortgage['rate'] = max(
                    mortgage['rate'] - arm_reduction,
                    ModelConfig.INTEREST_RATES['min_rate']
                )

    # логика шаг моделирования для банков
    def step(self):
        self.apply_crisis_effects()
        
        # Выдача новых кредитов (только если не в глубоком кризисе)
        crisis = ModelConfig.CRISIS_CONFIG
        progress = ModelConfig.get_crisis_progress(self)

        issuance_probability = max(0.1, 1.0 - progress * 0.9)

        if np.random.random() < issuance_probability:
            eligible = [a for a in self.model.all_agents
                        if isinstance(a, Household) and not a.has_mortgage and not a.defaulted]
            
            if eligible:
                household = np.random.choice(eligible)
                self.issue_mortgage(household)

# модель работы агентов в кризис
class CrisisModel(mesa.Model):    
    def __init__(self, N_households=None, N_banks=None, seed=None):
        super().__init__(seed=seed)
        
        # Используем значения из конфига, если не переданы явно
        N_households = N_households or ModelConfig.DEFAULT_N_HOUSEHOLDS
        N_banks = N_banks or ModelConfig.DEFAULT_N_BANKS
        
        self.steps = 0
        self.primary_bank_id = None
        
        # Создание домохозяйств
        households = []
        for i in range(N_households):
            income = ModelConfig.generate_income()
            family_size = ModelConfig.generate_family_size()
            household = Household(self, i, income, family_size)
            households.append(household)
        
        # Создание банков
        banks = []
        for i in range(N_banks):
            capital = ModelConfig.generate_bank_capital()
            bank = Bank(self, N_households + i, capital)
            banks.append(bank)
            if i == 0:  # первый банк назначаем основным
                self.primary_bank_id = bank.unique_id
        
        # Объединяем всех агентов
        self.all_agents = households + banks
        
        # Инициализация БД
        self.conn = sqlite3.connect('C:\codes\python\ABM_2008_modeling\src\crisis_database\crisis_log.db')
        create_tables(self)

    # логирование состояний
    def log_state(self):
        cur = self.conn.cursor()
        
        for agent in self.all_agents:
            if isinstance(agent, Household):
                cur.execute('''
                    INSERT OR REPLACE INTO household_state 
                    (step, agent_id, income, family_size, has_mortgage,
                     mortgage_amount, interest_rate, delinquency_months, defaulted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (self.steps, agent.unique_id, agent.income, agent.family_size,
                      1 if agent.has_mortgage else 0, agent.mortgage_amount,
                      agent.interest_rate, agent.delinquency_months, 
                      1 if agent.defaulted else 0))
                
            elif isinstance(agent, Bank):
                total_mortgages = sum(m['amount'] for m in agent.mortgages) if agent.mortgages else 0
                cur.execute('''
                    INSERT OR REPLACE INTO bank_state
                    (step, agent_id, capital, mortgages_count, mortgages_total_amount, defaults_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (self.steps, agent.unique_id, agent.capital, 
                      len(agent.mortgages), total_mortgages, agent.defaults_count))
        
        # запись агрегированных логов
        self._log_aggregated_metrics()
        self.conn.commit()
    
    # логика записи агрегированных логов
    def _log_aggregated_metrics(self):
        cur = self.conn.cursor()
        
        households = [a for a in self.all_agents if isinstance(a, Household)]
        banks = [a for a in self.all_agents if isinstance(a, Bank)]
        
        # запись статистики по некоторым параметрам:
        # количество домохозяйств, количество дефолтов среди домохозяйств, процент дефолтов среди домохозяйств
        # полный капитал всех банков, ипотечная нагрузка по всем банкам
        total_households = len(households)
        defaulted = sum(1 for h in households if h.defaulted)
        default_rate = defaulted / total_households if total_households > 0 else 0
        total_capital = sum(b.capital for b in banks)
        total_mortgages = sum(sum(m['amount'] for m in b.mortgages) for b in banks)
        
        # список всех процентных станов и среднее их значение
        all_rates = [m['rate'] for b in banks for m in b.mortgages]
        avg_rate = np.mean(all_rates) if all_rates else 0
        
        # сколько домохозяйств просрачивают
        total_delinquencies = sum(1 for h in households if h.delinquency_months > 0)
        
        cur.execute('''
            INSERT OR REPLACE INTO aggregated_metrics
            (step, total_households, defaulted_households, default_rate,
             total_banks_capital, total_mortgages, avg_interest_rate, total_delinquencies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (self.steps, total_households, defaulted, default_rate, 
              total_capital, total_mortgages, avg_rate, total_delinquencies))
    
    # логика шага для модели кризиса
    def step(self):
        np.random.shuffle(self.all_agents)

        for agent in self.all_agents:
            agent.step()

        self.log_state()
    
    # закрытие соединения
    def close(self):
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

if __name__ == "__main__":
    model = CrisisModel()

    try:
        reset_tables(model)
        create_tables(model)
        for step in range(ModelConfig.SIMULATION_STEPS):
            model.step()
            print(f"Step {step} completed")

        print("Simulation completed successfully!")

    finally:
        model.close()