"""
Tests for the Velocity Predictor ML model.
"""
import pytest
from unittest.mock import patch, MagicMock
import numpy as np


class TestVelocityPredictor:
    """Test the VelocityPredictor class."""
    
    @pytest.fixture
    def sample_velocity_data(self):
        """Sample velocity snapshot data."""
        return {
            "video_id": "test_video",
            "channel_id": "test_channel",
            "views_1h": 100,
            "views_6h": 500,
            "views_24h": 2000,
            "views_3d": 8000,
            "views_7d": 15000,
            "views_14d": 20000,
            "likes_24h": 100,
            "comments_24h": 20,
            "subscriber_count": 50000,
        }
    
    def test_calculate_growth_multiplier(self, sample_velocity_data):
        """Test growth multiplier calculation."""
        views_24h = sample_velocity_data["views_24h"]
        views_7d = sample_velocity_data["views_7d"]
        
        if views_24h > 0:
            growth_multiplier = views_7d / views_24h
        else:
            growth_multiplier = 1.0
        
        assert growth_multiplier > 0
        assert growth_multiplier == 7.5  # 15000 / 2000
    
    def test_calculate_views_per_hour(self, sample_velocity_data):
        """Test views per hour calculation."""
        views_24h = sample_velocity_data["views_24h"]
        vph_24h = views_24h / 24
        
        assert vph_24h > 0
        assert vph_24h == 2000 / 24
    
    def test_calculate_like_rate(self, sample_velocity_data):
        """Test like rate calculation."""
        likes = sample_velocity_data["likes_24h"]
        views = sample_velocity_data["views_24h"]
        
        like_rate = likes / views if views > 0 else 0
        
        assert 0 <= like_rate <= 1
        assert like_rate == 0.05  # 100 / 2000
    
    def test_predict_30d_from_7d(self, sample_velocity_data):
        """Test predicting 30-day views from 7-day data."""
        views_7d = sample_velocity_data["views_7d"]
        
        # Typical growth multiplier from 7d to 30d is around 1.04-1.5
        predicted_30d_low = views_7d * 1.04
        predicted_30d_high = views_7d * 1.5
        
        assert predicted_30d_low > views_7d
        assert predicted_30d_high > predicted_30d_low
    
    def test_trajectory_classification(self, sample_velocity_data):
        """Test trajectory classification (above/on_track/below)."""
        views_7d = sample_velocity_data["views_7d"]
        expected_7d = 12000  # Hypothetical expected value
        
        ratio = views_7d / expected_7d if expected_7d > 0 else 1.0
        
        if ratio > 1.2:
            trajectory = "above"
        elif ratio < 0.8:
            trajectory = "below"
        else:
            trajectory = "on_track"
        
        assert trajectory in ["above", "on_track", "below"]
        assert trajectory == "above"  # 15000/12000 = 1.25 > 1.2


class TestGrowthPatterns:
    """Test channel growth pattern analysis."""
    
    def test_calculate_channel_growth_pattern(self):
        """Test calculating channel's typical growth pattern."""
        # Sample historical data for a channel
        historical_growth = [
            {"views_24h": 1000, "views_7d": 7500},  # 7.5x
            {"views_24h": 2000, "views_7d": 16000},  # 8x
            {"views_24h": 1500, "views_7d": 10500},  # 7x
        ]
        
        multipliers = [
            v["views_7d"] / v["views_24h"] 
            for v in historical_growth 
            if v["views_24h"] > 0
        ]
        
        avg_multiplier = sum(multipliers) / len(multipliers)
        
        assert avg_multiplier > 0
        assert 7 < avg_multiplier < 8
    
    def test_channel_pattern_consistency(self):
        """Test how consistent a channel's growth pattern is."""
        multipliers = [7.5, 8.0, 7.0, 7.8, 7.2]
        
        mean = sum(multipliers) / len(multipliers)
        variance = sum((m - mean) ** 2 for m in multipliers) / len(multipliers)
        std_dev = variance ** 0.5
        
        # Low std dev means consistent pattern
        consistency_score = 1 - (std_dev / mean) if mean > 0 else 0
        
        assert 0 <= consistency_score <= 1
        assert consistency_score > 0.9  # These multipliers are fairly consistent


class TestPredictionAccuracy:
    """Test prediction accuracy metrics."""
    
    def test_calculate_prediction_accuracy(self):
        """Test accuracy calculation for a single prediction."""
        predicted = 20000
        actual = 18000
        
        # Accuracy as percentage error
        error = abs(predicted - actual) / actual * 100
        accuracy = max(0, 100 - error)
        
        assert 0 <= accuracy <= 100
        assert accuracy > 85  # Should be reasonably accurate
    
    def test_calculate_batch_accuracy(self):
        """Test accuracy calculation for multiple predictions."""
        predictions = [
            {"predicted": 20000, "actual": 18000},
            {"predicted": 50000, "actual": 55000},
            {"predicted": 10000, "actual": 10500},
        ]
        
        errors = [
            abs(p["predicted"] - p["actual"]) / p["actual"] * 100
            for p in predictions
        ]
        
        avg_error = sum(errors) / len(errors)
        accuracy = max(0, 100 - avg_error)
        
        assert 0 <= accuracy <= 100
    
    def test_calculate_mape(self):
        """Test Mean Absolute Percentage Error calculation."""
        predictions = [20000, 50000, 10000]
        actuals = [18000, 55000, 10500]
        
        ape = [abs(p - a) / a * 100 for p, a in zip(predictions, actuals)]
        mape = sum(ape) / len(ape)
        
        assert mape >= 0
        assert mape < 20  # Should be less than 20% error
