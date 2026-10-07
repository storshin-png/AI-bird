"""
Создание PyTorch DataLoader'ов для обучения NN1.
Вход: manifest_fragments.csv + папка спектрограмм
Выход: train_loader, val_loader, test_loader (для демонстрации)
"""
import argparse
import torch
from torch.utils.data import Dataset, DataLoader
import pandas as pd
import numpy as np
from pathlib import Path


class BirdSpectrogramDataset(Dataset):
    """Датасет для загрузки спектрограмм из манифеста."""
    
    def __init__(self, manifest_path, spectro_dir, split):
        self.df = pd.read_csv(manifest_path)
        self.df = self.df[self.df["split"] == split].reset_index(drop=True)
        self.spectro_dir = Path(spectro_dir)
        
        if len(self.df) == 0:
            print(f"[WARN] Нет фрагментов в сплите '{split}'")
    
    def __len__(self):
        return len(self.df)
    
    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        # Имя файла спектрограммы: заменяем .wav на .npy
        npy_name = row["fragment_id"].replace(".wav", ".npy")
        npy_path = self.spectro_dir / npy_name
        
        # Загрузка спектрограммы
        if not npy_path.exists():
            raise FileNotFoundError(f"Спектрограмма не найдена: {npy_path}")
        
        spectrogram = np.load(npy_path)  # shape: (128, ~218)
        
        # Нормализация (per-sample)
        spectrogram = (spectrogram - spectrogram.mean()) / (spectrogram.std() + 1e-8)
        
        # Добавляем канал (для CNN: [1, 128, ~218])
        spectrogram = spectrogram[np.newaxis, ...]
        
        # Метка: bird=1, no_bird=0
        label = 1 if row["label"] == "bird" else 0
        
        return (
            torch.tensor(spectrogram, dtype=torch.float32),
            torch.tensor(label, dtype=torch.long)
        )


def main():
    parser = argparse.ArgumentParser(
        description="Создание DataLoader'ов для обучения NN1"
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Путь к CSV манифесту фрагментов"
    )
    parser.add_argument(
        "--spectro",
        required=True,
        help="Папка со спектрограммами .npy"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Размер батча (по умолчанию: 32)"
    )
    args = parser.parse_args()
    
    manifest_path = Path(args.manifest)
    spectro_dir = Path(args.spectro)
    
    # Проверка существования
    if not manifest_path.exists():
        print(f"[FAIL] Манифест не найден: {manifest_path}")
        return
    if not spectro_dir.exists():
        print(f"[FAIL] Папка спектрограмм не найдена: {spectro_dir}")
        return
    
    print("=" * 60)
    print("СОЗДАНИЕ DATALOADER'ОВ")
    print("=" * 60)
    print(f"  Манифест: {manifest_path}")
    print(f"  Спектрограммы: {spectro_dir}")
    print(f"  Batch size: {args.batch_size}")
    
    # Создание датасетов
    train_dataset = BirdSpectrogramDataset(manifest_path, spectro_dir, "train")
    val_dataset = BirdSpectrogramDataset(manifest_path, spectro_dir, "val")
    test_dataset = BirdSpectrogramDataset(manifest_path, spectro_dir, "test")
    
    print(f"\n  Train: {len(train_dataset)} фрагментов")
    print(f"  Val:   {len(val_dataset)} фрагментов")
    print(f"  Test:  {len(test_dataset)} фрагментов")
    
    # Создание DataLoader'ов
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,  # Для Windows: 0, чтобы избежать проблем с multiprocessing
        pin_memory=True
    )
    
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=True
    )
    
    test_loader = DataLoader(
        test_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=True
    )
    
    # Тестовая загрузка одного батча
    print("\n" + "=" * 60)
    print("ТЕСТОВАЯ ЗАГРУЗКА БАТЧА")
    print("=" * 60)
    
    try:
        for split_name, loader in [("train", train_loader), ("val", val_loader), ("test", test_loader)]:
            if len(loader.dataset) == 0:
                print(f"  [{split_name}] Пропущен (нет данных)")
                continue
            
            batch_x, batch_y = next(iter(loader))
            print(f"  [{split_name}]")
            print(f"    Форма батча X: {batch_x.shape}")
            print(f"    Форма батча Y: {batch_y.shape}")
            print(f"    Пример меток: {batch_y[:8].tolist()}")
            print(f"    Баланс в батче: bird={batch_y.sum().item()}, no_bird={len(batch_y) - batch_y.sum().item()}")
        
        print("\n[OK] DataLoader'ы созданы и работают корректно")
        
    except Exception as e:
        print(f"\n[FAIL] Ошибка при загрузке батча: {e}")
        return
    
    # Сохранение информации о DataLoader'ах
    info = {
        "manifest": str(manifest_path),
        "spectro_dir": str(spectro_dir),
        "batch_size": args.batch_size,
        "train_size": len(train_dataset),
        "val_size": len(val_dataset),
        "test_size": len(test_dataset),
        "input_shape": tuple(batch_x.shape[1:]),  # без batch dimension
    }
    
    print("\n" + "=" * 60)
    print("ИНФОРМАЦИЯ ДЛЯ ОБУЧЕНИЯ")
    print("=" * 60)
    for k, v in info.items():
        print(f"  {k}: {v}")
    
    # Возврат DataLoader'ов (для использования в скрипте обучения)
    return train_loader, val_loader, test_loader


if __name__ == "__main__":
    main()