import numpy as np
import pickle
import os
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class FareAdjustmentAgent:
    """
    Reinforcement Learning Agent for Fare Adjustment.
    Uses Q-Learning (or Contextual Bandits) to learn optimal fare adjustments
    based on context (time, weather, zone, congestion).
    
    State: (heure, meteo, type_zone)
    Action: Adjustment factor (e.g., -10%, -5%, 0%, +5%, +10%)
    Reward: User acceptance (1 if accepted/good rating, -1 if rejected/bad rating) - simplified.
    """
    
    def __init__(self, model_path='ml_models/rl_agent.pkl'):
        self.model_path = model_path
        self.actions = [-0.10, -0.05, 0.0, 0.05, 0.10] # Percentage adjustments
        self.q_table = {} # State -> [Q-values for each action]
        self.learning_rate = 0.1
        self.discount_factor = 0.9
        self.epsilon = 0.1 # Exploration rate
        
        self.load()

    def _get_state(self, heure, meteo, type_zone):
        """Encodes state as a tuple."""
        # Ensure inputs are consistent
        return (str(heure), int(meteo or 0), int(type_zone or 0))

    def predict_action(self, heure, meteo, type_zone, congestion=None):
        """
        Selects an action based on state using Epsilon-Greedy policy.
        Returns the adjustment factor.
        """
        state = self._get_state(heure, meteo, type_zone)
        
        if np.random.rand() < self.epsilon:
            # Explore
            action_idx = np.random.randint(len(self.actions))
        else:
            # Exploit
            if state not in self.q_table:
                self.q_table[state] = np.zeros(len(self.actions))
            action_idx = np.argmax(self.q_table[state])
            
        return self.actions[action_idx]

    def update_policy(self, heure, meteo, type_zone, action_factor, reward):
        """
        Updates Q-table based on feedback.
        """
        state = self._get_state(heure, meteo, type_zone)
        
        # Find action index
        try:
            action_idx = self.actions.index(action_factor)
        except ValueError:
            logger.warning(f"Action {action_factor} not in action space.")
            return

        if state not in self.q_table:
            self.q_table[state] = np.zeros(len(self.actions))
            
        # Q-Learning update rule
        # Q(s,a) = Q(s,a) + alpha * (reward + gamma * max(Q(s', a')) - Q(s,a))
        # Here we assume single-step episode (Contextual Bandit style), so gamma * max(Q(s', a')) is 0 or we treat next state as terminal.
        # For simplicity in this fare adjustment context, we treat it as a bandit problem (gamma=0).
        
        current_q = self.q_table[state][action_idx]
        new_q = current_q + self.learning_rate * (reward - current_q)
        self.q_table[state][action_idx] = new_q
        
        logger.debug(f"Updated Q-value for {state}, action {action_factor}: {current_q} -> {new_q}")

    def save(self):
        """Saves the Q-table to disk."""
        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            with open(self.model_path, 'wb') as f:
                pickle.dump(self.q_table, f)
            logger.info(f"RL Agent saved to {self.model_path}")
        except Exception as e:
            logger.error(f"Failed to save RL Agent: {e}")

    def load(self):
        """Loads the Q-table from disk."""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    self.q_table = pickle.load(f)
                logger.info(f"RL Agent loaded from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load RL Agent: {e}")
                self.q_table = {}
        else:
            logger.info("No existing RL Agent found. Starting fresh.")
            self.q_table = {}
