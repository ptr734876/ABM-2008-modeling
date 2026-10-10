from src.config import ModelConfig
from src.db_manipulator import *
from src.crisis_modeling import CrisisModel


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