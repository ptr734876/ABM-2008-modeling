import mesa
import numpy as np
from src.config import ModelConfig
from src.db_manipulator import *

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
            household.creditor_bank_id = self.unique_id
            
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
        defaulted_amount = 0
        for m in self.mortgages:
            if m['household_id'] == household.unique_id:
                defaulted_amount = m['amount']

        self.mortgages = [m for m in self.mortgages if m['household_id'] != household.unique_id]
        
        self.total_lent -= defaulted_amount
        # Списание убытков из капитала
        loss = defaulted_amount * 0.6  # возвращаем 40% через залог
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
        from src.agents.household_agent import Household

        self.apply_crisis_effects()
        
        # Выдача новых кредитов (только если не в глубоком кризисе)
        crisis = ModelConfig.CRISIS_CONFIG
        progress = ModelConfig.get_crisis_progress(self)

        issuance_probability = max(0.25, 1.0 - progress * 0.75)

        config = ModelConfig.MORTGAGE_CONFIG

        if config.get('max_applications_per_bank_per_step') is not None:
            max_applications = config['max_applications_per_bank_per_step']
        else:
            total_households = sum(1 for a in self.model.all_agents if isinstance(a, Household))
            expected_monthly_apps = total_households * config['avg_monthly_applications_rate']
            apps_per_bank = expected_monthly_apps / len([a for a in self.model.all_agents if isinstance(a, Bank)])
            max_applications = max(1, int(np.random.normal(apps_per_bank, apps_per_bank * 0.2)))
        
        for _ in range(max_applications):
            if np.random.random() < issuance_probability:
                eligible = [a for a in self.model.all_agents
                        if isinstance(a, Household) and not a.has_mortgage and not a.defaulted]
            
                if eligible:
                    household = np.random.choice(eligible)
                    self.issue_mortgage(household)
