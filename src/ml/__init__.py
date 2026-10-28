"""Machine Learning models for video performance prediction.

Deliberately no eager imports: most modules here are dormant experiments
(see model_registry.json) with heavy dependency chains (lightgbm -> matplotlib,
sklearn, torch-adjacent). Eagerly importing them made `from src.ml import
registry` — a pure-JSON module used by /health — load the entire ML stack and
fail whenever any of it was unhealthy. Import the module you need directly,
e.g. ``from src.ml import registry`` or ``from src.ml.thumbnail_predictor
import ThumbnailPredictor``.
"""
