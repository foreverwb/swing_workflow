
from .code1_event_detection import main as event_detection_main
from .code2_scoring import main as scoring_main
from .code3_strategy_calc import main as strategy_calc_main
from .code4_comparison import main as comparison_main
from .code_aggregator import main as aggregator_main

__all__ = [
    'event_detection_main',
    'scoring_main',
    'strategy_calc_main',
    'comparison_main',
    'aggregator_main'
]