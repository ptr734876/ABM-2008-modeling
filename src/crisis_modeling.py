import mesa
import numpy as np
import sqlite3
from src.config import ModelConfig
from src.db_manipulator import *
from src.agents.bank_agent import Bank
from src.agents.household_agent import Household

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