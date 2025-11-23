"""
Model loader module for DTester - handles loading and caching of ML models.
This module provides a centralized way to load and reuse models across the application.
"""

import logging
from typing import Any, Dict, Optional, Tuple

import torch
from transformers import AutoModel, AutoTokenizer

# Configure logging
logger = logging.getLogger(__name__)

# Global model cache
_model_cache: Dict[str, Dict[str, Any]] = {}


class ModelLoader:
    """
    Centralized model loader with caching capabilities.
    """

    # Default model configurations
    DEFAULT_MODELS = {
        "embedding": {
            "model_name": "Salesforce/codet5p-110m-embedding",
            "trust_remote_code": True,
            "eval_mode": True,
        }
    }

    def __init__(self):
        self.device = self._get_device()
        self.cache = _model_cache
        logger.info("ModelLoader initialized with device: %s", self.device)

    def _get_device(self) -> str:
        """Determine the best available device for model inference."""
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"  # Apple Silicon
        else:
            return "cpu"

    def load_embedding_model(
        self, model_name: Optional[str] = None, force_reload: bool = False
    ) -> Tuple[Optional[Any], Optional[Any]]:
        """
        Load embedding model and tokenizer with caching.

        Args:
            model_name: Name of the model to load. If None, uses default.
            force_reload: If True, bypasses cache and reloads the model.

        Returns:
            Tuple of (model, tokenizer) or (None, None) if loading fails.
        """
        # Use default model if none specified
        if model_name is None:
            model_name = self.DEFAULT_MODELS["embedding"]["model_name"]

        cache_key = f"embedding_{model_name}"

        # Return cached model if available and not forcing reload
        if not force_reload and cache_key in self.cache:
            logger.info("Using cached embedding model: %s", model_name)
            cached_model = self.cache[cache_key]
            return cached_model["model"], cached_model["tokenizer"]

        try:
            logger.info("Loading embedding model: %s", model_name)

            # Load model and tokenizer
            embedding_model = AutoModel.from_pretrained(
                model_name,
                trust_remote_code=self.DEFAULT_MODELS["embedding"]["trust_remote_code"],
            )

            embedding_tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                trust_remote_code=self.DEFAULT_MODELS["embedding"]["trust_remote_code"],
            )

            # Set to evaluation mode
            if (
                self.DEFAULT_MODELS["embedding"]["eval_mode"]
                and embedding_model is not None
            ):
                embedding_model.eval()

            # Move to appropriate device
            if self.device != "cpu" and embedding_model is not None:
                try:
                    embedding_model = embedding_model.to(self.device)
                    logger.info("Model moved to %s", self.device)
                except RuntimeError as e:
                    logger.warning(
                        "Failed to move model to %s, using CPU: %s", self.device, e
                    )
                    self.device = "cpu"

            # Cache the loaded model
            self.cache[cache_key] = {
                "model": embedding_model,
                "tokenizer": embedding_tokenizer,
                "device": self.device,
                "model_name": model_name,
            }

            logger.info(
                "Successfully loaded and cached embedding model: %s", model_name
            )
            return embedding_model, embedding_tokenizer

        except Exception as e:
            logger.error("Failed to load embedding model %s: %s", model_name, e)
            return None, None

    def get_cached_model(
        self, model_type: str, model_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a cached model without loading.

        Args:
            model_type: Type of model ('embedding', etc.)
            model_name: Specific model name. If None, uses default.

        Returns:
            Cached model dict or None if not found.
        """
        if model_name is None and model_type in self.DEFAULT_MODELS:
            model_name = self.DEFAULT_MODELS[model_type]["model_name"]

        cache_key = f"{model_type}_{model_name}"
        return self.cache.get(cache_key)

    def clear_cache(self, model_type: Optional[str] = None):
        """
        Clear model cache.

        Args:
            model_type: If specified, only clear models of this type.
                       If None, clear all cached models.
        """
        if model_type is None:
            self.cache.clear()
            logger.info("Cleared all cached models")
        else:
            keys_to_remove = [
                k for k in self.cache.keys() if k.startswith(f"{model_type}_")
            ]
            for key in keys_to_remove:
                del self.cache[key]
            logger.info("Cleared cached models of type: %s", model_type)

    def list_cached_models(self) -> Dict[str, str]:
        """
        List all currently cached models.

        Returns:
            Dict mapping cache keys to model names.
        """
        return {key: info["model_name"] for key, info in self.cache.items()}

    def get_device_info(self) -> Dict[str, Any]:
        """
        Get information about the current device and available devices.

        Returns:
            Dict with device information.
        """
        info = {
            "current_device": self.device,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count()
            if torch.cuda.is_available()
            else 0,
            "mps_available": hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available(),
        }

        if torch.cuda.is_available():
            info["cuda_device_name"] = torch.cuda.get_device_name(0)
            info["cuda_memory_total"] = torch.cuda.get_device_properties(0).total_memory

        return info


# Global model loader instance
_global_loader: Optional[ModelLoader] = None


def get_model_loader() -> ModelLoader:
    """
    Get the global model loader instance (singleton pattern).

    Returns:
        ModelLoader instance.
    """
    global _global_loader
    if _global_loader is None:
        _global_loader = ModelLoader()
    return _global_loader


def load_embedding_model(
    model_name: Optional[str] = None, force_reload: bool = False
) -> Tuple[Optional[Any], Optional[Any]]:
    """
    Convenience function to load embedding model using the global loader.

    Args:
        model_name: Name of the model to load. If None, uses default.
        force_reload: If True, bypasses cache and reloads the model.

    Returns:
        Tuple of (model, tokenizer) or (None, None) if loading fails.
    """
    loader = get_model_loader()
    return loader.load_embedding_model(model_name, force_reload)


def get_device() -> str:
    """
    Get the current device being used by the model loader.

    Returns:
        Device string ('cuda', 'mps', or 'cpu').
    """
    loader = get_model_loader()
    return loader.device


def clear_model_cache(model_type: Optional[str] = None):
    """
    Clear the global model cache.

    Args:
        model_type: If specified, only clear models of this type.
                   If None, clear all cached models.
    """
    loader = get_model_loader()
    loader.clear_cache(model_type)


def list_cached_models() -> Dict[str, str]:
    """
    List all currently cached models.

    Returns:
        Dict mapping cache keys to model names.
    """
    loader = get_model_loader()
    return loader.list_cached_models()


def get_device_info() -> Dict[str, Any]:
    """
    Get information about available devices.

    Returns:
        Dict with device information.
    """
    loader = get_model_loader()
    return loader.get_device_info()


if __name__ == "__main__":
    # Example usage and testing
    print("Testing ModelLoader...")

    # Get device info
    device_info = get_device_info()
    print(f"Device info: {device_info}")

    # Load embedding model
    model, tokenizer = load_embedding_model()
    if model is not None:
        print("Successfully loaded embedding model")
        print(
            f"Model device: {model.device if hasattr(model, 'device') else 'unknown'}"
        )
    else:
        print("Failed to load embedding model")

    # List cached models
    cached_models = list_cached_models()
    print(f"Cached models: {cached_models}")
