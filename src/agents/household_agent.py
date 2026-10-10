import mesa
import numpy as np
from src.config import ModelConfig
from src.db_manipulator import *

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
        self.creditor_bank_id = None
    
    # расчет необходимых средств на жизнь
    def calculate_essential_expenses(self):
        ec = ModelConfig.EXPENSES_CONFIG
        family = self.family_size
        n_adults = min(family, 2)
        n_children = max(0, family-2)
        adult_equiv = 1 + ec['first_adult'] + ec['additional_adult'] * (n_adults - 1) + ec['child'] * n_children

        expenses = max(
            (self.income / 12) * ec['base_consumption_share'],
            ec['floor_per_equivalent'] * adult_equiv
        )
        return expenses
    
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

        if self.is_unemployed:
            if np.random.random() < 0.10:
                self.is_unemployed = False
                self.income = self.original_income
        else:
            if np.random.random() < current_unemployment_rate:
                self.is_unemployed = True
                self.income = self.original_income * (1 - crisis['income_reduction'] * progress)


    def pay_mortgage(self):
        from src.agents.bank_agent import Bank

        if not self.has_mortgage or self.defaulted:
            return
        
        self.apply_crisis_effects()

        monthly_payment = self.calculate_monthly_payment()
        essential_expenses = self.calculate_essential_expenses()
        monthly_income = self.income / 12

        available = monthly_income + self.savings

        if available >= essential_expenses:
            available -= essential_expenses

        else:
            self.savings = 0
            self.delinquency_months += 1

            if self.delinquency_months >= ModelConfig.MORTGAGE_CONFIG['delinquency_limit']:
                self.defaulted = True
                for agent in self.model.all_agents:
                    if isinstance(agent, Bank) and agent.unique_id == self.creditor_bank_id:
                        agent.register_default(self)
                        break
            return
        
        if available >= monthly_payment:
            self.mortgage_amount -= monthly_payment
            available -= monthly_payment
            self.delinquency_months = 0

            if self.mortgage_amount <= 0:
                self.has_mortgage = False
                self.mortgage_amount = 0
                self.creditor_bank_id = None
        
        elif available >= monthly_payment * 0.5:
            partitial_payment = monthly_payment * 0.5
            self.mortgage_amount -= partitial_payment
            available -= partitial_payment
            self.delinquency_months += 0.5
        else:
            shortage = monthly_payment * 0.5 - available
            if self.savings >= shortage:
                self.mortgage_amount -= monthly_payment * 0.5
                available = 0
                self.savings -= shortage
                self.delinquency_months += 0.5
            else:
                self.delinquency_months += 1

        if self.delinquency_months >= ModelConfig.MORTGAGE_CONFIG['delinquency_limit']:
            self.defaulted = True
            for agent in self.model.all_agents:
                if isinstance(agent, Bank) and agent.unique_id == self.creditor_bank_id:
                    agent.register_default(self)
                    break

        self.savings = max(0, available)

        if monthly_income > essential_expenses + monthly_payment and self.delinquency_months == 0:
            self.savings += (monthly_income - essential_expenses - monthly_payment) * 0.3
    
    # логика каждого шага моделирования
    def step(self):
        self.pay_mortgage()