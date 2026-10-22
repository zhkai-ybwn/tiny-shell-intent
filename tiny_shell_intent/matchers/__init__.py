"""Matcher implementations for tiny shell intent engine."""

from .base import BaseMatcher
from .rule_matcher import RuleMatcher
from .fuzzy_matcher import FuzzyMatcher
from .model_matcher import ModelMatcher

__all__ = ["BaseMatcher", "RuleMatcher", "FuzzyMatcher", "ModelMatcher"]
