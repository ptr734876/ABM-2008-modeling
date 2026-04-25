# создание бд
def create_tables(model_object):
    cur = model_object.conn.cursor()
    
    # Таблица состояния домохозяйств
    cur.execute('''
        CREATE TABLE IF NOT EXISTS household_state (
            step INTEGER,
            agent_id INTEGER,
            income REAL,
            family_size INTEGER,
            has_mortgage INTEGER,
            mortgage_amount REAL,
            interest_rate REAL,
            delinquency_months REAL,
            defaulted INTEGER,
            PRIMARY KEY (step, agent_id)
        )
    ''')
    
    # Таблица состояния банков
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bank_state (
            step INTEGER,
            agent_id INTEGER,
            capital REAL,
            mortgages_count INTEGER,
            mortgages_total_amount REAL,
            defaults_count INTEGER,
            PRIMARY KEY (step, agent_id)
        )
    ''')
    
    # Таблица агрегированных метрик
    cur.execute('''
        CREATE TABLE IF NOT EXISTS aggregated_metrics (
            step INTEGER PRIMARY KEY,
            total_households INTEGER,
            defaulted_households INTEGER,
            default_rate REAL,
            total_banks_capital REAL,
            total_mortgages REAL,
            avg_interest_rate REAL,
            total_delinquencies INTEGER
        )
    ''')
    
    model_object.conn.commit()

def reset_tables(model_object):
    cur = model_object.conn.cursor()

    cur.execute('''DROP TABLE IF EXISTS aggregated_metrics''')
    cur.execute('''DROP TABLE IF EXISTS bank_state''')
    cur.execute('''DROP TABLE IF EXISTS household_state''')

    model_object.conn.commit()