import os
import django
import sys
from unittest.mock import MagicMock

# Setup Django environment
sys.path.append('/home/gates/Documents/Niveau5/GesTrafic/test/fare-calculator-service-v2-main')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fare_calculator.settings')
django.setup()

from core.ml.rl_agent import FareAdjustmentAgent
from core.tasks import train_rl_on_recent_trips
from core.views import EstimateView, AddTrajetView

def verify_rl_agent():
    print("Verifying RL Agent...")
    agent = FareAdjustmentAgent()
    action = agent.predict_action('matin', 0, 0)
    print(f"Predicted action: {action}")
    
    # Test save/load
    agent.save()
    print("Agent saved.")
    
    agent2 = FareAdjustmentAgent()
    print("Agent loaded.")

def verify_tasks():
    print("\nVerifying Celery Task Import...")
    print(f"Task train_rl_on_recent_trips: {train_rl_on_recent_trips}")

if __name__ == "__main__":
    try:
        verify_rl_agent()
        verify_tasks()
        print("\nVerification SUCCESS!")
    except Exception as e:
        print(f"\nVerification FAILED: {e}")
