"""
Local Data Stores and Model Artifacts for Offline Mode

Provides:
- Local historical data stores for backtests/simulation
- Local model artifacts for Llama/Gemma/ML models
- Offline-capable data access layer
- Model versioning and caching
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import json
import hashlib
import shutil
import threading

logger = get_logger(__name__)


class DataCategory(Enum):
    """Categories of offline data."""
    MARKET_DATA = "market_data"
    ORDER_BOOK = "order_book"
    TRADES = "trades"
    OHLCV = "ohlcv"
    ON_CHAIN = "on_chain"
    SENTIMENT = "sentiment"
    FEATURES = "features"
    LABELS = "labels"


class ModelType(Enum):
    """Types of model artifacts."""
    LLM_LLAMA = "llm_llama"
    LLM_GEMMA = "llm_gemma"
    ML_CLASSIFIER = "ml_classifier"
    ML_REGRESSOR = "ml_regressor"
    RL_POLICY = "rl_policy"
    EMBEDDING = "embedding"
    TOKENIZER = "tokenizer"


class StorageFormat(Enum):
    """Storage formats for data."""
    PARQUET = "parquet"
    ARROW = "arrow"
    JSON = "json"
    CSV = "csv"
    PICKLE = "pickle"
    SAFETENSORS = "safetensors"
    GGUF = "gguf"
    ONNX = "onnx"


@dataclass
class DatasetMetadata:
    """Metadata for a local dataset."""
    dataset_id: str
    name: str
    category: DataCategory
    
    symbols: List[str] = field(default_factory=list)
    venues: List[str] = field(default_factory=list)
    
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    row_count: int = 0
    file_size_bytes: int = 0
    
    storage_format: StorageFormat = StorageFormat.PARQUET
    storage_path: str = ""
    
    checksum: str = ""
    version: str = "1.0.0"
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ModelArtifact:
    """Metadata for a local model artifact."""
    artifact_id: str
    name: str
    model_type: ModelType
    
    version: str = "1.0.0"
    base_model: str = ""
    
    file_size_bytes: int = 0
    storage_format: StorageFormat = StorageFormat.SAFETENSORS
    storage_path: str = ""
    
    quantization: Optional[str] = None
    context_length: int = 4096
    
    checksum: str = ""
    
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_loaded: Optional[datetime] = None


@dataclass
class OfflineConfig:
    """Configuration for offline mode."""
    enabled: bool = False
    
    data_root: str = "./offline_data"
    models_root: str = "./offline_models"
    cache_root: str = "./offline_cache"
    
    max_cache_size_gb: float = 50.0
    max_data_age_days: int = 365
    
    auto_sync_on_online: bool = True
    verify_checksums: bool = True


class OfflineDataStore:
    """
    Local Data Store for Offline Mode.
    
    Features:
    - Local historical data storage
    - Efficient columnar formats (Parquet/Arrow)
    - Data versioning and checksums
    - Automatic cache management
    - Seamless online/offline switching
    """
    
    def __init__(self, config: Optional[OfflineConfig] = None):
        self._config = config or OfflineConfig()
        self._datasets: Dict[str, DatasetMetadata] = {}
        self._models: Dict[str, ModelArtifact] = {}
        self._cache: Dict[str, Any] = {}
        
        self._ensure_directories()
        self._load_metadata()
    
    def _ensure_directories(self) -> None:
        """Ensure storage directories exist."""
        for path in [
            self._config.data_root,
            self._config.models_root,
            self._config.cache_root,
        ]:
            Path(path).mkdir(parents=True, exist_ok=True)
    
    def _load_metadata(self) -> None:
        """Load metadata from disk."""
        metadata_path = Path(self._config.data_root) / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, "r") as f:
                    data = json.load(f)
                    for ds in data.get("datasets", []):
                        ds["category"] = DataCategory(ds["category"])
                        ds["storage_format"] = StorageFormat(ds["storage_format"])
                        if ds.get("start_date"):
                            ds["start_date"] = datetime.fromisoformat(ds["start_date"])
                        if ds.get("end_date"):
                            ds["end_date"] = datetime.fromisoformat(ds["end_date"])
                        ds["created_at"] = datetime.fromisoformat(ds["created_at"])
                        ds["last_accessed"] = datetime.fromisoformat(ds["last_accessed"])
                        dataset = DatasetMetadata(**ds)
                        self._datasets[dataset.dataset_id] = dataset
                logger.info(f"Loaded {len(self._datasets)} dataset metadata records")
            except Exception as e:
                logger.warning(f"Failed to load metadata: {e}")
        
        models_path = Path(self._config.models_root) / "models.json"
        if models_path.exists():
            try:
                with open(models_path, "r") as f:
                    data = json.load(f)
                    for m in data.get("models", []):
                        m["model_type"] = ModelType(m["model_type"])
                        m["storage_format"] = StorageFormat(m["storage_format"])
                        m["created_at"] = datetime.fromisoformat(m["created_at"])
                        if m.get("last_loaded"):
                            m["last_loaded"] = datetime.fromisoformat(m["last_loaded"])
                        model = ModelArtifact(**m)
                        self._models[model.artifact_id] = model
                logger.info(f"Loaded {len(self._models)} model artifact records")
            except Exception as e:
                logger.warning(f"Failed to load model metadata: {e}")
    
    def _save_metadata(self) -> None:
        """Save metadata to disk."""
        metadata_path = Path(self._config.data_root) / "metadata.json"
        datasets_data = []
        for ds in self._datasets.values():
            ds_dict = {
                "dataset_id": ds.dataset_id,
                "name": ds.name,
                "category": ds.category.value,
                "symbols": ds.symbols,
                "venues": ds.venues,
                "start_date": ds.start_date.isoformat() if ds.start_date else None,
                "end_date": ds.end_date.isoformat() if ds.end_date else None,
                "row_count": ds.row_count,
                "file_size_bytes": ds.file_size_bytes,
                "storage_format": ds.storage_format.value,
                "storage_path": ds.storage_path,
                "checksum": ds.checksum,
                "version": ds.version,
                "created_at": ds.created_at.isoformat(),
                "last_accessed": ds.last_accessed.isoformat(),
            }
            datasets_data.append(ds_dict)
        
        with open(metadata_path, "w") as f:
            json.dump({"datasets": datasets_data}, f, indent=2)
        
        models_path = Path(self._config.models_root) / "models.json"
        models_data = []
        for m in self._models.values():
            m_dict = {
                "artifact_id": m.artifact_id,
                "name": m.name,
                "model_type": m.model_type.value,
                "version": m.version,
                "base_model": m.base_model,
                "file_size_bytes": m.file_size_bytes,
                "storage_format": m.storage_format.value,
                "storage_path": m.storage_path,
                "quantization": m.quantization,
                "context_length": m.context_length,
                "checksum": m.checksum,
                "performance_metrics": m.performance_metrics,
                "created_at": m.created_at.isoformat(),
                "last_loaded": m.last_loaded.isoformat() if m.last_loaded else None,
            }
            models_data.append(m_dict)
        
        with open(models_path, "w") as f:
            json.dump({"models": models_data}, f, indent=2)
    
    def register_dataset(
        self,
        name: str,
        category: DataCategory,
        symbols: List[str],
        venues: List[str],
        start_date: datetime,
        end_date: datetime,
        storage_format: StorageFormat = StorageFormat.PARQUET,
    ) -> DatasetMetadata:
        """Register a new dataset for offline storage."""
        dataset_id = f"{category.value}_{hashlib.md5(name.encode()).hexdigest()[:8]}"
        
        storage_path = str(
            Path(self._config.data_root) / category.value / f"{dataset_id}.{storage_format.value}"
        )
        
        dataset = DatasetMetadata(
            dataset_id=dataset_id,
            name=name,
            category=category,
            symbols=symbols,
            venues=venues,
            start_date=start_date,
            end_date=end_date,
            storage_format=storage_format,
            storage_path=storage_path,
        )
        
        self._datasets[dataset_id] = dataset
        self._save_metadata()
        
        logger.info(f"Registered dataset '{name}' with ID '{dataset_id}'")
        return dataset
    
    def store_dataset(
        self,
        dataset_id: str,
        data: Any,
    ) -> bool:
        """Store data for a registered dataset."""
        if dataset_id not in self._datasets:
            logger.error(f"Dataset '{dataset_id}' not found")
            return False
        
        dataset = self._datasets[dataset_id]
        storage_path = Path(dataset.storage_path)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            if dataset.storage_format == StorageFormat.PARQUET:
                if hasattr(data, "to_parquet"):
                    data.to_parquet(storage_path)
                else:
                    import pandas as pd
                    pd.DataFrame(data).to_parquet(storage_path)
            elif dataset.storage_format == StorageFormat.JSON:
                with open(storage_path, "w") as f:
                    json.dump(data, f)
            elif dataset.storage_format == StorageFormat.CSV:
                if hasattr(data, "to_csv"):
                    data.to_csv(storage_path, index=False)
            
            dataset.file_size_bytes = storage_path.stat().st_size
            dataset.row_count = len(data) if hasattr(data, "__len__") else 0
            
            with open(storage_path, "rb") as f:
                dataset.checksum = hashlib.sha256(f.read()).hexdigest()
            
            self._save_metadata()
            
            logger.info(
                f"Stored dataset '{dataset_id}': "
                f"{dataset.row_count} rows, {dataset.file_size_bytes / 1024 / 1024:.2f} MB"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to store dataset '{dataset_id}': {e}")
            return False
    
    def load_dataset(
        self,
        dataset_id: str,
        verify_checksum: bool = True,
    ) -> Optional[Any]:
        """Load a dataset from offline storage."""
        if dataset_id not in self._datasets:
            logger.error(f"Dataset '{dataset_id}' not found")
            return None
        
        dataset = self._datasets[dataset_id]
        storage_path = Path(dataset.storage_path)
        
        if not storage_path.exists():
            logger.error(f"Dataset file not found: {storage_path}")
            return None
        
        if verify_checksum and self._config.verify_checksums:
            with open(storage_path, "rb") as f:
                current_checksum = hashlib.sha256(f.read()).hexdigest()
            if current_checksum != dataset.checksum:
                logger.error(f"Checksum mismatch for dataset '{dataset_id}'")
                return None
        
        try:
            if dataset.storage_format == StorageFormat.PARQUET:
                import pandas as pd
                data = pd.read_parquet(storage_path)
            elif dataset.storage_format == StorageFormat.JSON:
                with open(storage_path, "r") as f:
                    data = json.load(f)
            elif dataset.storage_format == StorageFormat.CSV:
                import pandas as pd
                data = pd.read_csv(storage_path)
            else:
                logger.error(f"Unsupported format: {dataset.storage_format}")
                return None
            
            dataset.last_accessed = datetime.utcnow()
            self._save_metadata()
            
            logger.info(f"Loaded dataset '{dataset_id}'")
            return data
            
        except Exception as e:
            logger.error(f"Failed to load dataset '{dataset_id}': {e}")
            return None
    
    def register_model(
        self,
        name: str,
        model_type: ModelType,
        version: str,
        base_model: str = "",
        storage_format: StorageFormat = StorageFormat.SAFETENSORS,
        quantization: Optional[str] = None,
        context_length: int = 4096,
    ) -> ModelArtifact:
        """Register a model artifact for offline storage."""
        artifact_id = f"{model_type.value}_{hashlib.md5(f'{name}_{version}'.encode()).hexdigest()[:8]}"
        
        storage_path = str(
            Path(self._config.models_root) / model_type.value / f"{artifact_id}"
        )
        
        artifact = ModelArtifact(
            artifact_id=artifact_id,
            name=name,
            model_type=model_type,
            version=version,
            base_model=base_model,
            storage_format=storage_format,
            storage_path=storage_path,
            quantization=quantization,
            context_length=context_length,
        )
        
        self._models[artifact_id] = artifact
        self._save_metadata()
        
        logger.info(f"Registered model '{name}' v{version} with ID '{artifact_id}'")
        return artifact
    
    def store_model(
        self,
        artifact_id: str,
        model_data: Any,
        config_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Store model artifact to offline storage."""
        if artifact_id not in self._models:
            logger.error(f"Model artifact '{artifact_id}' not found")
            return False
        
        artifact = self._models[artifact_id]
        storage_path = Path(artifact.storage_path)
        storage_path.mkdir(parents=True, exist_ok=True)
        
        try:
            if artifact.storage_format == StorageFormat.SAFETENSORS:
                model_file = storage_path / "model.safetensors"
                if hasattr(model_data, "save_pretrained"):
                    model_data.save_pretrained(storage_path, safe_serialization=True)
                else:
                    from safetensors.torch import save_file
                    save_file(model_data, str(model_file))
            elif artifact.storage_format == StorageFormat.GGUF:
                model_file = storage_path / "model.gguf"
                if isinstance(model_data, (str, Path)):
                    shutil.copy(model_data, model_file)
            elif artifact.storage_format == StorageFormat.ONNX:
                model_file = storage_path / "model.onnx"
                if isinstance(model_data, (str, Path)):
                    shutil.copy(model_data, model_file)
            elif artifact.storage_format == StorageFormat.PICKLE:
                import pickle
                model_file = storage_path / "model.pkl"
                with open(model_file, "wb") as f:
                    pickle.dump(model_data, f)
            
            if config_data:
                config_file = storage_path / "config.json"
                with open(config_file, "w") as f:
                    json.dump(config_data, f, indent=2)
            
            total_size = sum(f.stat().st_size for f in storage_path.rglob("*") if f.is_file())
            artifact.file_size_bytes = total_size
            
            self._save_metadata()
            
            logger.info(
                f"Stored model '{artifact_id}': {total_size / 1024 / 1024:.2f} MB"
            )
            return True
            
        except Exception as e:
            logger.error(f"Failed to store model '{artifact_id}': {e}")
            return False
    
    def load_model(
        self,
        artifact_id: str,
    ) -> Optional[Any]:
        """Load model artifact from offline storage."""
        if artifact_id not in self._models:
            logger.error(f"Model artifact '{artifact_id}' not found")
            return None
        
        artifact = self._models[artifact_id]
        storage_path = Path(artifact.storage_path)
        
        if not storage_path.exists():
            logger.error(f"Model directory not found: {storage_path}")
            return None
        
        try:
            if artifact.storage_format == StorageFormat.SAFETENSORS:
                from safetensors.torch import load_file
                model_file = storage_path / "model.safetensors"
                if model_file.exists():
                    model_data = load_file(str(model_file))
                else:
                    model_data = storage_path
            elif artifact.storage_format == StorageFormat.GGUF:
                model_file = storage_path / "model.gguf"
                model_data = str(model_file)
            elif artifact.storage_format == StorageFormat.ONNX:
                import onnxruntime as ort
                model_file = storage_path / "model.onnx"
                model_data = ort.InferenceSession(str(model_file))
            elif artifact.storage_format == StorageFormat.PICKLE:
                import pickle
                model_file = storage_path / "model.pkl"
                with open(model_file, "rb") as f:
                    model_data = pickle.load(f)
            else:
                logger.error(f"Unsupported format: {artifact.storage_format}")
                return None
            
            artifact.last_loaded = datetime.utcnow()
            self._save_metadata()
            
            logger.info(f"Loaded model '{artifact_id}'")
            return model_data
            
        except Exception as e:
            logger.error(f"Failed to load model '{artifact_id}': {e}")
            return None
    
    def get_available_datasets(
        self,
        category: Optional[DataCategory] = None,
    ) -> List[DatasetMetadata]:
        """Get list of available datasets."""
        datasets = list(self._datasets.values())
        if category:
            datasets = [d for d in datasets if d.category == category]
        return datasets
    
    def get_available_models(
        self,
        model_type: Optional[ModelType] = None,
    ) -> List[ModelArtifact]:
        """Get list of available model artifacts."""
        models = list(self._models.values())
        if model_type:
            models = [m for m in models if m.model_type == model_type]
        return models
    
    def cleanup_old_data(self, max_age_days: Optional[int] = None) -> int:
        """Remove datasets older than max age."""
        max_age = max_age_days or self._config.max_data_age_days
        cutoff = datetime.utcnow() - timedelta(days=max_age)
        
        removed = 0
        for dataset_id, dataset in list(self._datasets.items()):
            if dataset.last_accessed < cutoff:
                storage_path = Path(dataset.storage_path)
                if storage_path.exists():
                    storage_path.unlink()
                del self._datasets[dataset_id]
                removed += 1
        
        if removed > 0:
            self._save_metadata()
            logger.info(f"Removed {removed} old datasets")
        
        return removed
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        total_data_size = sum(d.file_size_bytes for d in self._datasets.values())
        total_model_size = sum(m.file_size_bytes for m in self._models.values())
        
        by_category = {}
        for category in DataCategory:
            size = sum(
                d.file_size_bytes for d in self._datasets.values()
                if d.category == category
            )
            by_category[category.value] = size / 1024 / 1024
        
        by_model_type = {}
        for model_type in ModelType:
            size = sum(
                m.file_size_bytes for m in self._models.values()
                if m.model_type == model_type
            )
            by_model_type[model_type.value] = size / 1024 / 1024
        
        return {
            "total_datasets": len(self._datasets),
            "total_models": len(self._models),
            "total_data_size_mb": total_data_size / 1024 / 1024,
            "total_model_size_mb": total_model_size / 1024 / 1024,
            "total_size_mb": (total_data_size + total_model_size) / 1024 / 1024,
            "max_cache_size_gb": self._config.max_cache_size_gb,
            "data_by_category_mb": by_category,
            "models_by_type_mb": by_model_type,
            "offline_mode_enabled": self._config.enabled,
        }


_store: Optional[OfflineDataStore] = None
_store_lock = threading.Lock()


def get_offline_data_store() -> OfflineDataStore:
    """Get global OfflineDataStore instance."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = OfflineDataStore()
    return _store
