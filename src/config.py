import numpy as np

class ModelConfig:
    DEFAULT_N_HOUSEHOLDS = 7000
    DEFAULT_N_BANKS = 5
    SIMULATION_STEPS = 36

    # calibrted
    INCOME_DISTRIBUTION = {
        1: {'mu': 10.06, 'sigma': 0.937},
        2: {'mu': 10.97, 'sigma': 0.778},
        3: {'mu': 11.09, 'sigma': 0.752},
        4: {'mu': 11.29, 'sigma': 0.698},
        5: {'mu': 11.23, 'sigma': 0.730},
        6: {'mu': 11.12, 'sigma': 0.741},
        7: {'mu': 11.15, 'sigma': 0.713}
    }

    # calibrated
    MIN_INCOME = 0
    MAX_INCOME = np.inf

    # calibrated
    FAMILY_SIZE_CONFIG = {
        'min': 1,
        'max': 7,
        'distribution': 'poisson'
    }

    # calibrated
    MONTHLY_EXPENSES_PER_PERSON = 1_683

    # calibrated
    MORTGAGE_CONFIG = {
        'term_months': 360,
        'max_payment_to_income_ratio': 0.41,
        'min_loan_amount': 50_000,
        'max_loan_amount': 417_000,
        'delinquency_limit': 3
    }
    # calibrated
    INTEREST_RATES = {
        'base_rate': 0.0575,
        'min_rate': 0.0500,
        'max_rate': 0.0800,
        'adjustment': {
            'risk_premium': 0.015,
        }
    }
    # calibrated
    BANK_CONFIG = {
        'initial_capital': 1_000_000,
        'capital_distribution': {
            'type': 'lognormal',
            'mean': 13.5,
            'sigma': 1.8,
            'min': 500_000,
            'max': 500_000_000
        },
        'lending_capacity_ratio': 0.70
    }

    # calibrated
    CRISIS_CONFIG = {
        'enabled': True,
        'start_step': 12,                     
        'peak_step': 34,                      
        
        # для домохозяйств
        'unemployment_rate': 0.101,
        'income_reduction': 0.029,
        
        # Для банков
        'fed_funds_rate_reduction': 0.04,
        'tightened_ltv': 0.80,
        'min_credit_score': 680,
        'arm_rate_reduction': 0.03
    }

    # calibrated
    @staticmethod
    def generate_income(family_size = None):

        if family_size is None or family_size == 1:
            params = ModelConfig.INCOME_DISTRIBUTION[1]
        else:
            size = min(family_size, 7)
            params = ModelConfig.INCOME_DISTRIBUTION[size]

        income = np.random.lognormal(params['mu'], params['sigma'])
        income = np.clip(
                income,
                ModelConfig.MIN_INCOME,
                ModelConfig.MAX_INCOME
            )
        return income
    
    # calibrated
    @staticmethod
    def generate_family_size():
        if ModelConfig.FAMILY_SIZE_CONFIG['distribution'] == 'uniform':
            return np.random.randint(
                ModelConfig.FAMILY_SIZE_CONFIG['min'],
                ModelConfig.FAMILY_SIZE_CONFIG['max'] + 1
            )
        elif ModelConfig.FAMILY_SIZE_CONFIG['distribution'] == 'poisson':
            size = np.random.poisson(2.5) + 1
            return min(size, ModelConfig.FAMILY_SIZE_CONFIG['max'])
        else:
            return 2
        
    # calibrated
    @staticmethod
    def generate_bank_capital():
        config = ModelConfig.BANK_CONFIG['capital_distribution']
        if config['type'] == 'lognormal':
            capital = np.random.lognormal(config['mean'], config['sigma'])
            return np.clip(capital, config['min'], config['max'])
        elif config['type'] == 'uniform':
            return np.random.uniform(config['min'], config['max'])
        else:
            return ModelConfig.BANK_CONFIG['initial_capital']
        
    # calibrated
    @staticmethod
    def calculate_monthly_payment(principal, annual_rate, months):
        if principal <= 0:
            return 0

        monthly_rate = annual_rate / 12

        if monthly_rate == 0:
            return principal / months
        else:
            payment = principal * (monthly_rate * (1 + monthly_rate) ** months) / ((1 + monthly_rate) ** months - 1)
            return payment
    
    # calibrated
    @staticmethod
    def calculate_max_loan(income, monthly_payment_ratio, annual_rate, months):
        max_monthly_payment = income / 12 * monthly_payment_ratio
        monthly_rate = annual_rate / 12

        if monthly_rate == 0:
            return max_monthly_payment * months
        else:
            max_loan = max_monthly_payment * (1 - (1 + monthly_rate) ** -months) / monthly_rate
            return max_loan
    
    # calibrated
    @staticmethod
    def get_crisis_progress(model_object):
        crisis = ModelConfig.CRISIS_CONFIG
        if not crisis['enabled']:
            return 0.0
            
        current_step = model_object.model.steps
        start = crisis['start_step']
        peak = crisis['peak_step']
        
        if current_step < start:
            return 0.0
        elif current_step >= peak:
            return 1.0
        else:
            return (current_step - start) / (peak - start)